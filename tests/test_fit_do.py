"""Tests for checking a staged DO against the ERP column shapes.

No database: the column definitions are supplied directly.
"""

import unittest
from datetime import datetime
from decimal import Decimal

from thaisausage.fit_do import column_shapes, digits, measured, problems


HEADER = {"DoNo": {"source": "payload", "path": "do_no"},
          "CustName": {"source": "payload", "path": "cust_name"},
          "TotalAmount": {"source": "payload", "path": "total_amount"},
          "TransactionNo": {"source": "transaction_no"},
          "EntryDate": {"source": "server_time"}}

SHAPES = {
    "DoNo": {"COLUMN_NAME": "DoNo", "DATA_TYPE": "varchar", "CHARACTER_MAXIMUM_LENGTH": 20,
             "NUMERIC_PRECISION": None, "NUMERIC_SCALE": None},
    "CustName": {"COLUMN_NAME": "CustName", "DATA_TYPE": "nvarchar", "CHARACTER_MAXIMUM_LENGTH": 30,
                 "NUMERIC_PRECISION": None, "NUMERIC_SCALE": None},
    "TotalAmount": {"COLUMN_NAME": "TotalAmount", "DATA_TYPE": "decimal",
                    "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": 8, "NUMERIC_SCALE": 2},
    "TransactionNo": {"COLUMN_NAME": "TransactionNo", "DATA_TYPE": "int",
                      "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": 10, "NUMERIC_SCALE": 0},
    "EntryDate": {"COLUMN_NAME": "EntryDate", "DATA_TYPE": "datetime",
                  "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": None, "NUMERIC_SCALE": None},
}


def check(payload, shapes=None):
    return problems(HEADER, shapes or SHAPES, payload, 900000, None, "dbo.tbl_DOhdr")


class FitTests(unittest.TestCase):
    def test_a_document_that_fits_reports_nothing(self):
        self.assertEqual(check({"do_no": "DO-1", "cust_name": "ลูกค้า", "total_amount": 100}), [])

    def test_the_column_that_is_too_narrow_is_named(self):
        long_name = "บมจ. ซีพี แอ็กซ์ตร้า (สำนักงานใหญ่) จำกัด มหาชน"
        found = check({"do_no": "DO-1", "cust_name": long_name})
        self.assertEqual(len(found), 1)
        column, reason, value = found[0]
        self.assertEqual(column, "CustName")
        self.assertIn(str(len(long_name)), reason)
        self.assertIn("30", reason)
        self.assertEqual(value, long_name)

    def test_a_number_with_too_many_digits_is_reported(self):
        found = check({"do_no": "DO-1", "total_amount": 1234567.89})  # decimal(8,2) holds 6 digits
        self.assertEqual([column for column, _, _ in found], ["TotalAmount"])

    def test_a_number_that_fits_its_precision_is_not_reported(self):
        self.assertEqual(check({"do_no": "DO-1", "total_amount": 99804.8}), [])

    def test_a_column_the_table_does_not_have_is_reported(self):
        shapes = {name: shape for name, shape in SHAPES.items() if name != "CustName"}
        found = check({"do_no": "DO-1", "cust_name": "x"}, shapes)
        self.assertEqual(found[0][0], "CustName")
        self.assertIn("ไม่มีคอลัมน์", found[0][1])

    def test_the_server_clock_is_not_measured(self):
        self.assertEqual(check({"do_no": "DO-1"}), [])


class MeasureTests(unittest.TestCase):
    def test_a_date_is_measured_as_it_is_stored(self):
        self.assertEqual(measured(datetime(2026, 9, 26, 10, 30)), len("2026-09-26T10:30:00"))

    def test_nothing_takes_no_room(self):
        self.assertEqual(measured(None), 0)

    def test_digits_counts_only_the_whole_part(self):
        self.assertEqual(digits(Decimal("99804.80")), 5)
        self.assertEqual(digits(-1234), 4)
        self.assertEqual(digits("text"), 0)


class QueryTests(unittest.TestCase):
    def test_the_table_name_is_bound_not_pasted(self):
        calls = []

        class Connector:
            def select_approved(self, connection, sql, parameters=()):
                from thaisausage.sqlserver import reviewed_select
                reviewed_select(sql)
                calls.append((sql, parameters))
                return []
        column_shapes(Connector(), None, "dbo.tbl_DOhdr")
        sql, parameters = calls[0]
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", sql)
        self.assertEqual(parameters, ("dbo", "tbl_DOhdr"))

    def test_a_table_without_a_schema_defaults_to_dbo(self):
        calls = []

        class Connector:
            def select_approved(self, connection, sql, parameters=()):
                calls.append(parameters)
                return []
        column_shapes(Connector(), None, "tbl_Dodtl")
        self.assertEqual(calls[0], ("dbo", "tbl_Dodtl"))


if __name__ == "__main__":
    unittest.main()
