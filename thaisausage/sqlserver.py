"""SQL Server read-only connector foundation.

The connector deliberately accepts reviewed SQL statements only. It never writes to
the ERP database and does not accept SQL from HTTP request bodies.
"""

import os
import re
from datetime import date, datetime
from decimal import Decimal

from .contracts import ContractError
from .connectors import mapped


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# Reviewed queries are plain single-statement SELECTs. Comments and statement separators are
# refused outright because this guard matches text and cannot reason about SQL semantics.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|ALTER|DROP|CREATE|TRUNCATE|GRANT|REVOKE|DENY"
    r"|BACKUP|RESTORE|SHUTDOWN|RECONFIGURE|WAITFOR|BULK|OPENROWSET|OPENQUERY|OPENDATASOURCE|INTO)\b",
    re.I)
_APPROVED_PREDICATE = re.compile(
    r"(?:\b[A-Za-z_][A-Za-z0-9_]*\s*\.\s*)?\[?IsApprSo\]?\s*=\s*1(?![0-9.])", re.I)
# The whitespace lives inside the lookahead so `= 1` cannot be reached by backtracking.
_UNSAFE_APPROVAL = re.compile(r"\[?IsApprSo\]?\s*(?:<>|!=|>=|<=|>|<|=(?!\s*1(?![0-9.])))", re.I)


def reviewed_select(sql):
    """Accept one plain SELECT statement; reject separators, comments and side effects."""
    if not isinstance(sql, str) or not sql.strip():
        raise ContractError("SQL must be a reviewed SELECT statement")
    if ";" in sql:
        raise ContractError("SQL must be a single statement without ';'")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ContractError("SQL comments are not allowed in a reviewed statement")
    if not re.match(r"^\s*SELECT\b", sql, re.I):
        raise ContractError("Only SELECT statements are allowed")
    if _FORBIDDEN.search(sql):
        raise ContractError("SQL statement contains a forbidden write or side effect")
    return sql


def approval_filtered(sql):
    """Require a visible `IsApprSo = 1` predicate and refuse any other comparison of it.

    This is a conservative text contract, not a SQL parser: a query whose approval rule cannot be
    read here is rejected rather than trusted.
    """
    reviewed_select(sql)
    if _UNSAFE_APPROVAL.search(sql):
        raise ContractError("approved_orders_query must compare IsApprSo only with 1")
    if not _APPROVED_PREDICATE.search(sql):
        raise ContractError("approved_orders_query must filter approved SOs with IsApprSo = 1")
    return sql


def connection_string(config):
    """Build an ODBC string while keeping credentials out of config files/logs."""
    env_name = config.get("connection_string_env", "ERP_SQLSERVER_CONNECTION_STRING")
    base = os.environ.get(env_name, "").strip()
    if not base:
        raise ContractError("Set the SQL Server connection string environment variable")
    auth_mode = config.get("auth_mode", "sql")
    if auth_mode == "sql":
        user = os.environ.get(config.get("username_env", "ERP_SQL_USER"), "")
        password = os.environ.get(config.get("password_env", "ERP_SQL_PASSWORD"), "")
        if not user or not password:
            raise ContractError("Set the SQL Server username and password environment variables")
        # The base string is intentionally checked so credentials cannot be ambiguous.
        if re.search(r"(?:^|;)\s*(?:UID|PWD|User\s*ID|Password)\s*=", base, re.I):
            raise ContractError("Do not put UID/PWD in the base string; use the configured secret environment variables")
        return base.rstrip(";") + ";UID=" + _escape_value(user) + ";PWD=" + _escape_value(password)
    if auth_mode == "integrated":
        return base.rstrip(";") + ";Trusted_Connection=yes"
    raise ContractError("sqlserver.auth_mode must be sql or integrated")


def _escape_value(value):
    """ODBC brace escape for values containing delimiters or closing braces."""
    return "{" + value.replace("}", "}}") + "}"


class SQLServerConnector:
    """Lazy pyodbc connector for SELECT-only discovery and approved reads."""

    def __init__(self, config):
        self.config = config

    def _driver(self):
        try:
            import pyodbc
        except ImportError as error:
            raise ContractError("Install pyodbc and Microsoft ODBC Driver 18 before SQL Server testing") from error
        return pyodbc

    def connect(self):
        pyodbc = self._driver()
        connection = pyodbc.connect(
            connection_string(self.config),
            timeout=int(self.config.get("connect_timeout_seconds", 10)),
            autocommit=True,
        )
        connection.timeout = int(self.config.get("query_timeout_seconds", 30))
        return connection

    def check_read_only_connection(self):
        """Run metadata-only checks; never reads ERP business tables."""
        connection = self.connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT DB_NAME() AS database_name, @@VERSION AS sql_version")
            row = cursor.fetchone()
            return {"database_name": row.database_name, "sql_version": row.sql_version}
        finally:
            connection.close()

    def select_approved(self, connection, sql, parameters=()):
        """Execute a pre-reviewed SELECT; reject anything that is not one plain query."""
        reviewed_select(sql)
        if not isinstance(parameters, (tuple, list)):
            raise ContractError("SQL parameters must be a tuple or list")
        cursor = connection.cursor()
        cursor.execute(sql, parameters)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def fetch_orders(self, order_no=None):
        """Fetch approved SO rows; query text must be supplied by the ERP/DBA contract."""
        sql = self.config.get("orders_query")
        if not sql:
            raise ContractError("Configure sqlserver.orders_query after schema discovery")
        connection = self.connect()
        try:
            parameters = (order_no,) if "?" in sql and order_no else ()
            rows = self.select_approved(connection, sql, parameters)
        finally:
            connection.close()
        return self._group_rows(rows)

    def fetch_approved_orders(self):
        """Fetch the reviewed, approval-filtered SO query for scheduled sync."""
        sql = self.config.get("approved_orders_query")
        if not sql:
            raise ContractError("Configure sqlserver.approved_orders_query after schema discovery")
        approval_filtered(sql)
        connection = self.connect()
        try:
            rows = self.select_approved(connection, sql)
        finally:
            connection.close()
        return self._group_rows(rows)

    def _group_rows(self, rows):
        order_key = self.config.get("order_key", "order_no")
        if not rows:
            return []
        groups = {}
        for row in rows:
            key = row.get(order_key)
            if not key:
                raise ContractError("SQL result is missing the configured order_key")
            groups.setdefault(key, []).append(row)
        result = []
        for key, group in groups.items():
            order = self._normalize(mapped(group[0], self.config.get("field_map", {})))
            items, incomplete = [], False
            for row in group:
                item = self._normalize(mapped(row, self.config.get("item_field_map", {})))
                code = item.get("item_code")
                # A detail line we cannot identify makes the whole SO unsafe to send.
                if not isinstance(code, str) or not code.strip():
                    incomplete = True
                    continue
                items.append(item)
            order["items"] = items
            if incomplete or not items:
                order["rejected_reason"] = "detail_item_code_missing"
            result.append(order)
        return result

    def _normalize(self, value):
        """Convert common pyodbc values into JSON-compatible contract values."""
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize(item) for item in value]
        return value


def approved_identifier(value):
    if not isinstance(value, str) or not value or any(not _IDENTIFIER.fullmatch(part) for part in value.split(".")):
        raise ContractError("SQL identifier must come from the reviewed allowlist")
    return value
