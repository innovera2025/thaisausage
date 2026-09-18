"""Tests for the daily status screen.

It reads a temporary SQLite database; nothing here reaches ERP, eVRP or the network.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from thaisausage.service import IntegrationService
from thaisausage.status import reason_of, rows


class ReadingTests(unittest.TestCase):
    def test_a_missing_table_reads_as_empty_rather_than_crashing(self):
        with sqlite3.connect(":memory:") as db:
            self.assertEqual(rows(db, "SELECT * FROM a_table_this_build_does_not_have"), [])

    def test_the_upstream_error_is_what_an_operator_is_shown(self):
        self.assertEqual(reason_of(json.dumps({"upstream_error": "PICKUP_HUB_NOT_FOUND"})),
                         "PICKUP_HUB_NOT_FOUND")

    def test_a_result_that_is_not_json_still_reports_something(self):
        self.assertEqual(reason_of("connection reset"), "connection reset")

    def test_a_result_without_a_known_reason_key_is_summarised(self):
        self.assertIn("status", reason_of(json.dumps({"status": 502})))


class ScreenTests(unittest.TestCase):
    """Runs the command end to end against a database built through the service itself."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = str(root / "status.sqlite3")
        service = IntegrationService(self.database, False, Mock(), Mock())
        service.receive_do({"receipt_id": "DO-A", "do_no": "DO-A", "header": {"do_no": "DO-A"},
                            "details": [{"item_code": "I-1"}]}, "eVRP")
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO do_writes VALUES ('eVRP:DO-C','eVRP','DO-C','DO-C','11505',"
                       "'h','needs_review','timeout after commit','2026-09-18T11:20:00Z')")
        self.config = root / "config.json"
        self.config.write_text(json.dumps({
            "database": self.database, "dry_run": False, "api_key_env": "STATUS_TEST_KEY",
            "vrp": {"token_env": "STATUS_TEST_TOKEN"}, "erp": {}, "sqlserver": {},
            "do_write": {"enabled": False}}), encoding="utf-8")

    def run_status(self):
        environment = dict(os.environ, STATUS_TEST_KEY="x", STATUS_TEST_TOKEN="y")
        finished = subprocess.run([sys.executable, "-m", "thaisausage.status",
                                   "--config", str(self.config)],
                                  capture_output=True, text=True, env=environment,
                                  cwd=str(Path(__file__).resolve().parents[1]))
        self.assertEqual(finished.returncode, 0, finished.stderr)
        return finished.stdout

    def test_a_staged_document_is_listed_as_not_yet_written(self):
        self.assertIn("DO-A", self.run_status())

    def test_a_state_that_needs_a_person_is_marked(self):
        output = self.run_status()
        self.assertIn("needs_review", output)
        self.assertIn("<<", output)

    def test_the_screen_says_whether_erp_writing_is_automatic(self):
        self.assertIn("ต้องสั่งเองทีละใบ", self.run_status())


if __name__ == "__main__":
    unittest.main()
