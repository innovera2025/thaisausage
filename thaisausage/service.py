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
                    receipt_id TEXT PRIMARY KEY, do_no TEXT, payload_hash TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL, received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS do_writes (
                    receipt_id TEXT PRIMARY KEY, do_no TEXT, transaction_no TEXT,
                    payload_hash TEXT NOT NULL, state TEXT NOT NULL, reason TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS do_writes_do_no
                    ON do_writes(do_no) WHERE do_no IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS do_writes_transaction_no
                    ON do_writes(transaction_no) WHERE transaction_no IS NOT NULL;
            """)
        finally:
            db.close()
        self._migrate_hook_columns()

    def _migrate_hook_columns(self):
        db = self.connect()
        try:
            columns = {row[1] for row in db.execute("PRAGMA table_info(erp_hooks)")}
            with db:
                if "payload_hash" not in columns:
                    db.execute("ALTER TABLE erp_hooks ADD COLUMN payload_hash TEXT")
                if "reason" not in columns:
                    db.execute("ALTER TABLE erp_hooks ADD COLUMN reason TEXT")
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

    def receive_do(self, payload):
        """Stage a DO payload for inspection; this method never writes to ERP."""
        from .contracts import require, text
        require(isinstance(payload, dict), "DO body must be an object")
        receipt_id = payload.get("receipt_id") or payload.get("do_no")
        require(text(receipt_id) and len(receipt_id) <= 120, "receipt_id or do_no is required")
        do_no = payload.get("do_no")
        require(do_no is None or text(do_no), "do_no must be a non-empty string when supplied")
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        db = self.connect()
        try:
            with db:
                row = db.execute("SELECT payload_hash,state FROM do_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
                if row:
                    if row[0] != digest:
                        raise Conflict("receipt_id already used with different data")
                    return {"receipt_id": receipt_id, "state": row[1], "replayed": True}
                db.execute("INSERT INTO do_receipts VALUES (?,?,?,?,?,?)",
                           (receipt_id, do_no, digest, canonical(payload), "staged", datetime.now(timezone.utc).isoformat()))
                return {"receipt_id": receipt_id, "state": "staged", "erp_write": False}
        finally:
            db.close()

    # A DO write that never reached ERP may be retried after the cause is fixed.
    RETRYABLE_WRITE_STATES = ("preview", "disabled", "rejected")

    def write_do(self, receipt_id, writer, transaction_no=None):
        """Write one staged DO into ERP behind the writer feature flag.

        Returns None when the receipt was never staged. This method performs no ERP
        write in dry-run mode and no write while the writer flag is disabled.
        """
        from .contracts import require, text
        require(text(receipt_id), "receipt_id is required")
        db = self.connect()
        try:
            row = db.execute("SELECT payload,payload_hash,do_no FROM do_receipts WHERE receipt_id=?",
                             (receipt_id,)).fetchone()
        finally:
            db.close()
        if not row:
            return None
        payload, digest, staged_do_no = json.loads(row[0]), row[1], row[2]
        transaction_no = transaction_no or payload.get("transaction_no")
        do_no = payload.get("do_no") or staged_do_no
        require(text(transaction_no), "transaction_no is required before an ERP DO write")
        now = datetime.now(timezone.utc).isoformat()
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            claimed = db.execute("SELECT state,payload_hash,reason FROM do_writes WHERE receipt_id=?",
                                 (receipt_id,)).fetchone()
            if claimed:
                if claimed[1] != digest:
                    raise Conflict("receipt_id already written with different data")
                if claimed[0] not in self.RETRYABLE_WRITE_STATES:
                    return {"receipt_id": receipt_id, "state": claimed[0], "reason": claimed[2],
                            "transaction_no": transaction_no, "replayed": True}
                db.execute("UPDATE do_writes SET state='pending',reason=NULL,updated_at=? WHERE receipt_id=?",
                           (now, receipt_id))
            else:
                try:
                    db.execute("INSERT INTO do_writes VALUES (?,?,?,?,?,?,?)",
                               (receipt_id, do_no, transaction_no, digest, "pending", None, now))
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
                state, reason = "inserted", None
                detail = writer.write(payload, transaction_no)
        except DOWriteDisabled:
            state, reason = "disabled", "do_write_disabled"
        except DOWriteAmbiguous as error:
            state, reason = "needs_review", str(error)
        except ContractError as error:
            state, reason = "rejected", str(error)
        except Exception as error:
            state, reason = "needs_review", type(error).__name__
        db = self.connect()
        try:
            with db:
                db.execute("UPDATE do_writes SET state=?,reason=?,updated_at=? WHERE receipt_id=?",
                           (state, reason, datetime.now(timezone.utc).isoformat(), receipt_id))
        finally:
            db.close()
        if reason:
            logger.warning("do write receipt_id=%s state=%s reason=%s", receipt_id, state, reason)
        return {"receipt_id": receipt_id, "state": state, "reason": reason,
                "transaction_no": transaction_no, **detail}

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
                if not orders:
                    state, reason = "review", "sql_order_not_found"
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
                logger.warning("hook sweep review event_id=%s reason=%s", event_id, reason)
        return results

    def sweep_approved_orders(self, sqlserver):
        """Read the configured approved-SO query and submit each new order."""
        orders = sqlserver.fetch_approved_orders()
        results = []
        for order in orders:
            order_no = order["order_no"]
            digest = hashlib.sha256(order_no.encode()).hexdigest()[:32]
            request_id = "SCHEDULE-" + digest
            db = self.connect()
            try:
                claimed = db.execute("SELECT request_id FROM order_claims WHERE order_no=?", (order_no,)).fetchone()
            finally:
                db.close()
            if claimed and not self.dry_run:
                results.append({"order_no": order_no, "state": "skipped", "reason": "already_claimed"})
                continue
            result = self.submit({"request_id": request_id, "orders": [order]})
            if self.dry_run:
                results.append({"order_no": order_no, "state": "preview", "reason": "dry_run_preview"})
            else:
                results.append({"order_no": order_no, "state": result["state"],
                                "reason": result.get("reason")})
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
