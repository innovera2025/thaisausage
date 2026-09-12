import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .connectors import RemoteError
from .contracts import validate_orders


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
                    received_at TEXT NOT NULL
                );
            """)
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
        """Persist a trigger; a later SQL sweep owns the full payload read."""
        from .contracts import require, text
        require(text(hook.get("event_id")) and len(hook["event_id"]) <= 120,
                "event_id is required and must be <= 120 characters")
        require(hook.get("event_type") in ("sales_order.ready", "sales_order.changed"),
                "event_type must be sales_order.ready or sales_order.changed")
        require(text(hook.get("source_id")), "source_id is required")
        require(hook.get("order_no") is None or text(hook["order_no"]),
                "order_no must be a non-empty string when supplied")
        now = datetime.now(timezone.utc).isoformat()
        db = self.connect()
        try:
            with db:
                row = db.execute("SELECT state FROM erp_hooks WHERE event_id=?", (hook["event_id"],)).fetchone()
                if row:
                    return {"event_id": hook["event_id"], "state": row[0], "replayed": True}
                db.execute(
                    "INSERT INTO erp_hooks(event_id,event_type,source_id,company_id,order_no,changed_at,state,received_at) VALUES (?,?,?,?,?,?,?,?)",
                    (hook["event_id"], hook["event_type"], hook["source_id"], hook.get("company_id"), hook.get("order_no"), hook.get("changed_at"), "received", now))
                return {"event_id": hook["event_id"], "state": "received", "sweep": "queued"}
        finally:
            db.close()

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
