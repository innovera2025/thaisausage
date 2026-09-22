"""Tests for revising a delivery order ERP already holds.

A fake connection stands in for SQL Server, so nothing here can reach a database.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from thaisausage.contracts import ContractError
from thaisausage.do_writer import DOWriter, build_update
from thaisausage.service import Conflict, IntegrationService


CONFIG = {
    "enabled": True,
    "update_enabled": True,
    "header_table": "dbo.tbl_DOhdr",
    "detail_table": "dbo.tbl_Dodtl",
    "connection_string_env": "ERP_SQLSERVER_WRITE_CONNECTION_STRING",
    "username_env": "ERP_SQL_WRITE_USER",
    "password_env": "ERP_SQL_WRITE_PASSWORD",
    "header_columns": {"TransactionNo": {"source": "transaction_no"},
                       "DoNo": {"source": "payload", "path": "do_no", "required": True},
                       "Driver": {"source": "payload", "path": "driver"},
                       "IsAcc": {"source": "fixed", "value": 0},
                       "EntryDate": {"source": "server_time"}},
    "detail_columns": {"TransactionNo": {"source": "transaction_no"},
                       "Slno": {"source": "line_no"},
                       "Itemcode": {"source": "payload", "path": "item_code", "required": True}},
}

REVISION = {"receipt_id": "DO-1-R2", "do_no": "DO-1",
            "header": {"do_no": "DO-1", "driver": "สมชาย"},
            "details": [{"item_code": "I-1"}, {"item_code": "I-2"}]}


class FakeConnection:
    def __init__(self, document=(0, 0, 0), documents=1):
        self.executed = []
        self.committed = self.rolled_back = self.closed = False
        self.document, self.documents = document, documents

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, sql, parameters=None):
                connection.executed.append((sql, parameters))

            def fetchall(self):
                return [connection.document] * connection.documents

            def fetchone(self):
                return (1,)
        return Cursor()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def statements(self, verb):
        return [entry for entry in self.executed if entry[0].startswith(verb)]


class StatementTests(unittest.TestCase):
    def test_the_key_is_the_condition_and_never_a_value(self):
        sql, parameters = build_update("dbo.tbl_DOhdr", CONFIG["header_columns"],
                                       {"do_no": "DO-1", "driver": "สมชาย"}, 900001)
        self.assertNotIn("TransactionNo =", sql.split("WHERE")[0])
        self.assertTrue(sql.endswith("WHERE TransactionNo = ?"))
        self.assertEqual(parameters[-1], 900001)

    def test_the_creation_timestamp_is_left_alone(self):
        sql, _ = build_update("dbo.tbl_DOhdr", CONFIG["header_columns"], {"do_no": "DO-1"}, 900001)
        self.assertNotIn("EntryDate", sql)

    def test_a_required_column_is_still_required(self):
        with self.assertRaises(ContractError):
            build_update("dbo.tbl_DOhdr", CONFIG["header_columns"], {}, 900001)


class WriterTests(unittest.TestCase):
    def writer(self, connection, **overrides):
        return DOWriter({**CONFIG, **overrides}, connect=lambda config: connection)

    def test_lines_are_replaced_inside_the_same_transaction_as_the_rewrite(self):
        connection = FakeConnection()
        result = self.writer(connection).update(REVISION, 900001)
        self.assertEqual(len(connection.statements("UPDATE")), 1)
        self.assertEqual(len(connection.statements("DELETE")), 1)
        self.assertEqual(len(connection.statements("INSERT")), 2)
        self.assertTrue(connection.committed)
        self.assertEqual(result["detail_rows"], 2)

    def test_an_approved_document_is_refused(self):
        connection = FakeConnection(document=(1, 0, 0))
        with self.assertRaises(ContractError) as caught:
            self.writer(connection).update(REVISION, 900001)
        self.assertIn("approved", str(caught.exception))
        self.assertEqual(connection.statements("DELETE"), [])
        self.assertFalse(connection.committed)

    def test_a_closed_or_accounted_document_is_refused(self):
        for document in ((0, 1, 0), (0, 0, 1)):
            connection = FakeConnection(document=document)
            with self.assertRaises(ContractError):
                self.writer(connection).update(REVISION, 900001)

    def test_a_number_shared_by_two_documents_is_refused(self):
        connection = FakeConnection(documents=2)
        with self.assertRaises(ContractError) as caught:
            self.writer(connection).update(REVISION, 900001)
        self.assertIn("2 documents", str(caught.exception))

    def test_a_missing_document_is_refused(self):
        connection = FakeConnection(documents=0)
        with self.assertRaises(ContractError):
            self.writer(connection).update(REVISION, 900001)

    def test_updating_needs_its_own_flag_even_when_writing_is_on(self):
        connection = FakeConnection()
        from thaisausage.do_writer import DOWriteDisabled
        with self.assertRaises(DOWriteDisabled):
            self.writer(connection, update_enabled=False).update(REVISION, 900001)
        self.assertEqual(connection.executed, [])

    def test_a_rehearsal_changes_nothing(self):
        connection = FakeConnection()
        result = self.writer(connection, rollback_only=True).update(REVISION, 900001)
        self.assertIs(result["committed"], False)
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "update.sqlite3")
        self.service = IntegrationService(self.database, False, Mock(), Mock())
        self.service.receive_do(REVISION, "eVRP")
        self.connection = FakeConnection()

    def written(self, transaction_no="900001", state="inserted"):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO do_writes VALUES ('eVRP:DO-1','eVRP','DO-1','DO-1',?,"
                       "'hash',?,NULL,'2026-09-22T00:00:00Z')", (transaction_no, state))

    def writer(self, **overrides):
        return DOWriter({**CONFIG, **overrides}, connect=lambda config: self.connection)

    def test_the_erp_number_comes_from_our_record_not_the_payload(self):
        self.written()
        payload = dict(REVISION, transaction_no="123456")  # a number the caller made up
        self.service.receive_do(dict(payload, receipt_id="DO-1-R3"), "eVRP")
        result = self.service.update_do("DO-1-R3", self.writer())
        self.assertEqual(result["transaction_no"], "900001")

    def test_a_do_that_was_never_written_is_refused(self):
        result = self.service.update_do("DO-1-R2", self.writer())
        self.assertEqual((result["state"], result["reason"]), ("rejected", "do_no_not_written"))
        self.assertEqual(self.connection.executed, [])

    def test_a_do_whose_write_failed_is_refused(self):
        self.written(state="rejected")
        result = self.service.update_do("DO-1-R2", self.writer())
        self.assertEqual(result["reason"], "do_no_not_written")

    def test_an_applied_revision_is_recorded_and_replayed_not_reapplied(self):
        self.written()
        first = self.service.update_do("DO-1-R2", self.writer())
        self.assertEqual(first["state"], "updated")
        self.connection = FakeConnection()
        second = self.service.update_do("DO-1-R2", self.writer())
        self.assertTrue(second["replayed"])
        self.assertEqual(self.connection.executed, [])

    def test_the_same_revision_id_with_different_content_conflicts(self):
        self.written()
        self.service.update_do("DO-1-R2", self.writer())
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE do_receipts SET payload_hash='different' WHERE receipt_key='eVRP:DO-1-R2'")
        with self.assertRaises(Conflict):
            self.service.update_do("DO-1-R2", self.writer())

    def test_a_revision_that_was_never_staged_returns_nothing(self):
        self.written()
        self.assertIsNone(self.service.update_do("DO-1-R9", self.writer()))

    def test_a_refusal_is_reported_rather_than_raised_to_the_caller(self):
        self.written()
        self.connection = FakeConnection(document=(1, 0, 0))
        result = self.service.attempt_do_update("DO-1-R2", self.writer())
        self.assertEqual(result["state"], "rejected")
        self.assertIn("approved", result["reason"])


if __name__ == "__main__":
    unittest.main()
