import os
import unittest
from unittest.mock import patch

from thaisausage.contracts import ContractError
from thaisausage.sqlserver import SQLServerConnector, approved_identifier, connection_string


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
        for sql in ("UPDATE orders SET x=1", "SELECT 1; DELETE FROM orders", "EXEC dbo.Export"):
            with self.subTest(sql=sql), self.assertRaises(ContractError):
                connector.select_approved(Connection(), sql)


if __name__ == "__main__":
    unittest.main()
