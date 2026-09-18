"""Tests for reading a written DO back out of ERP and comparing it with what we sent.

No database is involved: the SELECT text is checked directly and the comparison is exercised
through its own function.
"""

import unittest
from datetime import datetime
from decimal import Decimal

from thaisausage.contracts import ContractError
from thaisausage.verify_do import columns_of, comparable, expected, read_rows


class FakeConnector:
    """Records the statement instead of running it, and enforces the same SELECT guard."""

    def __init__(self):
        self.calls = []

    def select_approved(self, connection, sql, parameters=()):
        from thaisausage.sqlserver import reviewed_select
        reviewed_select(sql)
        self.calls.append((sql, parameters))
        return []


class QueryTests(unittest.TestCase):
    def test_the_transaction_number_is_bound_not_pasted(self):
        connector = FakeConnector()
        read_rows(connector, None, "dbo.tbl_DOhdr", ["DoNo", "CustCode"], 11504)
        sql, parameters = connector.calls[0]
        self.assertEqual(sql, "SELECT DoNo, CustCode FROM dbo.tbl_DOhdr WHERE TransactionNo = ?")
        self.assertEqual(parameters, (11504,))

    def test_detail_rows_are_read_in_line_order(self):
        connector = FakeConnector()
        read_rows(connector, None, "dbo.tbl_Dodtl", ["Slno"], 11504, order_by="Slno")
        self.assertTrue(connector.calls[0][0].endswith("ORDER BY Slno"))

    def test_a_column_name_outside_the_configuration_is_refused(self):
        with self.assertRaises(ContractError):
            columns_of({"DoNo; DROP TABLE x": {}})

    def test_an_empty_mapping_is_refused(self):
        with self.assertRaises(ContractError):
            columns_of({})


class ComparisonTests(unittest.TestCase):
    """ERP pads text, returns money as Decimal and dates as datetime."""

    def test_padding_does_not_count_as_a_difference(self):
        self.assertEqual(comparable("A20-002   "), comparable("A20-002"))

    def test_money_matches_across_types(self):
        self.assertEqual(comparable(Decimal("5950.00")), comparable(5950))
        self.assertEqual(comparable("595.00"), comparable(595.0))

    def test_a_date_is_compared_by_its_day(self):
        self.assertEqual(comparable(datetime(2026, 9, 18, 14, 30)), comparable("2026-09-18"))

    def test_blank_and_missing_are_the_same_absence(self):
        self.assertIsNone(comparable("   "))
        self.assertIsNone(comparable(None))

    def test_a_real_difference_is_still_reported(self):
        self.assertNotEqual(comparable("A20-002"), comparable("A20-003"))


class ExpectedValueTests(unittest.TestCase):
    def test_every_mapping_source_resolves(self):
        payload = {"do_no": "DO-1", "qty": 10}
        self.assertEqual(expected({"source": "payload", "path": "do_no"}, payload, 1, 1), "DO-1")
        self.assertEqual(expected({"source": "fixed", "value": 0}, payload, 1, 1), 0)
        self.assertEqual(expected({"source": "transaction_no"}, payload, 11504, 1), 11504)
        self.assertEqual(expected({"source": "line_no"}, payload, 1, 3), 3)

    def test_the_server_clock_is_not_compared(self):
        self.assertIsNone(expected({"source": "server_time"}, {}, 1, 1))


if __name__ == "__main__":
    unittest.main()
