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
            if value is None and "default" in spec:
                # A column ERP needs filled but eVRP has no opinion about. Sending it stays
                # possible; leaving it out gets the value the ERP team asked for.
                value = spec["default"]
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


def build_update(table, columns, source, transaction_no):
    """Return (sql, parameters) that rewrites one existing header row.

    TransactionNo identifies the row, so it is the condition rather than a value, and the creation
    timestamp is left as it was. Everything else the mapping owns is rewritten, so the row ends up
    saying exactly what the payload says.
    """
    require(text(table), "do_write target table is not configured")
    require(isinstance(columns, dict) and columns, "do_write column mapping is not configured")
    assignments, parameters = [], []
    for column, spec in columns.items():
        _column(column)
        require(isinstance(spec, dict), column + " mapping must be an object")
        kind = spec.get("source")
        if kind in ("transaction_no", "server_time", "line_no"):
            continue
        if kind == "fixed":
            value = spec.get("value")
        elif kind == "payload":
            require(text(spec.get("path")), column + " payload mapping requires a path")
            value = lookup(source, spec["path"])
            if value is None and "default" in spec:
                value = spec["default"]
        else:
            raise ContractError(column + " mapping source must be payload, fixed, transaction_no, line_no or server_time")
        if value is None and spec.get("required"):
            raise ContractError(column + " is required by the reviewed mapping")
        assignments.append(column + " = ?")
        parameters.append(_bindable(column, value))
    require(assignments, "the reviewed mapping leaves nothing to update")
    sql = "UPDATE %s SET %s WHERE TransactionNo = ?" % (
        approved_identifier(table), ", ".join(assignments))
    return sql, tuple(parameters) + (transaction_no,)


