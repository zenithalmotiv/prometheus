"""
Tests for Prometheus utility helpers.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helpers import (
    parse_quantity_unit, normalize_unit, sanitize_item_id,
    format_stock_line, truncate_text,
)


class TestHelpers(unittest.TestCase):
    """Test cases for utility helpers."""

    def test_parse_quantity_unit_basic(self):
        qty, unit, remaining = parse_quantity_unit("5 kg rice")
        self.assertEqual(qty, 5)
        self.assertEqual(unit, "kg")
        self.assertEqual(remaining, "rice")

    def test_parse_quantity_unit_decimal(self):
        qty, unit, remaining = parse_quantity_unit("2.5 L oil")
        self.assertEqual(qty, 2.5)
        self.assertEqual(unit, "L")

    def test_parse_quantity_unit_no_unit(self):
        qty, unit, remaining = parse_quantity_unit("10 packets")
        self.assertEqual(qty, 10)
        self.assertEqual(unit, "packet")

    def test_normalize_unit_kg(self):
        self.assertEqual(normalize_unit("kg"), "kg")

    def test_normalize_unit_grams(self):
        self.assertEqual(normalize_unit("grams"), "g")

    def test_normalize_unit_liters(self):
        self.assertEqual(normalize_unit("liters"), "L")

    def test_sanitize_item_id(self):
        self.assertEqual(sanitize_item_id("Rice Premium"), "rice_premium")

    def test_sanitize_item_id_special_chars(self):
        self.assertEqual(sanitize_item_id("Rice & Beans!!"), "rice_beans")

    def test_format_stock_line(self):
        item = {
            "item_name": "Rice",
            "item_id": "R001",
            "current_stock": 100,
            "unit": "kg",
            "avg_daily_usage": 40,
        }
        line = format_stock_line(item)
        self.assertIn("Rice", line)
        self.assertIn("100", line)
        self.assertIn("(2.5d)", line)

    def test_truncate_text_short(self):
        text = "Short text"
        self.assertEqual(truncate_text(text, 100), text)

    def test_truncate_text_long(self):
        text = "x" * 5000
        result = truncate_text(text, 100)
        self.assertTrue(len(result) <= 100)
        self.assertIn("truncated", result)


if __name__ == "__main__":
    unittest.main()
