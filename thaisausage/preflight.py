"""Check our own data and configuration against the eVRP contract before sending.

Read-only: it runs the reviewed approved-SO query, maps and validates every order exactly as
the scheduler would, and reports what would be refused — without contacting eVRP. Output carries
identifiers and counts only, never customer data.

    python3 -m thaisausage.preflight --config config/local.json
    python3 -m thaisausage.preflight --config config/local.json --all-orders

Exit code 0 means every order would pass our contract; 1 means something needs attention.
"""

import argparse
import re
from collections import Counter

from .config import load_config
from .contracts import ContractError, validate_orders
from .sqlserver import SQLServerConnector


PLACEHOLDERS = ("HUBCODE", "XXX", "REPLACE", "YOUR_", "TODO")


def configuration_report(config):
    """Flags and query shape an operator should confirm before a live cycle."""
    sqlserver = config.get("sqlserver", {})
    query = sqlserver.get("approved_orders_query", "")
    top = re.search(r"SELECT\s+TOP\s*\((\d+)\)", query, re.I)
    order_filter = re.search(r"h\.OrderNo\)\)\s*=\s*'([^']*)'", query)
    company = re.search(r"h\.Company\)\)\s*=\s*'([^']*)'", query)
    hub_map = re.findall(r"WHEN '([^']*)' THEN '([^']*)'", query)
    return {
        "dry_run": config.get("dry_run"),
        "sync_enabled": config.get("sync", {}).get("enabled"),
        "do_write_enabled": config.get("do_write", {}).get("enabled"),
        "approval_filter": bool(re.search(r"IsApprSo\s*=\s*1", query, re.I)),
        "row_limit": int(top.group(1)) if top else None,
        "single_order_filter": order_filter.group(1) if order_filter else None,
        "company_filter": company.group(1) if company else None,
        "hub_mapping": hub_map,
    }


def order_problems(order):
    """Return the contract problems of one mapped order, without echoing its content."""
    problems = []
    try:
        validate_orders({"request_id": "PREFLIGHT", "orders": [order]})
    except ContractError as error:
        problems.append(str(error))
    if order.get("rejected_reason"):
        problems.append(order["rejected_reason"])
    hub = str(order.get("pickup_hub_code") or "")
    if any(mark in hub.upper() for mark in PLACEHOLDERS):
        problems.append("pickup_hub_code is still a placeholder")
    if not str(order.get("delivery_point_code") or "").strip() and \
            not str(order.get("shipping_address") or "").strip():
        problems.append("no delivery_point_code and no shipping_address")
    return problems


def reconcile_totals(sqlserver_config, orders):
    """Compare mapped line totals against the ERP header totals.

    A mismatch means a mapping problem on our side — a wrong price column, a missing line or a
    discount the header already applied — and is worth knowing before eVRP ever sees the order.
    Requires sqlserver.totals_query returning order_no plus total_amount / total_actual_amount.
    """
    query = sqlserver_config.get("totals_query")
    if not query:
        return None
    connector = SQLServerConnector(sqlserver_config)
    connection = connector.connect()
    try:
        rows = connector.select_approved(connection, query)
    finally:
        connection.close()
    erp_totals = {str(row.get("order_no") or "").strip(): row for row in rows}
    differences = []
    for order in orders:
        key = str(order.get("order_no") or "").strip()
        row = erp_totals.get(key)
        if not row:
            differences.append((key, "no header total found"))
            continue
        mapped = sum(float(item.get("quantity") or 0) * float(item.get("unit_price") or 0)
                     for item in order.get("items") or [])
        for column in ("total_amount", "total_actual_amount"):
            value = row.get(column)
            if value is None:
                continue
            if abs(float(value) - mapped) <= 0.01:
                break
        else:
            differences.append((key, "lines %.2f vs header %s" % (
                mapped, {c: row.get(c) for c in ("total_amount", "total_actual_amount")})))
    return {"checked": len(orders), "differences": differences}


