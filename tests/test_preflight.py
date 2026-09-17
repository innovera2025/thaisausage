"""Tests for the pre-send check.

No database and no network: the SQL connector is replaced by a stub so the checks themselves
are what is under test.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from thaisausage import preflight


ROOT = Path(__file__).resolve().parents[1]
QUERY = ("SELECT TOP (5000) LTRIM(RTRIM(h.OrderNo)) AS order_no FROM dbo.SalesOrderHdr h "
         "WHERE h.IsApprSo = 1 AND LTRIM(RTRIM(h.Company)) = 'TST' "
         "AND CASE LTRIM(RTRIM(h.LocationCode)) WHEN 'L03' THEN 'HUBCODE' END = 1 "
         "AND LTRIM(RTRIM(h.OrderNo)) = 'SO-1'")


def order(**overrides):
    base = json.loads((ROOT / "examples/erp-order.json").read_text())["orders"][0]
    # The shipped example carries a deliberate placeholder hub; use a realistic one by default.
    base["pickup_hub_code"] = "NKP01"
    base.update(overrides)
    return base


class ConfigurationReportTests(unittest.TestCase):
    def test_reads_flags_and_query_shape(self):
        report = preflight.configuration_report({
            "dry_run": False, "sync": {"enabled": True}, "do_write": {"enabled": False},
            "sqlserver": {"approved_orders_query": QUERY}})
        self.assertIs(report["dry_run"], False)
        self.assertIs(report["sync_enabled"], True)
        self.assertIs(report["do_write_enabled"], False)
        self.assertTrue(report["approval_filter"])
        self.assertEqual(report["row_limit"], 5000)
        self.assertEqual(report["company_filter"], "TST")
        self.assertEqual(report["single_order_filter"], "SO-1")
        self.assertEqual(report["hub_mapping"], [("L03", "HUBCODE")])

    def test_missing_approval_filter_is_visible(self):
        report = preflight.configuration_report({"sqlserver": {"approved_orders_query": "SELECT 1"}})
        self.assertFalse(report["approval_filter"])
        self.assertIsNone(report["row_limit"])


class OrderProblemTests(unittest.TestCase):
    def test_clean_order_has_no_problems(self):
        self.assertEqual(preflight.order_problems(order()), [])

    def test_placeholder_hub_is_reported(self):
        problems = preflight.order_problems(order(pickup_hub_code="HUBCODE"))
        self.assertIn("pickup_hub_code is still a placeholder", problems)

    def test_missing_delivery_target_is_reported(self):
        problems = preflight.order_problems(order(delivery_point_code="", shipping_address=""))
        self.assertTrue(any("delivery" in p for p in problems))

    def test_contract_error_is_reported_without_echoing_data(self):
        broken = order()
        broken["items"][0]["quantity"] = 0
        problems = preflight.order_problems(broken)
        self.assertTrue(problems)
        self.assertNotIn(broken["customer"]["name"], " ".join(problems))

    def test_rejected_reason_from_mapping_is_kept(self):
        problems = preflight.order_problems(order(rejected_reason="detail_item_code_missing"))
        self.assertIn("detail_item_code_missing", problems)


class ReconciliationTests(unittest.TestCase):
    def totals_rows(self, amount):
        return [{"order_no": "SO-DEMO-0001", "total_amount": amount, "total_actual_amount": None}]

    def run_with(self, rows):
        connector = Mock()
        connector.select_approved.return_value = rows
        with patch.object(preflight, "SQLServerConnector", return_value=connector):
            return preflight.reconcile_totals({"totals_query": "SELECT 1 AS order_no"}, [order()])

    def test_skipped_without_a_totals_query(self):
        self.assertIsNone(preflight.reconcile_totals({}, [order()]))

    def test_matching_total_reports_no_difference(self):
        expected = sum(i["quantity"] * i["unit_price"] for i in order()["items"])
        self.assertEqual(self.run_with(self.totals_rows(expected))["differences"], [])

    def test_mismatch_is_reported(self):
        result = self.run_with(self.totals_rows(999999.0))
        self.assertEqual(len(result["differences"]), 1)
        self.assertIn("SO-DEMO-0001", result["differences"][0][0])

    def test_missing_header_row_is_reported(self):
        result = self.run_with([])
        self.assertEqual(result["differences"][0][1], "no header total found")


class InspectTests(unittest.TestCase):
    def inspect_with(self, orders, config=None):
        connector = Mock()
        connector.fetch_approved_orders.return_value = orders
        with patch.object(preflight, "SQLServerConnector", return_value=connector):
            return preflight.inspect(config or {"sqlserver": {"approved_orders_query": QUERY}})

    def test_counts_payment_terms_and_lists_master_data(self):
        report = self.inspect_with([
            order(order_no="SO-A", payment_in_day=0),
            order(order_no="SO-B", payment_in_day=30),
            order(order_no="SO-C", payment_in_day=None)])
        self.assertEqual((report["cod"], report["credit"], report["not_cod"]), (1, 1, 1))
        self.assertEqual(report["orders"], 3)
        self.assertEqual(report["evrp_master"]["customer_codes"], ["CUSTOMER-DEMO"])
        self.assertEqual(report["evrp_master"]["hub_codes"], ["NKP01"])

    def test_duplicate_and_untrimmed_order_numbers_are_surfaced(self):
        report = self.inspect_with([order(order_no="SO-A "), order(order_no="SO-A ")])
        self.assertEqual(report["duplicate_order_no"], ["SO-A "])
        self.assertEqual(len(report["untrimmed_order_no"]), 2)

    def test_all_orders_drops_the_single_order_filter(self):
        connector = Mock()
        connector.fetch_approved_orders.return_value = []
        with patch.object(preflight, "SQLServerConnector", return_value=connector) as factory:
            preflight.inspect({"sqlserver": {"approved_orders_query": QUERY}}, all_orders=True)
        used = factory.call_args.args[0]["approved_orders_query"]
        self.assertNotIn("h.OrderNo)) = 'SO-1'", used)
        self.assertIn("IsApprSo = 1", used)


if __name__ == "__main__":
    unittest.main()
