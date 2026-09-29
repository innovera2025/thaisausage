"""Turn eVRP's rejections into a document their team can act on.

Every refusal is stored with eVRP's own message, so the list of what is missing already exists —
it just has to be grouped. This writes one Markdown report: how many orders failed, why, and the
exact codes to create, so nobody has to read a thousand log lines to find them.

    python -m thaisausage.rejection_report --config config/local.json --out /app/data/report.md

Reads the local database only. Nothing is sent and nothing is changed.
"""

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from .config import load_config

# eVRP's codes, in the order a person would fix them: the customer first, then its delivery point,
# then the route on that point.
EXPLANATION = {
    "CUSTOMER_MASTER_REQUIRED": "ยังไม่มีลูกค้ารายนี้ใน Master — ต้องสร้าง Customer + จุดส่ง + Route",
    "DELIVERY_POINT_NOT_FOUND": "มีลูกค้าแล้ว แต่ไม่มีจุดส่งที่ใช้รหัสนี้ — ต้องสร้างจุดส่ง (poi_code) + Route",
    "DELIVERY_ROUTE_NOT_FOUND": "มีจุดส่งแล้ว แต่ยังไม่ได้กำหนดสายส่ง — ต้องผูก Route ให้จุดส่งนี้",
    "PICKUP_HUB_NOT_FOUND": "ไม่มีรหัส hub นี้ใน Master Hub ของบริษัทที่ X-Token ชี้ไป",
    "DEFAULT_PICKUP_NOT_CONFIGURED": "hub นี้ยังไม่มี Default Pickup POI",
}

CODE_IN_MESSAGE = ("ไม่พบรหัสจุดส่ง ", "จุดส่งงาน ", "Customer ")


def failures(database):
    """Every stored refusal, flattened to (order_no, code, message)."""
    found = []
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT request_id, result, created_at FROM submissions "
                          "WHERE state IN ('failed','needs_review') ORDER BY created_at").fetchall()
    for request_id, result, created_at in rows:
        try:
            stored = json.loads(result)
            detail = json.loads(stored.get("upstream_error") or "{}")
        except (TypeError, ValueError):
            continue
        for order in detail.get("results") or []:
            for error in order.get("errors") or []:
                found.append({"order_no": order.get("order_no") or "?",
                              "code": error.get("code") or "?",
                              "message": (error.get("message") or "").strip(),
                              "at": created_at})
    return found


def subject(message):
    """The code eVRP is complaining about, pulled out of its own sentence."""
    for prefix in CODE_IN_MESSAGE:
        if prefix in message:
            tail = message.split(prefix, 1)[1]
            return tail.split()[0].strip(" ,.")
    return ""


def report(found, sent_count):
    by_code = defaultdict(list)
    for failure in found:
        by_code[failure["code"]].append(failure)
    lines = ["# รายการที่ eVRP ปฏิเสธ — ขอให้ตั้ง Master",
             "",
             "วันที่ออกรายงาน: %s" % datetime.now(timezone.utc).astimezone().strftime("%d %B %Y %H:%M"),
             "ผู้ส่ง: ระบบเชื่อมต่อ ERP ↔ eVRP ของ หจก. ไทยซอสเทรดดิ้ง",
             "",
             "## สรุป",
             "",
             "| | จำนวน |",
             "|---|---:|",
             "| SO ที่ส่งสำเร็จ | %d |" % sent_count,
             "| SO ที่ถูกปฏิเสธ | %d |" % len({f["order_no"] for f in found}),
             ""]
    lines += ["| สาเหตุ | จำนวน SO | ต้องทำอะไร |", "|---|---:|---|"]
    for code, items in sorted(by_code.items(), key=lambda pair: -len(pair[1])):
        lines.append("| `%s` | %d | %s |"
                     % (code, len({item["order_no"] for item in items}),
                        EXPLANATION.get(code, "ดูข้อความจาก eVRP ด้านล่าง")))
    lines.append("")

    for code, items in sorted(by_code.items(), key=lambda pair: -len(pair[1])):
        codes = sorted({subject(item["message"]) for item in items if subject(item["message"])})
        lines += ["## %s" % code, "",
                  EXPLANATION.get(code, ""), "",
                  "ตัวอย่างข้อความจาก eVRP:", "",
                  "> %s" % items[0]["message"], ""]
        if codes:
            lines += ["รหัสที่ต้องสร้าง %d รายการ:" % len(codes), "", "```"]
            lines += codes
            lines += ["```", ""]
        orders = sorted({item["order_no"] for item in items})
        lines += ["SO ที่ได้รับผลกระทบ %d ใบ:" % len(orders), "",
                  "```", ", ".join(orders), "```", ""]

    lines += ["## หมายเหตุ", "",
              "- ระบบเราส่ง `delivery_point_code` เป็น **รหัสลูกค้า** ดังนั้น `poi_code` ของจุดส่ง"
              "ขอให้ใช้ค่าเดียวกับรหัสลูกค้า",
              "- จุดส่งต้องมี Route (`rt_id`) มิฉะนั้นจะได้ `DELIVERY_ROUTE_NOT_FOUND`",
              "- เมื่อตั้งเสร็จ ระบบเราจะส่งใหม่ให้เองอัตโนมัติ ไม่ต้องแจ้งกลับ",
              ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Group eVRP's refusals into one document")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--out", default="/app/data/evrp-rejections.md")
    args = parser.parse_args()

    config = load_config(args.config)
    with sqlite3.connect(config["database"]) as db:
        sent = db.execute("SELECT COUNT(*) FROM submissions WHERE state='sent'").fetchone()[0]
    found = failures(config["database"])
    if not found:
        raise SystemExit("ไม่มีรายการที่ถูกปฏิเสธ")
    text = report(found, sent)
    with open(args.out, "w", encoding="utf-8") as stream:
        stream.write(text)
    print("เขียนแล้ว:", args.out)
    print(text[:text.index("## CUSTOMER") if "## CUSTOMER" in text else 1200])


if __name__ == "__main__":
    main()
