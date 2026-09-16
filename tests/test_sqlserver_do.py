"""SQL-level tests for the ERP DO writer.

Every test uses a fake driver. No ODBC driver is loaded and no ERP database is
contacted, so these tests prove statement shape and transaction behaviour only.
"""

import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from thaisausage.contracts import ContractError
from thaisausage.do_writer import DOWriteAmbiguous, DOWriteDisabled, DOWriter, build_insert


HEADER_COLUMNS = {
    "TransactionNo": {"source": "transaction_no"},
    "DoNo": {"source": "payload", "path": "do_no", "required": True},
    "CustName": {"source": "payload", "path": "customer.name"},
    "TotalAmount": {"source": "payload", "path": "total_amount"},
    "Dodate": {"source": "payload", "path": "do_date"},
    "IsAcc": {"source": "fixed", "value": 0},
    "IsAccBy": {"source": "fixed", "value": None},
    "IsAccDate": {"source": "fixed", "value": None},
    "DocuNw": {"source": "fixed", "value": None},
    "EntryDate": {"source": "server_time"},
}

DETAIL_COLUMNS = {
    "TransactionNo": {"source": "transaction_no"},
    "Slno": {"source": "line_no"},
    "Itemcode": {"source": "payload", "path": "item_code", "required": True},
    "Description": {"source": "payload", "path": "description"},
    "Qty": {"source": "payload", "path": "quantity"},
}

CONFIG = {
    "enabled": True,
    "header_table": "dbo.tbl_DOhdr",
    "detail_table": "dbo.tbl_Dodtl",
    "connection_string_env": "TEST_WRITE_CONNECTION",
    "username_env": "TEST_WRITE_USER",
    "password_env": "TEST_WRITE_PASSWORD",
    "header_columns": HEADER_COLUMNS,
    "detail_columns": DETAIL_COLUMNS,
}

PAYLOAD = {
    "do_no": "DO-0001",
    "do_date": "2026-09-16",
    "total_amount": Decimal("1070.50"),
    "customer": {"name": "ลูกค้าทดสอบ"},
    "header": {"do_no": "DO-0001", "do_date": "2026-09-16",
               "total_amount": Decimal("1070.50"), "customer": {"name": "ลูกค้าทดสอบ"}},
    "details": [
        {"item_code": "ITEM-0001", "description": "สินค้าทดสอบ", "quantity": 2},
        {"item_code": "ITEM-0002", "description": "ของแถม", "quantity": 1},
    ],
}


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters):
        self.connection.executed.append((sql, parameters))
        if self.connection.fail_on == len(self.connection.executed):
            raise RuntimeError("driver failure")


class FakeConnection:
    def __init__(self, fail_on=None, fail_commit=False, fail_rollback=False):
        self.executed = []
        self.committed = self.rolled_back = self.closed = False
        self.fail_on, self.fail_commit, self.fail_rollback = fail_on, fail_commit, fail_rollback

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit timeout")
        self.committed = True

    def rollback(self):
        if self.fail_rollback:
            raise RuntimeError("rollback failed")
        self.rolled_back = True

    def close(self):
        self.closed = True


def writer_for(connection, **overrides):
    return DOWriter({**CONFIG, **overrides}, connect=lambda config: connection)