class DOWriter:
    """Transactional Header/Detail writer behind an explicit configuration flag."""

    def __init__(self, config, connect=None):
        self.config = config or {}
        self._connect = connect

    @property
    def enabled(self):
        return self.config.get("enabled") is True

    @property
    def auto_transaction_no(self):
        """True when the writer allocates TransactionNo itself instead of being given one."""
        return self.config.get("transaction_no_source") == "auto"

    @property
    def reserved_from(self):
        """The first number of the range the ERP team set aside for us, if they set one aside."""
        minimum = self.config.get("transaction_no_minimum")
        return int(minimum) if minimum else None

    def next_transaction_no(self, connection):
        """Allocate the next TransactionNo inside the caller's transaction.

        TransactionNo is part of the primary key and is not an identity column, so the number has
        to be chosen. UPDLOCK/HOLDLOCK stops a second writer taking the same number — but only a
        writer that takes the same lock, and the ERP application reads MAX without one. On
        18-09-26 that produced two documents numbered 11504. So the real protection is
        transaction_no_minimum: a range the ERP application never reaches, counted separately.
        """
        table = approved_identifier(self.config.get("header_table") or "")
        cursor = connection.cursor()
        floor = self.reserved_from
        if floor:
            cursor.execute(
                "SELECT ISNULL(MAX(TransactionNo), ?) + 1 FROM %s WITH (UPDLOCK, HOLDLOCK) "
                "WHERE TransactionNo >= ?" % table, (floor - 1, floor))
        else:
            cursor.execute("SELECT ISNULL(MAX(TransactionNo), 0) + 1 FROM %s WITH (UPDLOCK, HOLDLOCK)" % table)
        row = cursor.fetchone()
        if not row or row[0] is None:
            raise ContractError("could not allocate a TransactionNo")
        return int(row[0])

    def assert_number_is_ours(self, connection, transaction_no):
        """Refuse to commit if the number now belongs to someone else's document too.

        Run after the INSERTs and before COMMIT: our own header row is the one row expected. A
        second row means another writer committed the same number while we were working, and
        the database will not complain about it, because RowOrder makes the key unique anyway.
        """
        table = approved_identifier(self.config.get("header_table") or "")
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM %s WHERE TransactionNo = ?" % table, (transaction_no,))
        row = cursor.fetchone()
        found = int(row[0]) if row and row[0] is not None else 0
        if found != 1:
            raise ContractError(
                "TransactionNo %s is used by %d documents; refusing to add another"
                % (transaction_no, found))

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
        # ERP stores TransactionNo as an int, so an allocated number arrives as one.
        require(isinstance(transaction_no, int) or text(transaction_no), "transaction_no is required")
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

    def write(self, payload, transaction_no=None):
        """Insert Header and Details inside one transaction, or roll everything back."""
        if not self.enabled:
            raise DOWriteDisabled("do_write.enabled is false")
        # Validation precedes the connection; with an allocated number the statements are rebuilt
        # once the real number is known, inside the same transaction that takes the lock.
        self.prepare(payload, transaction_no or "PENDING")
        statements = None if self.auto_transaction_no else self.prepare(payload, transaction_no)
        rehearsal = self.config.get("rollback_only") is True
        connection = self.connect()
        commit_started = False
        try:
            cursor = connection.cursor()
            if statements is None:
                transaction_no = self.next_transaction_no(connection)
                statements = self.prepare(payload, transaction_no)
            for sql, parameters in statements:
                cursor.execute(sql, parameters)
            self.assert_number_is_ours(connection, transaction_no)
            if rehearsal:
                # Proves permission, mapping and SQL shape against the real tables, then leaves
                # nothing behind. Used before the first committed write.
                connection.rollback()
                return {"transaction_no": transaction_no, "header_rows": 1,
                        "detail_rows": len(statements) - 1, "committed": False}
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
                "detail_rows": len(statements) - 1, "committed": True}

    @property
    def update_enabled(self):
        """Changing a document ERP already holds is a separate permission from creating one."""
        return self.config.get("update_enabled") is True

    def assert_can_be_updated(self, connection, transaction_no):
        """Refuse to touch a document that is no longer ours to change.

        Once ERP has approved, closed or accounted a delivery order it belongs to their process.
        Two rows sharing the number means something went wrong earlier and a person has to look.
        """
        table = approved_identifier(self.config.get("header_table") or "")
        cursor = connection.cursor()
        cursor.execute("SELECT IsApproved, IsClosed, IsAcc FROM %s WHERE TransactionNo = ?" % table,
                       (transaction_no,))
        found = cursor.fetchall()
        if len(found) != 1:
            raise ContractError("TransactionNo %s matches %d documents in ERP; refusing to update"
                                % (transaction_no, len(found)))
        approved, closed, accounted = (int(value or 0) for value in found[0])
        if approved or closed or accounted:
            raise ContractError("document %s is approved, closed or already in accounting; "
                                "it can no longer be changed from here" % transaction_no)

    def update(self, payload, transaction_no):
        """Rewrite a document ERP already holds: header in place, detail lines replaced.

        The lines are replaced rather than matched one by one, because eVRP sends the document it
        now believes in, not a list of edits. That means a DELETE, which is why this needs a flag
        of its own; it happens in the same transaction as the rewrite, so a failure anywhere
        leaves the document exactly as it was.
        """
        if not self.enabled:
            raise DOWriteDisabled("do_write.enabled is false")
        if not self.update_enabled:
            raise DOWriteDisabled("do_write.update_enabled is false")
        require(isinstance(transaction_no, int) or text(transaction_no), "transaction_no is required")
        header = payload.get("header")
        require(isinstance(header, dict), "DO payload requires a header object")
        details = payload.get("details")
        require(isinstance(details, list) and details, "DO payload requires at least one detail line")

        rewrite = build_update(self.config.get("header_table"), self.config.get("header_columns"),
                               header, transaction_no)
        detail_table = approved_identifier(self.config.get("detail_table") or "")
        start = int(self.config.get("detail_line_start", 1))
        inserts = []
        for index, line in enumerate(details):
            require(isinstance(line, dict), "each DO detail line must be an object")
            inserts.append(build_insert(self.config.get("detail_table"),
                                        self.config.get("detail_columns"), line,
                                        transaction_no, line_no=start + index))

        rehearsal = self.config.get("rollback_only") is True
        connection = self.connect()
        commit_started = False
        try:
            self.assert_can_be_updated(connection, transaction_no)
            cursor = connection.cursor()
            cursor.execute(*rewrite)
            cursor.execute("DELETE FROM %s WHERE TransactionNo = ?" % detail_table, (transaction_no,))
            for sql, parameters in inserts:
                cursor.execute(sql, parameters)
            if rehearsal:
                connection.rollback()
                return {"transaction_no": transaction_no, "header_rows": 1,
                        "detail_rows": len(inserts), "committed": False}
            commit_started = True
            connection.commit()
        except Exception:
            if commit_started:
                raise DOWriteAmbiguous("commit outcome is unknown")
            try:
                connection.rollback()
            except Exception:
                raise DOWriteAmbiguous("rollback failed after an update error")
            raise
        finally:
            try:
                connection.close()
            except Exception:
                pass  # The transaction already resolved; closing is best effort.
        return {"transaction_no": transaction_no, "header_rows": 1,
                "detail_rows": len(inserts), "committed": True}
