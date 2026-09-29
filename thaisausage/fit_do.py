"""Check a staged DO against the shape of the ERP columns before writing it.

SQL Server 8152 says a value was too long but not which one, so a rejected document gives an
operator nothing to act on. This reads the column definitions and puts every mapped value next to
the room it has, which turns that into a list of exactly what to fix.

    python -m thaisausage.fit_do --config config/local.json --receipt-id DO2609260001

Read-only: one plain SELECT against INFORMATION_SCHEMA through the usual guard, with the
read-only credential. It never writes and never connects with the write credential.
"""

import argparse
from datetime import date, datetime
from decimal import Decimal

from .config import load_config
from .contracts import ContractError
from .service import receipt_key
from .sqlserver import SQLServerConnector
from .verify_do import expected, staged_payload


def column_shapes(connector, connection, table):
    """Column name to (type, max characters, precision, scale) for one reviewed table."""
    schema, _, name = table.partition(".")
    if not name:
        schema, name = "dbo", table
    rows = connector.select_approved(
        connection,
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        (schema.strip("[]"), name.strip("[]")))
    return {row["COLUMN_NAME"]: row for row in rows}


def measured(value):
    """How many characters this value takes once SQL Server stores it as text."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1
    if isinstance(value, (datetime, date)):
        return len(value.isoformat())
    return len(str(value))


def digits(value):
    """Digits left of the decimal point, which is what a numeric column runs out of room for."""
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        return 0
    return len(str(abs(int(value))))


def problems(mapping, shapes, payload, transaction_no, line_no, table):
    found = []
    for column, spec in mapping.items():
        shape = shapes.get(column)
        if shape is None:
            found.append((column, "ไม่มีคอลัมน์นี้ในตาราง %s" % table, None))
            continue
        value = expected(spec, payload or {}, transaction_no, line_no)
        if value is None:
            continue
        limit = shape.get("CHARACTER_MAXIMUM_LENGTH")
        if limit is not None and limit >= 0 and measured(value) > limit:
            found.append((column, "ยาว %d ตัวอักษร แต่คอลัมน์รับได้ %d (%s)"
                          % (measured(value), limit, shape["DATA_TYPE"]), value))
            continue
        precision, scale = shape.get("NUMERIC_PRECISION"), shape.get("NUMERIC_SCALE")
        if precision and digits(value) > precision - (scale or 0):
            found.append((column, "จำนวนเต็ม %d หลัก แต่คอลัมน์รับได้ %d หลัก (%s(%s,%s))"
                          % (digits(value), precision - (scale or 0), shape["DATA_TYPE"],
                             precision, scale), value))
    return found


def main():
    parser = argparse.ArgumentParser(description="Check a staged DO against the ERP column shapes")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--source", default="eVRP")
    args = parser.parse_args()

    config = load_config(args.config)
    do_write = config.get("do_write") or {}
    header_map, detail_map = do_write.get("header_columns"), do_write.get("detail_columns")
    if not header_map or not detail_map:
        raise SystemExit("do_write.header_columns / detail_columns are empty — fill the mapping first")

    payload = staged_payload(config["database"], args.source, args.receipt_id)
    if payload is None:
        raise SystemExit("ไม่พบใบที่ staged ไว้สำหรับ %s" % receipt_key(args.source, args.receipt_id))

    connector = SQLServerConnector(config.get("sqlserver", {}))
    connection = connector.connect()
    try:
        header_shapes = column_shapes(connector, connection, do_write.get("header_table"))
        detail_shapes = column_shapes(connector, connection, do_write.get("detail_table"))
    finally:
        connection.close()
    if not header_shapes:
        raise ContractError("could not read the column definitions for the header table")

    start = int(do_write.get("detail_line_start", 1))
    found = [("หัวเอกสาร", item) for item in
             problems(header_map, header_shapes, payload.get("header"), 900000, None,
                      do_write.get("header_table"))]
    for index, line in enumerate(payload.get("details") or []):
        found += [("บรรทัดที่ %d" % (start + index), item) for item in
                  problems(detail_map, detail_shapes, line, 900000, start + index,
                           do_write.get("detail_table"))]

    print("ใบ          :", receipt_key(args.source, args.receipt_id))
    print("หัวเอกสาร   :", len(header_shapes), "คอลัมน์ในตาราง")
    print("รายละเอียด  :", len(detail_shapes), "คอลัมน์ในตาราง")
    if not found:
        print("\nทุกค่าพอดีกับคอลัมน์ — ปัญหาอยู่ที่อื่น")
        return
    print("\nค่าที่ไม่พอดี %d รายการ\n" % len(found))
    for where, (column, reason, value) in found:
        print("  %-14s %-22s %s" % (where, column, reason))
        if value is not None:
            print("  %-14s %-22s ค่า: %s" % ("", "", value))
    raise SystemExit(1)


if __name__ == "__main__":
    main()