def inspect(config, all_orders=False):
    sqlserver = dict(config.get("sqlserver", {}))
    if all_orders:
        sqlserver["approved_orders_query"] = re.sub(
            r"AND LTRIM\(RTRIM\(h\.OrderNo\)\)\s*=\s*'[^']*'\s*", "",
            sqlserver.get("approved_orders_query", ""))
    orders = SQLServerConnector(sqlserver).fetch_approved_orders()
    report = {
        "orders": len(orders),
        "lines": sum(len(o.get("items") or []) for o in orders),
        "cod": sum(1 for o in orders if o.get("payment_in_day") == 0),
        "credit": sum(1 for o in orders if isinstance(o.get("payment_in_day"), (int, float))
                      and o["payment_in_day"] > 0),
        "not_cod": sum(1 for o in orders if o.get("payment_in_day") is None),
        "hubs": Counter(o.get("pickup_hub_code") for o in orders),
        "duplicate_order_no": [value for value, count in
                               Counter(o.get("order_no") for o in orders).items() if count > 1],
        "untrimmed_order_no": [o["order_no"] for o in orders
                               if isinstance(o.get("order_no"), str) and o["order_no"] != o["order_no"].strip()],
        "failing": [(o.get("order_no"), problems) for o in orders
                    if (problems := order_problems(o))],
        "evrp_master": {
            "hub_codes": sorted({str(o.get("pickup_hub_code") or "") for o in orders}),
            "customer_codes": sorted({str((o.get("customer") or {}).get("code") or "") for o in orders}),
            "delivery_point_codes": sorted({str(o.get("delivery_point_code") or "") for o in orders}),
        },
        "totals": reconcile_totals(sqlserver, orders),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description="Pre-send check of our own SO data")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--all-orders", action="store_true",
                        help="ignore a single-order test filter in the query")
    args = parser.parse_args()
    config = load_config(args.config)

    print("== configuration")
    for key, value in configuration_report(config).items():
        print("   %-22s %s" % (key, value))

    print("== data")
    report = inspect(config, args.all_orders)
    print("   orders                 %s (%s lines)" % (report["orders"], report["lines"]))
    print("   payment_in_day         COD=%s credit=%s not_cod=%s"
          % (report["cod"], report["credit"], report["not_cod"]))
    print("   pickup_hub_code        %s" % dict(report["hubs"]))
    if report["duplicate_order_no"]:
        print("   duplicate order_no     %s" % report["duplicate_order_no"][:5])
    if report["untrimmed_order_no"]:
        print("   order_no with spaces   %s" % len(report["untrimmed_order_no"]))

    totals = report["totals"]
    print("== erp reconciliation")
    if totals is None:
        print("   skipped: set sqlserver.totals_query to compare line totals with the ERP header")
    elif totals["differences"]:
        print("   %d of %d orders differ from the ERP header total:" % (
            len(totals["differences"]), totals["checked"]))
        for order_no, detail in totals["differences"][:10]:
            print("     %-20s %s" % (order_no, detail))
    else:
        print("   all %d orders match the ERP header total" % totals["checked"])

    print("== needs to exist in the eVRP master")
    for key, values in report["evrp_master"].items():
        print("   %-22s %s" % (key, values if len(values) <= 12 else "%d values" % len(values)))

    print("== contract")
    if report["failing"]:
        print("   %d order(s) would be refused:" % len(report["failing"]))
        for order_no, problems in report["failing"][:20]:
            print("     %-20s %s" % (order_no, "; ".join(problems)))
    else:
        print("   every order passes the contract we enforce")

    blocking = (bool(report["failing"]) or report["orders"] == 0
                or bool(totals and totals["differences"]))
    print("== verdict:", "NOT READY" if blocking else "READY to send")
    raise SystemExit(1 if blocking else 0)


if __name__ == "__main__":
    main()
