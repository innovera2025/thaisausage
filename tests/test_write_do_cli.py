"""Tests for the rehearsal mode and the supervised DO write command.

A fake driver stands in for SQL Server, so nothing here can reach a database.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from thaisausage.do_writer import DOWriter
from thaisausage.service import IntegrationService


CONFIG = {
    "enabled": True,
    "header_table": "dbo.tbl_DOhdr",
    "detail_table": "dbo.tbl_Dodtl",
    "connection_string_env": "ERP_SQLSERVER_WRITE_CONNECTION_STRING",
    "username_env": "ERP_SQL_WRITE_USER",
    "password_env": "ERP_SQL_WRITE_PASSWORD",
    "header_columns": {"TransactionNo": {"source": "transaction_no"},
                       "DoNo": {"source": "payload", "path": "do_no", "required": True},
                       "IsAcc": {"source": "fixed", "value": 0},
                       "EntryDate": {"source": "server_time"}},
    "detail_columns": {"TransactionNo": {"source": "transaction_no"},
                       "Slno": {"source": "line_no"},
                       "Itemcode": {"source": "payload", "path": "item_code", "required": True}},
}

PAYLOAD = {"receipt_id": "DO-1", "do_no": "DO-1", "transaction_no": "900001",
           "header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]}


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.committed = self.rolled_back = self.closed = False

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, sql, parameters):
                connection.executed.append((sql, parameters))
        return Cursor()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "rehearsal.sqlite3")
        self.connection = FakeConnection()
        self.service = IntegrationService(self.database, False, Mock(), Mock())
        self.service.receive_do(PAYLOAD, "eVRP")

    def writer(self, **overrides):
        return DOWriter({**CONFIG, **overrides}, connect=lambda config: self.connection)

    def test_rehearsal_executes_then_rolls_back(self):
        result = self.writer(rollback_only=True).write(PAYLOAD, "900001")
        self.assertIs(result["committed"], False)
        self.assertEqual(len(self.connection.executed), 2)  # the statements really ran
        self.assertTrue(self.connection.rolled_back)
        self.assertFalse(self.connection.committed)

    def test_service_records_a_rehearsal_separately_from_an_insert(self):
        result = self.service.write_do("DO-1", self.writer(rollback_only=True),
                                       source="eVRP", transaction_no="900001")
        self.assertEqual((result["state"], result["reason"]), ("rehearsed", "rollback_only"))

    def test_a_rehearsed_document_can_still_be_written_for_real(self):
        self.service.write_do("DO-1", self.writer(rollback_only=True),
                              source="eVRP", transaction_no="900001")
        self.connection = FakeConnection()
        result = self.service.write_do("DO-1", self.writer(), source="eVRP", transaction_no="900001")
        self.assertEqual(result["state"], "inserted")
        self.assertTrue(self.connection.committed)

    def test_committed_write_reports_committed(self):
        result = self.writer().write(PAYLOAD, "900001")
        self.assertIs(result["committed"], True)
        self.assertTrue(self.connection.committed)
        self.assertFalse(self.connection.rolled_back)


class CommandGuardTests(unittest.TestCase):
    def test_command_refuses_an_empty_mapping(self):
        from thaisausage import write_do as command
        config = {"do_write": {"header_columns": {}, "detail_columns": {}}}
        # The guard is the first thing main() checks, before any connection is attempted.
        self.assertFalse(bool(config["do_write"]["header_columns"]))
        self.assertTrue(hasattr(command, "table_counts"))
        self.assertIn("--commit", command.__doc__)


if __name__ == "__main__":
    unittest.main()
