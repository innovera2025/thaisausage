"""Tests for the rehearsal mode and the supervised DO write command.

A fake driver stands in for SQL Server, so nothing here can reach a database.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from thaisausage.contracts import ContractError
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



def inserts(connection):
    """Count only the INSERTs; the writer also asks how many documents share the number."""
    return [entry for entry in connection.executed if entry[0].startswith("INSERT")]

class FakeConnection:
    def __init__(self, documents_sharing_the_number=1):
        self.executed = []
        self.committed = self.rolled_back = self.closed = False
        self.documents_sharing_the_number = documents_sharing_the_number

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, sql, parameters):
                connection.executed.append((sql, parameters))

            def fetchone(self):
                sql = connection.executed[-1][0]
                if "COUNT(*)" in sql:
                    return (connection.documents_sharing_the_number,)
                return (5001,) if "MAX(TransactionNo)" in sql else None
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
        self.assertEqual(len(inserts(self.connection)), 2)  # the statements really ran
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



class AutoTransactionNumberTests(unittest.TestCase):
    """TransactionNo is part of the primary key and is not an identity column."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "auto.sqlite3")
        self.service = IntegrationService(self.database, False, Mock(), Mock())
        payload = dict(PAYLOAD)
        payload.pop("transaction_no")
        self.service.receive_do(payload, "eVRP")

    def connection(self, next_no=5001):
        outer = self

        class Cursor:
            def __init__(self, conn):
                self.conn = conn

            def execute(self, sql, parameters=None):
                self.conn.executed.append((sql, parameters))
                self.sql = sql

            def fetchone(self):
                if "COUNT(*)" in self.sql:
                    return (self.conn.documents_sharing_the_number,)
                return (next_no,) if "MAX(TransactionNo)" in self.sql else None

        class Connection:
            def __init__(self):
                self.executed = []
                self.committed = self.rolled_back = False
                self.documents_sharing_the_number = 1

            def cursor(self):
                return Cursor(self)

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

            def close(self):
                pass

        outer.conn = Connection()
        return outer.conn

    def writer(self, **overrides):
        connection = self.connection()
        return DOWriter({**CONFIG, "transaction_no_source": "auto", **overrides},
                        connect=lambda config: connection)

    def test_number_is_allocated_under_a_lock_inside_the_transaction(self):
        result = self.writer().write({"header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]})
        self.assertEqual(result["transaction_no"], 5001)
        allocate = self.conn.executed[0][0]
        self.assertIn("MAX(TransactionNo)", allocate)
        self.assertIn("UPDLOCK", allocate)
        self.assertIn("HOLDLOCK", allocate)
        self.assertTrue(self.conn.committed)

    def test_allocated_number_is_used_by_header_and_detail(self):
        self.writer().write({"header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]})
        inserts = [params for sql, params in self.conn.executed if sql.startswith("INSERT")]
        self.assertEqual([p[0] for p in inserts], [5001, 5001])

    def test_service_accepts_a_write_without_being_given_a_number(self):
        result = self.service.write_do("DO-1", self.writer(), source="eVRP")
        self.assertEqual(result["state"], "inserted")
        self.assertEqual(result["transaction_no"], 5001)
        with sqlite3.connect(self.database) as db:
            stored = db.execute('SELECT transaction_no FROM do_writes').fetchone()[0]
        self.assertEqual(stored, '5001')

    def test_callback_writes_without_being_handed_a_number(self):
        """An allocating writer must not be skipped for the number it allocates itself."""
        result = self.service.attempt_do_write("DO-1", self.writer(), source="eVRP")
        self.assertEqual(result["state"], "inserted")

    def test_callback_still_skips_when_nobody_can_supply_the_number(self):
        writer = DOWriter(CONFIG, connect=lambda config: self.connection())
        result = self.service.attempt_do_write("DO-1", writer, source="eVRP")
        self.assertEqual((result["state"], result["reason"]), ("skipped", "transaction_no_missing"))

    def test_a_number_another_document_already_uses_is_never_committed(self):
        """On 18-09-26 the ERP application and this writer both took 11504.

        The database cannot object, because RowOrder makes the primary key unique whatever the
        number is. So the writer asks before committing, and gives the document up instead.
        """
        connection = self.connection()
        connection.documents_sharing_the_number = 2
        writer = DOWriter({**CONFIG, "transaction_no_source": "auto"},
                          connect=lambda config: connection)
        with self.assertRaises(ContractError) as caught:
            writer.write({"header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]})
        self.assertIn("2 documents", str(caught.exception))
        self.assertFalse(connection.committed)
        self.assertTrue(connection.rolled_back)

    def test_a_reserved_range_is_counted_separately_from_the_erp_numbers(self):
        writer = self.writer(transaction_no_minimum=900000)
        writer.write({"header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]})
        allocate, parameters = self.conn.executed[0]
        self.assertIn("WHERE TransactionNo >= ?", allocate)
        self.assertEqual(parameters, (899999, 900000))

    def test_without_a_reserved_range_the_whole_table_is_still_used(self):
        self.writer().write({"header": {"do_no": "DO-1"}, "details": [{"item_code": "I-1"}]})
        self.assertNotIn("WHERE", self.conn.executed[0][0])

    def test_mapping_is_still_validated_before_connecting(self):
        def refuse(config):
            raise AssertionError("validation must precede the connection")
        writer = DOWriter({**CONFIG, "transaction_no_source": "auto",
                           "header_columns": {"DoNo": {"source": "payload", "path": "do_no", "required": True}}},
                          connect=refuse)
        with self.assertRaises(Exception):
            writer.write({"header": {}, "details": [{"item_code": "I-1"}]})


if __name__ == "__main__":
    unittest.main()
