"""ERP DO writer for tbl_DOhdr and tbl_Dodtl.

The writer is disabled by default and stays unreachable until an operator sets
do_write.enabled in the reviewed configuration file. Target tables, column names
and the source of every value come from that configuration, so this module never
guesses ERP schema and never builds SQL from an HTTP payload. Values are always
bound as parameters; only reviewed identifiers and the agreed GETDATE() server
timestamp are placed into statement text.
"""

import re
from datetime import date, datetime
from decimal import Decimal

from .connectors import lookup
from .contracts import ContractError, require, text
from .sqlserver import approved_identifier, connection_string


_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BINDABLE = (str, int, float, bool, Decimal, date, datetime)


class DOWriteDisabled(Exception):
    """Raised when a write is attempted while the feature flag is off."""


class DOWriteAmbiguous(Exception):
    """Raised when the outcome after COMMIT is unknown; never retry blindly."""


def _column(name):
    if not isinstance(name, str) or not _COLUMN.fullmatch(name):
        raise ContractError("ERP column name must come from the reviewed configuration")
    return name


def _bindable(column, value):
    if value is None or isinstance(value, _BINDABLE):
        return value
    raise ContractError(column + " value type cannot be bound to SQL")


def build_insert(table, columns, source, transaction_no, line_no=None):
    """Return (sql, parameters) for one reviewed row; no SQL comes from the payload."""
    require(text(table), "do_write target table is not configured")
    require(isinstance(columns, dict) and columns, "do_write column mapping is not configured")
    names, placeholders, parameters = [], [], []
    for column, spec in columns.items():
        _column(column)
        require(isinstance(spec, dict), column + " mapping must be an object")
        kind = spec.get("source")
        if kind == "server_time":
            # Agreed ERP contract: EntryDate uses the SQL Server clock, not ours.
            names.append(column)
            placeholders.append("GETDATE()")
            continue
        if kind == "fixed":
            value = spec.get("value")
        elif kind == "transaction_no":
            value = transaction_no
        elif kind == "line_no":
            require(line_no is not None, column + " line_no source is only valid for detail rows")
            value = line_no
        elif kind == "payload":
            require(text(spec.get("path")), column + " payload mapping requires a path")
            value = lookup(source, spec["path"])
        else:
            raise ContractError(column + " mapping source must be payload, fixed, transaction_no, line_no or server_time")
        if value is None and spec.get("required"):
            raise ContractError(column + " is required by the reviewed mapping")
        names.append(column)
        placeholders.append("?")
        parameters.append(_bindable(column, value))
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (
        approved_identifier(table), ", ".join(names), ", ".join(placeholders))
    return sql, tuple(parameters)


class DOWriter:
    """Transactional Header/Detail writer behind an explicit configuration flag."""

    def __init__(self, config, connect=None):
        self.config = config or {}
        self._connect = connect

    @property
    def enabled(self):
        return self.config.get("enabled") is True

    def _credentials(self):
        """Refuse to write with the read-only source credential."""
        read_names = {"ERP_SQLSERVER_CONNECTION_STRING", "ERP_SQL_USER", "ERP_SQL_PASSWORD"}
        write_names = {self.config.get("connection_string_env"),
                       self.config.get("username_env"), self.config.get("password_env")}
        require(all(text(name) for name in write_names),
                "do_write requires its own connection_string_env, username_env and password_env")
        require(not (read_names & write_names),
                "do_write must not reuse the read-only SQL credential environment variables")

    def connect(self):
        self._credentials()
        if self._connect:
            return self._connect(self.config)
        try:
            import pyodbc
        except ImportError as error:
            raise ContractError("Install pyodbc and Microsoft ODBC Driver 18 before ERP DO writing") from error
        connection = pyodbc.connect(
            connection_string(self.config),
            timeout=int(self.config.get("connect_timeout_seconds", 10)),
            autocommit=False,
        )
        connection.timeout = int(self.config.get("query_timeout_seconds", 30))
        return connection

    def prepare(self, payload, transaction_no):
        """Validate and build every statement before any connection is opened."""
        require(isinstance(payload, dict), "DO payload must be an object")
        require(text(transaction_no), "transaction_no is required")
        header = payload.get("header")
        require(isinstance(header, dict), "DO payload requires a header object")
        details = payload.get("details")
        require(isinstance(details, list) and details, "DO payload requires at least one detail line")
        statements = [build_insert(self.config.get("header_table"),
                                   self.config.get("header_columns"), header, transaction_no)]
        start = int(self.config.get("detail_line_start", 1))
        for index, line in enumerate(details):
            require(isinstance(line, dict), "each DO detail line must be an object")
            statements.append(build_insert(self.config.get("detail_table"),
                                           self.config.get("detail_columns"), line,
                                           transaction_no, line_no=start + index))
        return statements

    def write(self, payload, transaction_no):
        """Insert Header and Details inside one transaction, or roll everything back."""
        if not self.enabled:
            raise DOWriteDisabled("do_write.enabled is false")
        statements = self.prepare(payload, transaction_no)  # Validation precedes connection.
        connection = self.connect()
        commit_started = False
        try:
            cursor = connection.cursor()
            for sql, parameters in statements:
                cursor.execute(sql, parameters)
            commit_started = True
            connection.commit()
        except Exception:
            if commit_started:
                # The rows may already be committed; a human reconciles, we never retry.
                raise DOWriteAmbiguous("commit outcome is unknown")
            try:
                connection.rollback()
            except Exception:
                raise DOWriteAmbiguous("rollback failed after a write error")
            raise
        finally:
            try:
                connection.close()
            except Exception:
                pass  # The transaction already resolved; closing is best effort.
        return {"transaction_no": transaction_no, "header_rows": 1,
                "detail_rows": len(statements) - 1}
