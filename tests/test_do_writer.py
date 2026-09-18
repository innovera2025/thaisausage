"""Service-level tests for staged DO writes.

These tests use a fake SQL driver. They prove state handling, duplicate protection
and that no ERP write happens in dry-run or while the feature flag is disabled.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from thaisausage.contracts import ContractError
from thaisausage.do_writer import DOWriter
from thaisausage.service import Conflict, IntegrationService


CONFIG = {
    "enabled": True,
    "header_table": "dbo.tbl_DOhdr",
    "detail_table": "dbo.tbl_Dodtl",
    "connection_string_env": "ERP_SQLSERVER_WRITE_CONNECTION_STRING",
    "username_env": "ERP_SQL_WRITE_USER",
    "password_env": "ERP_SQL_WRITE_PASSWORD",
    "header_columns": {
        "TransactionNo": {"source": "transaction_no"},
        "DoNo": {"source": "payload", "path": "do_no", "required": True},
        "IsAcc": {"source": "fixed", "value": 0},
        "EntryDate": {"source": "server_time"},
    },
    "detail_columns": {
        "TransactionNo": {"source": "transaction_no"},
        "Slno": {"source": "line_no"},
        "Itemcode": {"source": "payload", "path": "item_code", "required": True},
    },
}


def staged_payload(receipt_id="DO-R-1", do_no="DO-0001", transaction_no="TR-0001"):
    return {"receipt_id": receipt_id, "do_no": do_no, "transaction_no": transaction_no,
            "header": {"do_no": do_no}, "details": [{"item_code": "ITEM-0001"},
                                                    {"item_code": "ITEM-0002"}]}



def inserts(connection):
    """Count only the INSERTs; the writer also asks how many documents share the number."""
    return [entry for entry in connection.executed if entry[0].startswith("INSERT")]

class FakeConnection:
    def __init__(self, fail_commit=False):
        self.executed = []
        self.committed = self.rolled_back = self.closed = False
        self.fail_commit = fail_commit

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, sql, parameters):
                connection.executed.append((sql, parameters))

            def fetchone(self):
                sql = connection.executed[-1][0]
                if "COUNT(*)" in sql:
                    return (1,)  # our own header row, and nobody else's
                return (5001,) if "MAX(TransactionNo)" in sql else None
        return Cursor()

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit timeout")
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class DOWriteServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "test.sqlite3")
        self.connection = FakeConnection()
        self.service = IntegrationService(self.database, False, Mock(), Mock())

    def writer(self, **overrides):
        return DOWriter({**CONFIG, **overrides}, connect=lambda config: self.connection)

    def stage(self, payload=None):
        payload = payload or staged_payload()
        self.service.receive_do(payload)
        return payload

    def write_states(self):
        with sqlite3.connect(self.database) as db:
            return db.execute("SELECT receipt_id,do_no,transaction_no,state,reason FROM do_writes").fetchall()

    def test_staging_alone_never_writes_to_erp(self):
        result = self.service.receive_do(staged_payload())
        self.assertEqual(result["state"], "staged")
        self.assertIs(result["erp_write"], False)
        self.assertEqual(self.write_states(), [])
        self.assertEqual(self.connection.executed, [])

    def test_live_write_inserts_header_and_details_in_one_transaction(self):
        self.stage()
        result = self.service.write_do("DO-R-1", self.writer())
        self.assertEqual(result["state"], "inserted")
        self.assertEqual(result["header_rows"], 1)
        self.assertEqual(result["detail_rows"], 2)
        self.assertEqual(len(inserts(self.connection)), 3)
        self.assertTrue(self.connection.committed)
        self.assertEqual(self.write_states(), [("DO-R-1", "DO-0001", "TR-0001", "inserted", None)])

    def test_dry_run_previews_without_executing_sql(self):
        service = IntegrationService(self.database, True, Mock(), Mock())
        service.receive_do(staged_payload())
        result = service.write_do("DO-R-1", self.writer())
        self.assertEqual(result["state"], "preview")
        self.assertEqual(result["statements"], 3)
        self.assertEqual(self.connection.executed, [])
        self.assertFalse(self.connection.committed)

    def test_disabled_flag_blocks_the_write(self):
        self.stage()
        result = self.service.write_do("DO-R-1", self.writer(enabled=False))
        self.assertEqual(result["state"], "disabled")
        self.assertEqual(self.connection.executed, [])

    def test_replay_of_the_same_receipt_does_not_write_twice(self):
        self.stage()
        self.service.write_do("DO-R-1", self.writer())
        replay = self.service.write_do("DO-R-1", self.writer())
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["state"], "inserted")
        self.assertEqual(len(inserts(self.connection)), 3)

    def test_changed_staged_payload_conflicts_with_a_recorded_write(self):
        self.stage()
        self.service.write_do("DO-R-1", self.writer())
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE do_receipts SET payload_hash='changed' WHERE receipt_id=?", ("DO-R-1",))
        with self.assertRaises(Conflict):
            self.service.write_do("DO-R-1", self.writer())

    def test_duplicate_do_no_under_another_receipt_is_rejected(self):
        self.stage()
        self.service.write_do("DO-R-1", self.writer())
        self.stage(staged_payload(receipt_id="DO-R-2", do_no="DO-0001", transaction_no="TR-0002"))
        with self.assertRaises(Conflict):
            self.service.write_do("DO-R-2", self.writer())
        self.assertEqual(len(inserts(self.connection)), 3)

    def test_duplicate_transaction_no_under_another_receipt_is_rejected(self):
        self.stage()
        self.service.write_do("DO-R-1", self.writer())
        self.stage(staged_payload(receipt_id="DO-R-3", do_no="DO-0003", transaction_no="TR-0001"))
        with self.assertRaises(Conflict):
            self.service.write_do("DO-R-3", self.writer())

    def test_commit_timeout_becomes_needs_review_and_is_not_retried(self):
        self.stage()
        self.connection = FakeConnection(fail_commit=True)
        result = self.service.write_do("DO-R-1", self.writer())
        self.assertEqual(result["state"], "needs_review")
        self.assertFalse(self.connection.rolled_back)
        executed = len(inserts(self.connection))
        replay = self.service.write_do("DO-R-1", self.writer())
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["state"], "needs_review")
        self.assertEqual(len(inserts(self.connection)), executed)

    def test_rejected_mapping_can_be_retried_after_the_cause_is_fixed(self):
        self.stage()
        broken = self.service.write_do("DO-R-1", self.writer(header_table=""))
        self.assertEqual(broken["state"], "rejected")
        self.assertEqual(self.connection.executed, [])
        fixed = self.service.write_do("DO-R-1", self.writer())
        self.assertEqual(fixed["state"], "inserted")

    def test_missing_transaction_no_stops_before_any_claim(self):
        self.service.receive_do({"receipt_id": "DO-R-9", "do_no": "DO-9", "header": {"do_no": "DO-9"},
                                 "details": [{"item_code": "I-1"}]})
        with self.assertRaises(ContractError):
            self.service.write_do("DO-R-9", self.writer())
        self.assertEqual(self.write_states(), [])

    def test_unknown_receipt_returns_none(self):
        self.assertIsNone(self.service.write_do("DO-MISSING", self.writer()))

    def test_recorded_reason_holds_no_payload_values(self):
        self.stage()
        result = self.service.write_do("DO-R-1", self.writer(detail_columns={
            "TransactionNo": {"source": "transaction_no"},
            "PartNoCust": {"source": "payload", "path": "missing_field", "required": True}}))
        self.assertEqual(result["state"], "rejected")
        self.assertNotIn("ITEM-0001", json.dumps(self.write_states(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()


class DoWriteSourceScopeTests(unittest.TestCase):
    """A staged DO is addressed by source plus receipt id, never by receipt id alone."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "scope.sqlite3")
        self.connection = FakeConnection()
        self.service = IntegrationService(self.database, False, Mock(), Mock())
        self.writer = DOWriter(CONFIG, connect=lambda config: self.connection)

    def test_write_targets_the_receipt_of_the_requested_source(self):
        self.service.receive_do(staged_payload(), "eVRP")
        self.assertIsNone(self.service.write_do("DO-R-1", self.writer, source="erp"))
        self.assertEqual(self.connection.executed, [])
        result = self.service.write_do("DO-R-1", self.writer, source="eVRP")
        self.assertEqual(result["state"], "inserted")
        self.assertEqual(result["receipt_key"], "eVRP:DO-R-1")
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT receipt_key,source FROM do_writes").fetchall(),
                             [("eVRP:DO-R-1", "eVRP")])

    def test_same_receipt_id_from_two_sources_writes_twice_without_conflict(self):
        self.service.receive_do(staged_payload(transaction_no="TR-A"), "erp")
        self.service.receive_do(staged_payload(do_no="DO-0002", transaction_no="TR-B"), "eVRP")
        first = self.service.write_do("DO-R-1", self.writer, source="erp")
        second = self.service.write_do("DO-R-1", self.writer, source="eVRP")
        self.assertEqual([first["state"], second["state"]], ["inserted", "inserted"])
        self.assertEqual(len(inserts(self.connection)), 6)
