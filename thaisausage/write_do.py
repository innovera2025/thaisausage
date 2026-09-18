"""Write one staged DO into ERP, deliberately and one document at a time.

The scheduled path never does this: the callback only stages. This command exists so an operator
can prove the write against the real tables under supervision.

Default is a rehearsal — the INSERTs run inside a transaction that is rolled back, which proves
the credential, the mapping and the statement shape while leaving no document behind:

    python3 -m thaisausage.write_do --config config/local.json --receipt-id DO2609040001

TransactionNo is part of the primary key and ERP does not generate it, so the writer allocates
the next number under a lock when do_write.transaction_no_source is "auto". Pass
--transaction-no instead to use a number the ERP team handed over.

Adding --commit keeps the rows. It writes to the live ERP tables, and the row counts printed
before and after are the evidence.
"""

import argparse

from .config import load_config
from .connectors import ERPConnector, VRPConnector
from .do_writer import DOWriter
from .service import IntegrationService
from .sqlserver import SQLServerConnector


def table_counts(config, tables):
    """Count rows in the target tables; SELECT only, so it is safe to run at any time."""
    connector = SQLServerConnector(config.get("sqlserver", {}))
    connection = connector.connect()
    try:
        return {table: connector.select_approved(connection, "SELECT COUNT(*) AS n FROM %s" % table)[0]["n"]
                for table in tables if table}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="Write one staged DO into ERP under supervision")
    parser.add_argument("--config", default="config/local.json")
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--source", default="eVRP")
    parser.add_argument("--transaction-no",
                        help="the TransactionNo to use; omit it when do_write.transaction_no_source is auto, "
                             "which makes the writer allocate one inside the same transaction")
    parser.add_argument("--commit", action="store_true",
                        help="keep the rows instead of rolling back (writes to the live ERP tables)")
    args = parser.parse_args()

    config = load_config(args.config)
    do_write = dict(config.get("do_write") or {})
    if not do_write.get("header_columns") or not do_write.get("detail_columns"):
        raise SystemExit("do_write.header_columns / detail_columns are empty — fill the mapping first")
    # Intent comes from this command line, not from the deployed configuration file.
    do_write["enabled"] = True
    do_write["rollback_only"] = not args.commit
    automatic = do_write.get("transaction_no_source") == "auto"
    if not args.transaction_no and not automatic:
        raise SystemExit("--transaction-no is required unless do_write.transaction_no_source is \"auto\"")

    tables = [do_write.get("header_table"), do_write.get("detail_table")]
    before = table_counts(config, tables)
    print("mode        :", "COMMIT (rows are kept)" if args.commit else "rehearsal (rolled back)")
    print("receipt     :", args.source + ":" + args.receipt_id)
    print("transaction :", args.transaction_no or "allocated by the writer under a lock")
    print("before      :", before)

    service = IntegrationService(config["database"], config["dry_run"],
                                 VRPConnector(config["vrp"]), ERPConnector(config["erp"]))
    result = service.write_do(args.receipt_id, DOWriter(do_write), source=args.source,
                              transaction_no=args.transaction_no)
    if result is None:
        raise SystemExit("no staged DO for %s:%s" % (args.source, args.receipt_id))
    print("result      :", {k: v for k, v in result.items() if k != "receipt_key"})

    after = table_counts(config, tables)
    print("after       :", after)
    added = {table: after[table] - before[table] for table in after}
    print("rows added  :", added)

    if args.commit and result.get("state") == "inserted" and not any(added.values()):
        raise SystemExit("reported inserted but no row count changed — investigate before continuing")
    if not args.commit and any(added.values()):
        raise SystemExit("rehearsal left rows behind — stop and investigate")
    raise SystemExit(0 if result.get("state") in ("inserted", "rehearsed") else 1)


if __name__ == "__main__":
    main()