class DOStatementTests(unittest.TestCase):
    def test_header_statement_binds_every_value_and_uses_server_time(self):
        sql, parameters = build_insert("dbo.tbl_DOhdr", HEADER_COLUMNS, PAYLOAD["header"], "TR-1")
        self.assertEqual(
            sql,
            "INSERT INTO dbo.tbl_DOhdr (TransactionNo, DoNo, CustName, TotalAmount, Dodate, "
            "IsAcc, IsAccBy, IsAccDate, DocuNw, EntryDate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())")
        self.assertEqual(parameters,
                         ("TR-1", "DO-0001", "ลูกค้าทดสอบ", Decimal("1070.50"), "2026-09-16", 0, None, None, None))

    def test_statement_never_interpolates_payload_values(self):
        sql, parameters = build_insert("dbo.tbl_DOhdr", HEADER_COLUMNS, PAYLOAD["header"], "TR-1")
        for value in ("DO-0001", "ลูกค้าทดสอบ", "1070.50", "2026-09-16", "TR-1"):
            self.assertNotIn(value, sql)
        self.assertEqual(sql.count("?"), len(parameters))

    def test_detail_lines_share_transaction_and_increment_line_numbers(self):
        writer = writer_for(FakeConnection())
        statements = writer.prepare(PAYLOAD, "TR-9")
        self.assertEqual(len(statements), 3)
        self.assertEqual([statement[1][0] for statement in statements], ["TR-9", "TR-9", "TR-9"])
        self.assertEqual([statement[1][1] for statement in statements[1:]], [1, 2])
        self.assertEqual(statements[1][1][2], "ITEM-0001")

    def test_detail_line_start_is_configurable(self):
        writer = writer_for(FakeConnection(), detail_line_start=0)
        statements = writer.prepare(PAYLOAD, "TR-9")
        self.assertEqual([statement[1][1] for statement in statements[1:]], [0, 1])

    def test_date_and_decimal_values_are_passed_to_the_driver_unchanged(self):
        payload = {"header": {"do_no": "DO-2", "do_date": date(2026, 9, 16),
                              "total_amount": Decimal("10.25"), "customer": {}},
                   "details": [{"item_code": "I-1", "quantity": 1}]}
        writer = writer_for(FakeConnection())
        parameters = writer.prepare(payload, "TR-2")[0][1]
        self.assertEqual(parameters[3], Decimal("10.25"))
        self.assertEqual(parameters[4], date(2026, 9, 16))

    def test_unbindable_value_is_rejected(self):
        payload = {"header": {"do_no": {"nested": "object"}}, "details": [{"item_code": "I-1"}]}
        with self.assertRaises(ContractError):
            writer_for(FakeConnection()).prepare(payload, "TR-3")

    def test_required_column_without_value_is_rejected(self):
        payload = {"header": {"customer": {}}, "details": [{"item_code": "I-1"}]}
        with self.assertRaises(ContractError):
            writer_for(FakeConnection()).prepare(payload, "TR-4")

    def test_unreviewed_identifiers_and_sources_are_rejected(self):
        cases = [
            ("dbo.tbl_DOhdr; DROP TABLE x", HEADER_COLUMNS),
            ("dbo.tbl_DOhdr", {"Do No": {"source": "fixed", "value": 1}}),
            ("dbo.tbl_DOhdr", {"DoNo": {"source": "sql", "value": "GETDATE()"}}),
            ("dbo.tbl_DOhdr", {"DoNo": {"source": "payload"}}),
            ("", HEADER_COLUMNS),
            ("dbo.tbl_DOhdr", {}),
        ]
        for table, columns in cases:
            with self.subTest(table=table), self.assertRaises(ContractError):
                build_insert(table, columns, PAYLOAD["header"], "TR-5")

    def test_payload_cannot_supply_sql_text(self):
        payload = {"header": {"do_no": "DO-1; DELETE FROM dbo.tbl_DOhdr", "customer": {}},
                   "details": [{"item_code": "I-1"}]}
        sql, parameters = writer_for(FakeConnection()).prepare(payload, "TR-6")[0]
        self.assertNotIn("DELETE", sql)
        self.assertIn("DO-1; DELETE FROM dbo.tbl_DOhdr", parameters)


class DOTransactionTests(unittest.TestCase):
    def test_successful_write_commits_once_with_header_and_details(self):
        connection = FakeConnection()
        result = writer_for(connection).write(PAYLOAD, "TR-10")
        self.assertEqual(result, {"transaction_no": "TR-10", "header_rows": 1, "detail_rows": 2})
        self.assertEqual(len(connection.executed), 3)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertTrue(connection.closed)

    def test_header_failure_rolls_back_without_commit(self):
        connection = FakeConnection(fail_on=1)
        with self.assertRaises(RuntimeError):
            writer_for(connection).write(PAYLOAD, "TR-11")
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_detail_failure_rolls_back_the_whole_document(self):
        connection = FakeConnection(fail_on=3)
        with self.assertRaises(RuntimeError):
            writer_for(connection).write(PAYLOAD, "TR-12")
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_failure_during_commit_is_ambiguous_and_never_retried(self):
        connection = FakeConnection(fail_commit=True)
        with self.assertRaises(DOWriteAmbiguous):
            writer_for(connection).write(PAYLOAD, "TR-13")
        self.assertFalse(connection.rolled_back)

    def test_failed_rollback_is_reported_as_ambiguous(self):
        connection = FakeConnection(fail_on=2, fail_rollback=True)
        with self.assertRaises(DOWriteAmbiguous):
            writer_for(connection).write(PAYLOAD, "TR-14")

    def test_disabled_writer_never_opens_a_connection(self):
        def refuse(config):
            raise AssertionError("the writer must not connect while disabled")
        writer = DOWriter({**CONFIG, "enabled": False}, connect=refuse)
        with self.assertRaises(DOWriteDisabled):
            writer.write(PAYLOAD, "TR-15")

    def test_validation_failure_happens_before_any_connection(self):
        def refuse(config):
            raise AssertionError("validation must precede the connection")
        writer = DOWriter({**CONFIG, "header_table": ""}, connect=refuse)
        with self.assertRaises(ContractError):
            writer.write(PAYLOAD, "TR-16")

    def test_write_credential_must_differ_from_the_read_only_credential(self):
        for override in ({"connection_string_env": "ERP_SQLSERVER_CONNECTION_STRING"},
                         {"username_env": "ERP_SQL_USER"},
                         {"password_env": "ERP_SQL_PASSWORD"},
                         {"username_env": ""}):
            with self.subTest(override=override), self.assertRaises(ContractError):
                DOWriter({**CONFIG, **override}).connect()

    def test_real_driver_path_requires_its_own_environment(self):
        # No fake connect: the writer must refuse before touching pyodbc.
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ContractError):
            DOWriter({**CONFIG, "username_env": "ERP_SQL_USER"}).connect()


if __name__ == "__main__":
    unittest.main()
