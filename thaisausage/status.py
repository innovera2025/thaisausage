"""One screen showing what the integration has actually done.

Answers the questions an operator asks every morning: did the schedule keep running, how many
orders reached eVRP, what is stuck, what came back from eVRP, and what is waiting to be written
into ERP. It reads the local database only — no ERP connection, no eVRP call — so it is safe to
run at any time and cannot change anything.

    python -m thaisausage.status --config config/local.json
    python -m thaisausage.status --config config/local.json --days 7
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .config import load_config

# Anything in this list means a human has to look; everything else is the system working.
NEEDS_ATTENTION = ("failed", "needs_review", "conflict", "rejected", "error")


def rows(db, sql, parameters=()):
    try:
        return db.execute(sql, parameters).fetchall()
    except sqlite3.OperationalError:
        return []  # A table this build does not have yet is simply empty.


def since(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def counted(db, table, column, cutoff, time_column):
    return rows(db, "SELECT %s, COUNT(*) FROM %s WHERE %s >= ? GROUP BY %s ORDER BY 2 DESC"
                % (column, table, time_column, column), (cutoff,))


def section(title, pairs, empty):
    print("\n" + title)
    if not pairs:
        print("  " + empty)
        return
    for name, count in pairs:
        mark = "  <<" if (name or "") in NEEDS_ATTENTION else ""
        print("  %-18s %6d%s" % (name or "(ไม่ระบุ)", count, mark))


def parsed(value):
    """JSON if it is JSON, otherwise the value itself; stored results are not always objects."""
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def reasons(result):
    """Say why a submission failed, in eVRP's own words.

    eVRP answers a rejection with a per-order list of field errors, stored as a JSON string
    inside the result. Truncating that string shows only the envelope, which is the same for
    every failure and says nothing. This digs out the part that differs.
    """
    data = parsed(result)
    if not isinstance(data, dict):
        return [str(result)[:160]]
    detail = parsed(data.get("upstream_error")) or {}
    lines = []
    if isinstance(detail, dict):
        for order in detail.get("results") or []:
            if not isinstance(order, dict):
                continue
            for error in order.get("errors") or []:
                if not isinstance(error, dict):
                    continue
                lines.append("%s · %s · %s" % (
                    order.get("order_no") or "?",
                    error.get("code") or error.get("field") or "?",
                    (error.get("message") or "").strip()))
        for error in detail.get("global_errors") or []:
            lines.append(str(error)[:160])
    if lines:
        return lines
    for key in ("reason", "error", "detail", "upstream_error"):
        if data.get(key):
            return [str(data[key])[:160]]
    return [json.dumps(data, ensure_ascii=False)[:160]]


def main():
    parser = argparse.ArgumentParser(description="Show what the integration has done lately")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    config = load_config(args.config)
    cutoff = since(args.days)
    db = sqlite3.connect(config["database"])
    try:
        print("ช่วงเวลา : %d วันล่าสุด" % args.days)
        print("โหมด     : %s" % ("dry_run (ไม่ส่งจริง)" if config.get("dry_run") else "ส่งจริง"))
        write = config.get("do_write") or {}
        print("เขียน DO : %s" % ("อัตโนมัติ" if write.get("enabled") else "ต้องสั่งเองทีละใบ"))

        section("SO ที่ส่งไป eVRP", counted(db, "submissions", "state", cutoff, "created_at"),
                "ยังไม่มีการส่งในช่วงนี้")
        section("DO ที่ eVRP ส่งเข้ามา", counted(db, "do_receipts", "state", cutoff, "received_at"),
                "ยังไม่มี DO เข้ามาในช่วงนี้")
        section("การเขียน DO ลง ERP", counted(db, "do_writes", "state", cutoff, "updated_at"),
                "ยังไม่มีการเขียนในช่วงนี้")

        staged = rows(db, "SELECT r.receipt_id, r.do_no, r.received_at FROM do_receipts r "
                          "LEFT JOIN do_writes w ON w.receipt_key = r.receipt_key "
                          "WHERE w.receipt_key IS NULL ORDER BY r.received_at DESC LIMIT 20")
        print("\nDO ที่ยังไม่ได้เขียนลง ERP")
        if not staged:
            print("  ไม่มีค้าง")
        for receipt_id, do_no, received_at in staged:
            print("  %-22s %-16s %s" % (receipt_id, do_no or "-", received_at))

        problems = rows(db, "SELECT receipt_id, state, reason, updated_at FROM do_writes "
                            "WHERE state IN (%s) ORDER BY updated_at DESC LIMIT 20"
                        % ",".join("?" * len(NEEDS_ATTENTION)), NEEDS_ATTENTION)
        print("\nรายการที่ต้องให้คนดู")
        if not problems:
            print("  ไม่มี")
        for receipt_id, state, reason, updated_at in problems:
            print("  %-22s %-12s %s  %s" % (receipt_id, state, updated_at, (reason or "")[:60]))

        failures = rows(db, "SELECT request_id, result, created_at FROM submissions "
                            "WHERE state IN ('failed','needs_review') AND created_at >= ? "
                            "ORDER BY created_at DESC LIMIT 20", (cutoff,))
        print("\nSO ที่ส่งไม่สำเร็จ")
        if not failures:
            print("  ไม่มี")
        for request_id, result, created_at in failures:
            print("  %-42s %s" % (request_id, created_at))
            for line in reasons(result):
                print("    %s" % line[:150])

        latest = rows(db, "SELECT MAX(created_at) FROM submissions")
        print("\nส่ง SO ครั้งล่าสุด :", (latest[0][0] if latest and latest[0][0] else "ยังไม่เคยส่ง"))
    finally:
        db.close()


if __name__ == "__main__":
    main()
