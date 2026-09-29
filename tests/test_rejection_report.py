"""Tests for grouping eVRP's refusals into one document.

Built from the shape eVRP actually returned on 29-09-26.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from thaisausage.rejection_report import failures, report, subject


def stored(order_no, code, message):
    return json.dumps({"reason": "upstream_http_422", "upstream_error": json.dumps({
        "success": False, "status": "validation_failed",
        "results": [{"order_no": order_no, "status": "error",
                     "errors": [{"code": code, "message": message}]}]}, ensure_ascii=False)})


POINT = "ไม่พบรหัสจุดส่ง ET-LS-CCO-0097 ใน Master กรุณาสร้างจุดส่งในหลังบ้าน"
CUSTOMER = "Customer CT-MS-BKK-2689 ยังไม่มี Master/จุดส่งที่กำหนดสายส่ง"
ROUTE = "ไม่มีสายส่งในจุดส่งงาน CT-MS-PTE-2286"


class SubjectTests(unittest.TestCase):
    def test_a_delivery_point_code_is_pulled_out(self):
        self.assertEqual(subject(POINT), "ET-LS-CCO-0097")

    def test_a_customer_code_is_pulled_out(self):
        self.assertEqual(subject(CUSTOMER), "CT-MS-BKK-2689")

    def test_a_route_complaint_names_the_point(self):
        self.assertEqual(subject(ROUTE), "CT-MS-PTE-2286")

    def test_a_message_without_a_code_gives_nothing(self):
        self.assertEqual(subject("ระบบขัดข้อง"), "")


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "report.sqlite3")
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE submissions (request_id TEXT PRIMARY KEY, payload_hash TEXT,"
                       " state TEXT, result TEXT, created_at TEXT)")
            db.executemany("INSERT INTO submissions VALUES (?,?,?,?,?)", [
                ("R-1", "h", "needs_review", stored("SO-1", "DELIVERY_POINT_NOT_FOUND", POINT), "2026-09-29T09:41:00Z"),
                ("R-2", "h", "needs_review", stored("SO-2", "CUSTOMER_MASTER_REQUIRED", CUSTOMER), "2026-09-29T09:42:00Z"),
                ("R-3", "h", "needs_review", stored("SO-3", "DELIVERY_ROUTE_NOT_FOUND", ROUTE), "2026-09-29T09:43:00Z"),
                ("R-4", "h", "sent", "{}", "2026-09-29T09:44:00Z"),
            ])

    def test_only_refusals_are_collected(self):
        found = failures(self.database)
        self.assertEqual(sorted(item["order_no"] for item in found), ["SO-1", "SO-2", "SO-3"])

    def test_the_document_groups_by_cause_and_lists_the_codes(self):
        text = report(failures(self.database), sent_count=59)
        self.assertIn("DELIVERY_POINT_NOT_FOUND", text)
        self.assertIn("ET-LS-CCO-0097", text)
        self.assertIn("CT-MS-BKK-2689", text)
        self.assertIn("| SO ที่ส่งสำเร็จ | 59 |", text)

    def test_each_cause_explains_what_to_create(self):
        text = report(failures(self.database), sent_count=0)
        self.assertIn("ต้องสร้าง Customer + จุดส่ง + Route", text)
        self.assertIn("ต้องผูก Route", text)

    def test_a_result_that_is_not_json_is_skipped_rather_than_fatal(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO submissions VALUES ('R-5','h','needs_review','not json','2026-09-29T09:45:00Z')")
        self.assertEqual(len(failures(self.database)), 3)


if __name__ == "__main__":
    unittest.main()
