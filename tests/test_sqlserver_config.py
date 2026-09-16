import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from thaisausage.contracts import ContractError
from thaisausage.sqlserver import (SQLServerConnector, approval_filtered, approved_identifier,
                                   connection_string, reviewed_select)


class SQLServerConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "connection_string_env": "TEST_SQL_CONNECTION",
            "username_env": "TEST_SQL_USER",
            "password_env": "TEST_SQL_PASSWORD",
            "auth_mode": "sql",
            "connect_timeout_seconds": 10,
            "query_timeout_seconds": 30,
        }

    def test_builds_credentials_separately_and_escapes_values(self):
        env = {
            "TEST_SQL_CONNECTION": "DRIVER={ODBC Driver 18 for SQL Server};SERVER=db.example,1433;DATABASE=ERP;Encrypt=yes;TrustServerCertificate=no",
            "TEST_SQL_USER": "report;user", "TEST_SQL_PASSWORD": "p}ass;word",
        }
        with patch.dict(os.environ, env, clear=False):
            value = connection_string(self.config)
        self.assertIn("UID={report;user};PWD={p}}ass;word}", value)
        self.assertNotIn("YOUR_PASSWORD", value)

    def test_rejects_credentials_in_base_string(self):
        env = {"TEST_SQL_CONNECTION": "DRIVER={ODBC Driver 18 for SQL Server};SERVER=db;UID=bad;PWD=bad",
               "TEST_SQL_USER": "user", "TEST_SQL_PASSWORD": "password"}
        with patch.dict(os.environ, env, clear=False), self.assertRaises(ContractError):
            connection_string(self.config)

    def test_integrated_auth_adds_trusted_connection(self):
        with patch.dict(os.environ, {"TEST_SQL_CONNECTION": "DRIVER={ODBC Driver 18 for SQL Server};SERVER=db;DATABASE=ERP"}, clear=False):
            self.assertTrue(connection_string({**self.config, "auth_mode": "integrated"}).endswith("Trusted_Connection=yes"))

    def test_only_reviewed_identifiers_are_allowed(self):
        self.assertEqual(approved_identifier("dbo.SalesOrder"), "dbo.SalesOrder")
        for value in ("dbo.Sales-Order", "dbo.Sales Order", "drop table", "dbo.Sales;DELETE"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                approved_identifier(value)

    def test_select_guard_rejects_mutation(self):
        connector = SQLServerConnector(self.config)
        class Cursor:
            description = [("value",)]
            def execute(self, sql, parameters):
                self.sql = sql
            def fetchall(self):
                return [(1,)]
        class Connection:
            def cursor(self):
                return Cursor()
        self.assertEqual(connector.select_approved(Connection(), "SELECT 1"), [{"value": 1}])
        for sql in ("UPDATE orders SET x=1", "SELECT 1; DELETE FROM orders", "SELECT x INTO #tmp FROM orders", "EXEC dbo.Export"):
            with self.subTest(sql=sql), self.assertRaises(ContractError):
                connector.select_approved(Connection(), sql)

    def test_group_rows_imports_mapping_and_normalizes_pyodbc_values(self):
        connector = SQLServerConnector({
            "order_key": "order_no",
            "field_map": {"order_no": "order_no", "order_date": "order_date",
                          "customer.code": "customer_code", "pickup_hub_code": "hub",
                          "shipping_address": "address"},
            "item_field_map": {"item_code": "item_code", "quantity": "quantity", "unit_price": "price"},
        })
        result = connector._group_rows([{
            "order_no": "SO-1", "order_date": date(2026, 9, 14), "customer_code": "C-1",
            "hub": "H-1", "address": "test", "item_code": "I-1",
            "quantity": Decimal("2.50"), "price": Decimal("10.00"),
        }])
        self.assertEqual(result[0]["order_date"], "2026-09-14")
        self.assertEqual(result[0]["items"][0]["quantity"], 2.5)

    def test_approved_orders_query_must_filter_approved_sales_orders(self):
        for query in ("", "SELECT order_no FROM dbo.v_sales_orders"):
            connector = SQLServerConnector({"approved_orders_query": query})
            connector.connect = Mock()
            with self.subTest(query=query), self.assertRaises(ContractError):
                connector.fetch_approved_orders()
            connector.connect.assert_not_called()  # The guard runs before any connection.

    def test_fetch_approved_orders_uses_configured_query_without_parameters(self):
        connector = SQLServerConnector({"approved_orders_query": "SELECT order_no FROM approved_orders WHERE IsApprSo = 1"})
        connector.connect = Mock()
        connection = connector.connect.return_value
        cursor = connection.cursor.return_value
        cursor.description = [("order_no",)]
        cursor.fetchall.return_value = [("SO-1",)]
        connector._group_rows = Mock(return_value=[{"order_no": "SO-1", "items": []}])
        self.assertEqual(connector.fetch_approved_orders(), [{"order_no": "SO-1", "items": []}])
        cursor.execute.assert_called_once_with("SELECT order_no FROM approved_orders WHERE IsApprSo = 1", ())



class ReviewedQueryGuardTests(unittest.TestCase):
    """Regression tests for the review findings on the SELECT and approval guards."""

    def test_single_statement_only(self):
        for sql in ("SELECT 1 AS IsApprSo; CREATE TABLE dbo.probe (id int)",
                    "SELECT 1 AS IsApprSo; GRANT CONTROL ON DATABASE::ERP TO reader",
                    "SELECT order_no FROM so;",
                    "SELECT order_no FROM so; SELECT 1"):
            with self.subTest(sql=sql), self.assertRaises(ContractError):
                reviewed_select(sql)

    def test_comments_are_refused(self):
        for sql in ("SELECT order_no FROM so -- IsApprSo = 1",
                    "SELECT order_no FROM so /* IsApprSo = 1 */",
                    "SELECT /* hidden */ order_no FROM so"):
            with self.subTest(sql=sql), self.assertRaises(ContractError):
                reviewed_select(sql)

    def test_side_effect_keywords_are_refused(self):
        for sql in ("SELECT order_no INTO dbo.copy FROM so", "UPDATE so SET x=1",
                    "SELECT * FROM so WHERE 1=1 DROP TABLE so", "EXEC dbo.Export",
                    "SELECT * FROM OPENROWSET('x','y','z')", "", "   "):
            with self.subTest(sql=sql), self.assertRaises(ContractError):
                reviewed_select(sql)

    def test_plain_select_is_accepted(self):
        sql = "SELECT h.so_no AS order_no FROM dbo.v_so h WHERE h.IsApprSo = 1"
        self.assertEqual(reviewed_select(sql), sql)

    def test_approval_predicate_must_be_visible_and_equal_one(self):
        for sql in ("SELECT order_no FROM so",
                    "SELECT order_no FROM so WHERE IsApprSo = 0",
                    "SELECT order_no FROM so WHERE IsApprSo <> 1",
                    "SELECT order_no FROM so WHERE IsApprSo = 10",
                    "SELECT order_no FROM so WHERE IsApprSo >= 1",
                    "SELECT order_no FROM so -- WHERE IsApprSo = 1",
                    "SELECT order_no, IsApprSo FROM so WHERE IsApprSo = 0"):
            with self.subTest(sql=sql), self.assertRaises(ContractError):
                approval_filtered(sql)

    def test_approved_query_shapes_that_are_accepted(self):
        for sql in ("SELECT order_no FROM so WHERE IsApprSo = 1",
                    "SELECT order_no FROM so WHERE h.IsApprSo=1",
                    "SELECT order_no FROM so WHERE [IsApprSo] = 1",
                    "SELECT order_no, IsApprSo FROM so WHERE IsApprSo = 1 AND company = 'THAI'"):
            with self.subTest(sql=sql):
                self.assertEqual(approval_filtered(sql), sql)


class DetailCompletenessTests(unittest.TestCase):
    """An SO whose detail lines cannot be identified must never be sent."""

    def connector(self):
        return SQLServerConnector({
            "order_key": "order_no",
            "field_map": {"order_no": "order_no"},
            "item_field_map": {"item_code": "item_code", "quantity": "qty"}})

    def test_missing_item_code_rejects_the_whole_order(self):
        for bad in (None, "", "   "):
            rows = [{"order_no": "SO-1", "item_code": "ITEM-1", "qty": 1},
                    {"order_no": "SO-1", "item_code": bad, "qty": 2}]
            with self.subTest(item_code=repr(bad)):
                order = self.connector()._group_rows(rows)[0]
                self.assertEqual(order["rejected_reason"], "detail_item_code_missing")
                self.assertEqual(len(order["items"]), 1)  # The good line is kept for inspection.

    def test_order_without_any_item_is_rejected(self):
        order = self.connector()._group_rows([{"order_no": "SO-2", "item_code": None, "qty": 1}])[0]
        self.assertEqual(order["rejected_reason"], "detail_item_code_missing")

    def test_complete_order_has_no_rejection_marker(self):
        order = self.connector()._group_rows([{"order_no": "SO-3", "item_code": "ITEM-9", "qty": 4}])[0]
        self.assertNotIn("rejected_reason", order)
        self.assertEqual(order["items"], [{"item_code": "ITEM-9", "quantity": 4}])

if __name__ == "__main__":
    unittest.main()
