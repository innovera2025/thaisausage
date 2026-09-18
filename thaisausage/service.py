import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone

from .connectors import RemoteError
from .contracts import ContractError, validate_orders
from .do_writer import DOWriteAmbiguous, DOWriteDisabled


logger = logging.getLogger(__name__)


class Conflict(ValueError):
    pass


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def receipt_key(source, receipt_id):
    """Scope a DO receipt to the channel that delivered it, e.g. `eVRP:DO-0001`."""
    return "%s:%s" % (source, receipt_id)


def safe_identifier(value):
    """Return an identifier that is safe to log, or a placeholder.

    Logs carry identifiers only. Anything that is not a plain document-style identifier could be
    mapped customer data, so it never reaches the log.
    """
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:\-]{1,120}", value):
        return value
    return "<redacted>"


class IntegrationService:
    def __init__(self, database, dry_run, vrp, erp):
        self.database, self.dry_run, self.vrp, self.erp = database, dry_run, vrp, erp
        db = self.connect()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS submissions (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS order_claims (
                    order_no TEXT PRIMARY KEY, request_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS erp_hooks (
                    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                    source_id TEXT NOT NULL, company_id TEXT,
                    order_no TEXT, changed_at TEXT, state TEXT NOT NULL,
                    received_at TEXT NOT NULL, payload_hash TEXT, reason TEXT
                );
                CREATE TABLE IF NOT EXISTS do_receipts (
                    receipt_key TEXT PRIMARY KEY, source TEXT NOT NULL, receipt_id TEXT NOT NULL,
                    do_no TEXT, payload_hash TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS do_writes (
                    receipt_key TEXT PRIMARY KEY, source TEXT NOT NULL, receipt_id TEXT NOT NULL,
                    do_no TEXT, transaction_no TEXT, payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS do_writes_do_no
                    ON do_writes(do_no) WHERE do_no IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS do_writes_transaction_no
                    ON do_writes(transaction_no) WHERE transaction_no IS NOT NULL;
            """)
        finally:
            db.close()
        self._migrate_columns()
        self._migrate_do_identity()

    def _migrate_do_identity(self):
        """Move older DO tables onto source-scoped receipt keys without losing rows."""
        rebuilds = {
            "do_receipts": """
                CREATE TABLE do_receipts_new (
                    receipt_key TEXT PRIMARY KEY, source TEXT NOT NULL, receipt_id TEXT NOT NULL,
                    do_no TEXT, payload_hash TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL, received_at TEXT NOT NULL);
                INSERT INTO do_receipts_new
                    SELECT COALESCE(source,'erp')||':'||receipt_id, COALESCE(source,'erp'), receipt_id,
                           do_no, payload_hash, payload, state, received_at FROM do_receipts;
                DROP TABLE do_receipts;
                ALTER TABLE do_receipts_new RENAME TO do_receipts;
            """,
            "do_writes": """
                CREATE TABLE do_writes_new (
                    receipt_key TEXT PRIMARY KEY, source TEXT NOT NULL, receipt_id TEXT NOT NULL,
                    do_no TEXT, transaction_no TEXT, payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL);
                INSERT INTO do_writes_new
                    SELECT 'erp:'||receipt_id, 'erp', receipt_id, do_no, transaction_no,
                           payload_hash, state, reason, updated_at FROM do_writes;
                DROP TABLE do_writes;
                ALTER TABLE do_writes_new RENAME TO do_writes;
            """,
        }
        db = self.connect()
        try:
            for table, script in rebuilds.items():
                columns = {row[1] for row in db.execute("PRAGMA table_info(%s)" % table)}
                if columns and "receipt_key" not in columns:
                    db.executescript(script)
        finally:
            db.close()

    def _migrate_columns(self):
        """Add columns that older databases predate; each ALTER is idempotent."""
        additions = {"erp_hooks": {"payload_hash": "TEXT", "reason": "TEXT"},
                     "do_receipts": {"source": "TEXT"}}
        db = self.connect()
        try:
            with db:
                for table, columns in additions.items():
                    existing = {row[1] for row in db.execute("PRAGMA table_info(%s)" % table)}
                    for column, kind in columns.items():
                        if column not in existing:
                            db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, kind))
        finally:
            db.close()

    def connect(self):
        return sqlite3.connect(self.database, timeout=10)

    def get(self, request_id):
        db = self.connect()
        try:
            row = db.execute("SELECT result FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def record_erp_hook(self, hook):
        """Persist a trigger; a realtime worker owns the full payload read."""
        from .contracts import require, text
        require(text(hook.get("event_id")) and len(hook["event_id"]) <= 120,
                "event_id is required and must be <= 120 characters")
        require(re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", hook["event_id"]) is not None,
                "event_id must be 1..120 characters: A-Z a-z 0-9 . _ : -")
        require(hook.get("event_type") in ("sales_order.ready", "sales_order.changed"),
                "event_type must be sales_order.ready or sales_order.changed")
        require(text(hook.get("source_id")), "source_id is required")
        require(hook.get("order_no") is None or text(hook["order_no"]),
                "order_no must be a non-empty string when supplied")
        digest = hashlib.sha256(canonical(hook).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        db = self.connect()
        try:
            with db:
                row = db.execute("SELECT state,payload_hash FROM erp_hooks WHERE event_id=?", (hook["event_id"],)).fetchone()
                if row:
                    if row[1] and row[1] != digest:
                        raise Conflict("event_id already used with different data")
                    return {"event_id": hook["event_id"], "state": row[0], "replayed": True}
                db.execute(
                    "INSERT INTO erp_hooks(event_id,event_type,source_id,company_id,order_no,changed_at,state,received_at,payload_hash,reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (hook["event_id"], hook["event_type"], hook["source_id"], hook.get("company_id"), hook.get("order_no"), hook.get("changed_at"), "received", now, digest, None))
                return {"event_id": hook["event_id"], "state": "received", "sweep": "queued"}
        finally:
            db.close()

    def receive_do(self, payload, source="erp"):
        """Stage a DO payload for inspection; this method never writes to ERP.

        Identity is scoped by `source`, so the same receipt number delivered by eVRP and by ERP
        stays two separate staged documents instead of colliding by accident. The claim is taken
        inside one immediate transaction, so concurrent callbacks replay instead of failing.
        """
        from .contracts import require, text
        require(isinstance(payload, dict), "DO body must be an object")
        require(text(source), "DO source is required")
        receipt_id = payload.get("receipt_id") or payload.get("do_no")
        require(text(receipt_id) and len(receipt_id) <= 120, "receipt_id or do_no is required")
        do_no = payload.get("do_no")
        require(do_no is None or text(do_no), "do_no must be a non-empty string when supplied")
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        key = receipt_key(source, receipt_id)
        answer = {"receipt_id": receipt_id, "receipt_key": key, "source": source, "erp_write": False}
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload_hash,state FROM do_receipts WHERE receipt_key=?", (key,)).fetchone()
            if row:
                if row[0] != digest:
                    raise Conflict("receipt_id already used with different data")
                return {**answer, "state": row[1], "replayed": True}
            db.execute("INSERT INTO do_receipts(receipt_key,source,receipt_id,do_no,payload_hash,payload,state,received_at)"
                       " VALUES (?,?,?,?,?,?,?,?)",
                       (key, source, receipt_id, do_no, digest, canonical(payload), "staged",
                        datetime.now(timezone.utc).isoformat()))
            db.commit()
            return {**answer, "state": "staged"}
        finally:
            db.close()

    # A DO write that never reached ERP may be retried after the cause is fixed.
    RETRYABLE_WRITE_STATES = ("preview", "disabled", "rejected", "rehearsed")

    def write_do(self, receipt_id, writer, source="erp", transaction_no=None):
        """Write one staged DO into ERP behind the writer feature flag.

        Returns None when the receipt was never staged for this source. This method performs no
        ERP write in dry-run mode and no write while the writer flag is disabled.
        """
        from .contracts import require, text
        require(text(receipt_id), "receipt_id is required")
        require(text(source), "DO source is required")
        key = receipt_key(source, receipt_id)
        db = self.connect()
        try:
            row = db.execute("SELECT payload,payload_hash,do_no FROM do_receipts WHERE receipt_key=?",
                             (key,)).fetchone()
        finally:
            db.close()
        if not row:
            return None
        payload, digest, staged_do_no = json.loads(row[0]), row[1], row[2]
        transaction_no = transaction_no or payload.get("transaction_no")
        do_no = payload.get("do_no") or staged_do_no
        # The writer may allocate the number itself; then it is only known after the write.
        allocates = getattr(writer, "auto_transaction_no", False)
        require(allocates or text(transaction_no),
                "transaction_no is required before an ERP DO write")
        now = datetime.now(timezone.utc).isoformat()
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            claimed = db.execute("SELECT state,payload_hash,reason FROM do_writes WHERE receipt_key=?",
                                 (key,)).fetchone()
            if claimed:
                if claimed[1] != digest:
                    raise Conflict("receipt_id already written with different data")
                if claimed[0] not in self.RETRYABLE_WRITE_STATES:
                    return {"receipt_id": receipt_id, "receipt_key": key, "source": source,
                            "state": claimed[0], "reason": claimed[2],
                            "transaction_no": transaction_no, "replayed": True}
                db.execute("UPDATE do_writes SET state='pending',reason=NULL,updated_at=? WHERE receipt_key=?",
                           (now, key))
            else:
                try:
                    db.execute("INSERT INTO do_writes VALUES (?,?,?,?,?,?,?,?,?)",
                               (key, source, receipt_id, do_no, transaction_no, digest, "pending", None, now))
                except sqlite3.IntegrityError:
                    raise Conflict("do_no or transaction_no is already claimed by another DO write")
            db.commit()
        finally:
            db.close()
        detail = {}
        try:
            if self.dry_run:
                # Preview proves the mapping without opening a database connection.
                state, reason = "preview", "dry_run_preview"
                detail = {"statements": len(writer.prepare(payload, transaction_no))}
            else:
                detail = writer.write(payload, transaction_no)
                # A rehearsal executes against the real tables and then rolls back, so it proves
                # permission and statement shape without leaving a document behind.
                state = "inserted" if detail.get("committed") else "rehearsed"
                reason = None if state == "inserted" else "rollback_only"
        except DOWriteDisabled:
            state, reason = "disabled", "do_write_disabled"
        except DOWriteAmbiguous as error:
            state, reason = "needs_review", str(error)
        except ContractError as error:
            state, reason = "rejected", str(error)
        except Exception as error:
            state, reason = "needs_review", type(error).__name__
        # An allocated number is only known once the write ran; record it against the claim.
        transaction_no = detail.get("transaction_no") or transaction_no
        db = self.connect()
        try:
            with db:
                db.execute("UPDATE do_writes SET state=?,reason=?,transaction_no=?,updated_at=? WHERE receipt_key=?",
                           (state, reason, transaction_no, datetime.now(timezone.utc).isoformat(), key))
        finally:
            db.close()
        if reason:
            # `reason` is always generated by this codebase, never copied from a payload.
            logger.warning("do write receipt=%s state=%s reason=%s", safe_identifier(key), state, reason)
        return {"receipt_id": receipt_id, "receipt_key": key, "source": source,
                "state": state, "reason": reason,
                "transaction_no": transaction_no, **detail}

    def attempt_do_write(self, receipt_id, writer, source, transaction_no=None):
        """Try an ERP DO write without letting its outcome change the staging answer.

        The DO is already staged by the time this runs, so every failure becomes a recorded state
        for an operator instead of an error raised back at eVRP.
        """
        if not transaction_no and not getattr(writer, "auto_transaction_no", False):
            # Nobody can supply the number: eVRP does not send one and this writer does not
            # allocate one. Writing would fail on a NOT NULL primary key column.
            result = {"state": "skipped", "reason": "transaction_no_missing"}
        else:
            try:
                result = self.write_do(receipt_id, writer, source=source, transaction_no=transaction_no)
                if result is None:
                    result = {"state": "skipped", "reason": "receipt_not_staged"}
            except Conflict as error:
                result = {"state": "conflict", "reason": str(error)}
            except ContractError as error:
                result = {"state": "rejected", "reason": str(error)}
            except Exception as error:
                result = {"state": "needs_review", "reason": type(error).__name__}
        if result["state"] in ("skipped", "conflict"):
            # Other states are already logged by write_do when it records them.
            logger.warning("do write not applied receipt=%s state=%s reason=%s",
                           safe_identifier(receipt_key(source, receipt_id)),
                           result["state"], result.get("reason"))
        return result

    def sweep_hooks(self, sqlserver):
        """Read queued hook keys from SQL Server and submit mapped SOs."""
        db = self.connect()
        try:
            hooks = db.execute("SELECT event_id,order_no FROM erp_hooks WHERE state='received' ORDER BY received_at LIMIT 100").fetchall()
        finally:
            db.close()
        results = []
        for event_id, order_no in hooks:
            try:
                if not order_no:
                    state, reason = "review", "order_no_required"
                    raise StopIteration
                orders = sqlserver.fetch_orders(order_no)
                rejected = next((order["rejected_reason"] for order in orders
                                 if isinstance(order, dict) and order.get("rejected_reason")), None)
                if not orders:
                    state, reason = "review", "sql_order_not_found"
                elif rejected:
                    state, reason = "review", rejected
                else:
                    request_id = "HOOK-" + event_id[:110]
                    result = self.submit({"request_id": request_id, "orders": orders})
                    if self.dry_run:
                        state, reason = "received", "dry_run_preview"
                    else:
                        state, reason = result["state"], None
            except StopIteration:
                pass
            except Exception as error:
                state, reason = "review", type(error).__name__
            db = self.connect()
            try:
                with db:
                    db.execute("UPDATE erp_hooks SET state=?, reason=? WHERE event_id=?", (state, reason, event_id))
            finally:
                db.close()
            results.append({"event_id": event_id, "state": state, "reason": reason})
            if reason:
                logger.warning("hook sweep review event_id=%s reason=%s", safe_identifier(event_id), reason)
        return results

    def sweep_approved_orders(self, sqlserver):
        """Read the configured approved-SO query and submit each new order.

        Each order is isolated: one unmappable or conflicting SO must not stop the
        rest of the approved batch from reaching eVRP in this cycle.
        """
        try:
            orders = sqlserver.fetch_approved_orders()
        except Exception as error:
            # The batch cannot be attributed to individual SOs, so it stops with a known state.
            reason = type(error).__name__
            logger.warning("scheduled sweep could not read the approved-SO query: %s", reason)
            return [{"order_no": None, "state": "review", "reason": reason}]
        results = []
        for order in orders:
            order_no = order.get("order_no") if isinstance(order, dict) else None
            if not isinstance(order_no, str) or not order_no.strip():
                results.append({"order_no": None, "state": "review", "reason": "order_no_missing"})
                logger.warning("scheduled sweep skipped a row without a usable order_no")
                continue
            if order.get("rejected_reason"):
                results.append({"order_no": order_no, "state": "review", "reason": order["rejected_reason"]})
                logger.warning("scheduled sweep rejected order_no=%s reason=%s",
                               safe_identifier(order_no), order["rejected_reason"])
                continue
            try:
                # eVRP keeps a request_id even when it refuses the payload, so a corrected
                # order needs a new identity: the id follows the order and its content.
                request_id = "SCHEDULE-%s-%s" % (
                    hashlib.sha256(order_no.encode()).hexdigest()[:16],
                    hashlib.sha256(canonical(order).encode()).hexdigest()[:12])
                db = self.connect()
                try:
                    claimed = db.execute(
                        "SELECT s.state FROM order_claims c LEFT JOIN submissions s ON s.request_id=c.request_id"
                        " WHERE c.order_no=?", (order_no,)).fetchone()
                finally:
                    db.close()
                if claimed and not self.dry_run:
                    # An unresolved earlier attempt stays visible instead of being skipped silently.
                    prior = claimed[0]
                    if prior in ("sending", "needs_review"):
                        results.append({"order_no": order_no, "state": "needs_review",
                                        "reason": "prior_attempt_" + prior})
                    else:
                        results.append({"order_no": order_no, "state": "skipped",
                                        "reason": "already_sent" if prior == "sent" else "already_claimed"})
                    continue
                result = self.submit({"request_id": request_id, "orders": [order]})
                if self.dry_run:
                    results.append({"order_no": order_no, "state": "preview", "reason": "dry_run_preview"})
                else:
                    results.append({"order_no": order_no, "state": result["state"],
                                    "reason": result.get("reason")})
            except Exception as error:
                reason = type(error).__name__
                results.append({"order_no": order_no, "state": "review", "reason": reason})
                logger.warning("scheduled sweep review order_no=%s reason=%s",
                               safe_identifier(order_no), reason)
        return results

    def submit(self, payload):
        validate_orders(payload)
        request_id = payload["request_id"]
        if self.dry_run:
            return {"request_id": request_id, "state": "validated", "dry_run": True,
                    "order_count": len(payload["orders"]), "mapped_payload": payload}
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        result = {"request_id": request_id, "state": "sending", "dry_run": False}
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload_hash, result FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[0] != digest:
                    raise Conflict("request_id already used with different data")
                return {**json.loads(row[1]), "replayed": True}
            for order in payload["orders"]:
                claimed = db.execute("SELECT request_id FROM order_claims WHERE order_no=?", (order["order_no"],)).fetchone()
                if claimed:
                    raise Conflict("order_no already submitted under another request_id")
                db.execute("INSERT INTO order_claims VALUES (?, ?)", (order["order_no"], request_id))
            db.execute("INSERT INTO submissions VALUES (?, ?, ?, ?, ?)",
                       (request_id, digest, "sending", canonical(result), datetime.now(timezone.utc).isoformat()))
            db.commit()
        finally:
            db.close()
        # A timeout or crash can occur AFTER VRP accepted data. Never automatically resend.
        try:
            response = self.vrp.send(payload)
            if isinstance(response, dict) and response.get("success") is True:
                result["state"] = "sent"
                result["vrp"] = {key: response[key] for key in (
                    "request_id", "batch_uuid", "status", "mode", "summary", "idempotent_replay"
                ) if key in response}
                result["vrp"]["orders"] = [
                    {key: order[key] for key in ("order_no", "status", "action", "running_id", "running_code") if key in order}
                    for order in response.get("results", []) if isinstance(order, dict)
                ]
            else:
                result["state"] = "needs_review"
                result["reason"] = "upstream_response_not_confirmed"
        except RemoteError as error:
            result["state"] = "needs_review"
            result["reason"] = "upstream_http_%s" % error.status if error.status else "upstream_outcome_unknown"
            if error.detail:
                # Kept so an operator can see why the upstream refused, without a second send.
                result["upstream_error"] = error.detail[:2000]
        except Exception:
            result["state"] = "needs_review"
            result["reason"] = "connector_error"
        db = self.connect()
        try:
            with db:
                db.execute("UPDATE submissions SET state=?, result=? WHERE request_id=?",
                           (result["state"], canonical(result), request_id))
        finally:
            db.close()
        return result
