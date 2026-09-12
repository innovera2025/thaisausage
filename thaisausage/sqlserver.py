"""SQL Server read-only connector foundation.

The connector deliberately accepts reviewed SQL statements only. It never writes to
the ERP database and does not accept SQL from HTTP request bodies.
"""

import os
import re

from .contracts import ContractError


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


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
        """Execute a pre-reviewed SELECT; reject write-shaped statements."""
        if not isinstance(sql, str) or not re.match(r"^\s*SELECT\b", sql, re.I):
            raise ContractError("Only SELECT statements are allowed")
        if re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|ALTER|DROP|TRUNCATE)\b", sql, re.I):
            raise ContractError("SQL statement contains a forbidden write or side effect")
        if not isinstance(parameters, (tuple, list)):
            raise ContractError("SQL parameters must be a tuple or list")
        cursor = connection.cursor()
        cursor.execute(sql, parameters)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def approved_identifier(value):
    if not isinstance(value, str) or not value or any(not _IDENTIFIER.fullmatch(part) for part in value.split(".")):
        raise ContractError("SQL identifier must come from the reviewed allowlist")
    return value
