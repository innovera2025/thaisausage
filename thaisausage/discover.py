"""Read-only ERP schema discovery.

Answers the questions a mapping needs — column types, lengths, nullability, keys, triggers
and where an approval flag lives — using metadata views only. It never reads business rows,
never writes, and prints no credential. Run it where the ERP is reachable:

    python3 -m thaisausage.discover --config config/local.json --out discovery.json
"""

import argparse
import json

from .config import load_config
from .sqlserver import SQLServerConnector


COLUMNS_SQL = """
SELECT c.TABLE_SCHEMA AS table_schema, c.TABLE_NAME AS table_name, c.ORDINAL_POSITION AS position,
       c.COLUMN_NAME AS column_name, c.DATA_TYPE AS data_type,
       c.CHARACTER_MAXIMUM_LENGTH AS max_length, c.NUMERIC_PRECISION AS precision,
       c.NUMERIC_SCALE AS scale, c.IS_NULLABLE AS is_nullable, c.COLUMN_DEFAULT AS column_default,
       c.COLLATION_NAME AS collation
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME = ?
ORDER BY c.ORDINAL_POSITION
"""

KEYS_SQL = """
SELECT i.name AS index_name, i.is_primary_key AS is_primary_key, i.is_unique AS is_unique,
       col.name AS column_name, ic.key_ordinal AS key_ordinal
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns col ON col.object_id = ic.object_id AND col.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID(?) AND i.is_hypothetical = 0
ORDER BY i.name, ic.key_ordinal
"""

IDENTITY_SQL = """
SELECT col.name AS column_name, col.is_identity AS is_identity, col.is_computed AS is_computed
FROM sys.columns col
WHERE col.object_id = OBJECT_ID(?) AND (col.is_identity = 1 OR col.is_computed = 1)
"""

TRIGGER_SQL = """
SELECT t.name AS trigger_name, t.is_disabled AS is_disabled
FROM sys.triggers t
WHERE t.parent_id = OBJECT_ID(?)
"""

FOREIGN_KEY_SQL = """
SELECT fk.name AS constraint_name, cpa.name AS column_name,
       OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS referenced_schema,
       OBJECT_NAME(fk.referenced_object_id) AS referenced_table, cref.name AS referenced_column
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns cpa ON cpa.object_id = fkc.parent_object_id AND cpa.column_id = fkc.parent_column_id
JOIN sys.columns cref ON cref.object_id = fkc.referenced_object_id AND cref.column_id = fkc.referenced_column_id
WHERE fk.parent_object_id = OBJECT_ID(?)
"""

FIND_COLUMN_SQL = """
SELECT c.TABLE_SCHEMA AS table_schema, c.TABLE_NAME AS table_name, t.TABLE_TYPE AS table_type,
       c.DATA_TYPE AS data_type
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.COLUMN_NAME = ?
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME
"""


def describe(connector, connection, table):
    """Collect the metadata one target table needs, without touching its rows."""
    plain = table.split(".")[-1]
    return {
        "table": table,
        "columns": connector.select_approved(connection, COLUMNS_SQL, (plain,)),
        "keys": connector.select_approved(connection, KEYS_SQL, (table,)),
        "identity_or_computed": connector.select_approved(connection, IDENTITY_SQL, (table,)),
        "triggers": connector.select_approved(connection, TRIGGER_SQL, (table,)),
        "foreign_keys": connector.select_approved(connection, FOREIGN_KEY_SQL, (table,)),
    }


def discover(config, tables, find_columns):
    connector = SQLServerConnector(config.get("sqlserver", {}))
    connection = connector.connect()
    try:
        report = {"tables": [describe(connector, connection, table) for table in tables],
                  "column_search": {}}
        for column in find_columns:
            report["column_search"][column] = connector.select_approved(
                connection, FIND_COLUMN_SQL, (column,))
        return report
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Read-only ERP schema discovery")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--tables", default="dbo.tbl_DOhdr,dbo.tbl_Dodtl",
                        help="comma separated tables to describe")
    parser.add_argument("--find-column", default="IsApprSo",
                        help="comma separated column names to locate across tables and views")
    parser.add_argument("--out", default="discovery.json")
    args = parser.parse_args()
    config = load_config(args.config)
    tables = [table.strip() for table in args.tables.split(",") if table.strip()]
    columns = [column.strip() for column in args.find_column.split(",") if column.strip()]
    report = discover(config, tables, columns)
    with open(args.out, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n")
    for table in report["tables"]:
        print("%s: %d columns, %d keys, %d triggers, %d foreign keys" % (
            table["table"], len(table["columns"]), len(table["keys"]),
            len(table["triggers"]), len(table["foreign_keys"])))
    for column, hits in report["column_search"].items():
        print("%s found in %d tables/views" % (column, len(hits)))
    print("written to %s (metadata only, no business rows)" % args.out)


if __name__ == "__main__":
    main()
