"""Read a written DO back out of ERP and compare it with what we sent.

Counting rows proves something arrived; this proves the right values landed in the right columns.
It reads with the read-only credential and one plain SELECT per table, so it is safe to run at any
time, including against a document the ERP team keyed in themselves.

    python -m thaisausage.verify_do --config config/local.json --transaction-no 11504

Add --receipt-id to compare against the staged payload instead of only printing what ERP holds:

    python -m thaisausage.verify_do --config config/local.json \\
        --transaction-no 11504 --receipt-id TEST-ERP-001
"""

import argparse
import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal

from .config import load_config
from .connectors import lookup
from .contracts import ContractError
from .do_writer import _COLUMN
from .service import receipt_key
from .sqlserver import SQLServerConnector, approved_identifier


def columns_of(mapping):
    """Return the configured column names, refusing anything that is not a plain identifier."""
    names = []
    for column in (mapping or {}):
        if not _COLUMN.fullmatch(column):
            raise ContractError("ERP column name must come from the reviewed configuration")
        names.append(column)
    if not names:
        raise ContractError("do_write column mapping is not configured")
    return names


def read_rows(connector, connection, table, columns, transaction_no, order_by=None):
    sql = "SELECT %s FROM %s WHERE TransactionNo = ?" % (
        ", ".join(columns), approved_identifier(table))
    if order_by:
        sql += " ORDER BY " + order_by
    return connector.select_approved(connection, sql, (transaction_no,))


def staged_payload(database, source, receipt_id):
    key = receipt_key(source, receipt_id)
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT payload FROM do_receipts WHERE receipt_key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def comparable(value):
    """Reduce a value to the form both sides can be judged by.

    ERP pads char columns, returns money as Decimal and dates as datetime, so a literal
    comparison would report differences that are not differences.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        return text or None


def expected(spec, source, transaction_no, line_no):
    """What we intended this column to hold, or None when only ERP decides."""
    kind = spec.get("source")
    if kind == "payload":
        return lookup(source, spec.get("path"))
    if kind == "fixed":
        return spec.get("value")
    if kind == "transaction_no":
        return transaction_no
    if kind == "line_no":
        return line_no
    return None  # server_time is the SQL Server clock; we have nothing to compare it against.


def report(title, mapping, erp_row, payload, transaction_no, line_no, show_empty):
    print("\n" + title)
    print("  %-24s %-28s %-28s" % ("คอลัมน์", "ที่เราส่งไป", "ที่อยู่ใน ERP"))
    differences = 0
    for column, spec in mapping.items():
        actual = erp_row.get(column)
        if spec.get("source") == "server_time":
            print("  %-24s %-28s %-28s  (ERP กำหนดเอง)" % (column, "—", actual))
            continue
        want = None if payload is None else expected(spec, payload, transaction_no, line_no)
        if not show_empty and comparable(want) is None and comparable(actual) is None:
            continue
        if payload is None:
            print("  %-24s %-28s %-28s" % (column, "—", actual))
            continue
        same = comparable(want) == comparable(actual)
        differences += 0 if same else 1
        print("  %-24s %-28s %-28s  %s" % (column, want, actual, "ตรง" if same else "ไม่ตรง <<"))
    return differences


def main():
    parser = argparse.ArgumentParser(description="Read a DO back out of ERP and check it")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--transaction-no", required=True, type=int)
    parser.add_argument("--receipt-id", help="compare against the payload staged under this receipt")
    parser.add_argument("--source", default="eVRP")
    parser.add_argument("--all-columns", action="store_true",
                        help="also print columns that are empty on both sides")
    args = parser.parse_args()

    config = load_config(args.config)
    do_write = config.get("do_write") or {}
    header_map, detail_map = do_write.get("header_columns"), do_write.get("detail_columns")
    header_columns, detail_columns = columns_of(header_map), columns_of(detail_map)

    payload = None
    if args.receipt_id:
        payload = staged_payload(config["database"], args.source, args.receipt_id)
        if payload is None:
            print("ไม่พบใบที่ staged ไว้สำหรับ %s:%s — จะแสดงเฉพาะค่าที่อยู่ใน ERP"
                  % (args.source, args.receipt_id))

    connector = SQLServerConnector(config.get("sqlserver", {}))
    connection = connector.connect()
    try:
        headers = read_rows(connector, connection, do_write.get("header_table"),
                            header_columns, args.transaction_no)
        details = read_rows(connector, connection, do_write.get("detail_table"),
                            detail_columns, args.transaction_no, order_by="Slno")
    finally:
        connection.close()

    print("TransactionNo :", args.transaction_no)
    print("หัวเอกสาร     :", len(headers), "แถว")
    print("รายละเอียด    :", len(details), "แถว")
    if not headers:
        raise SystemExit("ไม่พบเอกสารเลขนี้ใน ERP")

    differences = 0
    for row in headers:
        differences += report("หัวเอกสาร", header_map, row, payload.get("header") if payload else None,
                              args.transaction_no, None, args.all_columns)
    lines = payload.get("details") if payload else None
    start = int(do_write.get("detail_line_start", 1))
    for index, row in enumerate(details):
        line = lines[index] if lines and index < len(lines) else None
        differences += report("รายละเอียดบรรทัดที่ %d" % (start + index), detail_map, row, line,
                              args.transaction_no, start + index, args.all_columns)

    print()
    if payload is None:
        print("แสดงค่าที่อยู่ใน ERP เท่านั้น (ไม่ได้ระบุ --receipt-id จึงไม่มีอะไรให้เทียบ)")
    elif differences:
        raise SystemExit("พบ %d คอลัมน์ที่ไม่ตรงกัน" % differences)
    else:
        print("ทุกคอลัมน์ตรงกับที่ส่งไป")


if __name__ == "__main__":
    main()
