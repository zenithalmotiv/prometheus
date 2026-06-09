"""
Tests for Prometheus database operations.
"""

import os
import sys
import unittest
import tempfile
import shutil

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import config
from db.database import (
    init_db, get_connection,
    add_item, get_item_by_id, get_item_by_name, list_all_items,
    update_item, delete_item, delete_all_items,
    perform_stock_movement, get_low_stock_items, get_order_list,
    get_zero_stock_items, get_daily_report,
    list_purposes, add_purpose, remove_purpose,
    get_setting, set_setting, verify_secret_word, set_secret_word,
    undo_last_action, reset_day,
    create_backup, restore_backup,
    export_to_csv, export_to_excel, bulk_import_items,
)


class TestDatabase(unittest.TestCase):
    """Test cases for database operations."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, "test.db")
        # Override database path
        config.DATABASE_PATH = cls.db_path
        config.REORDER_DAYS = 3
        init_db()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        """Clear items before each test."""
        delete_all_items()

    # --- Item CRUD ---

    def test_add_item(self):
        ok, msg = add_item("R001", "Rice", "kg", 100, 100, 40)
        self.assertTrue(ok)
        self.assertIn("added", msg)

    def test_add_item_duplicate(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg = add_item("R001", "Rice", "kg", 100, 100, 40)
        self.assertFalse(ok)
        self.assertIn("already exists", msg)

    def test_get_item_by_id(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        item = get_item_by_id("R001")
        self.assertIsNotNone(item)
        self.assertEqual(item["item_name"], "Rice")

    def test_get_item_by_name(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        item = get_item_by_name("Rice")
        self.assertIsNotNone(item)
        self.assertEqual(item["item_id"], "R001")

    def test_list_all_items(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        add_item("S001", "Sugar", "kg", 50, 50, 20)
        items = list_all_items()
        self.assertEqual(len(items), 2)

    def test_update_item(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg = update_item("R001", {"current_stock": 80})
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 80)

    def test_delete_item(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg = delete_item("R001")
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertIsNone(item)

    def test_delete_all_items(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        add_item("S001", "Sugar", "kg", 50, 50, 20)
        ok, msg = delete_all_items()
        self.assertTrue(ok)
        items = list_all_items()
        self.assertEqual(len(items), 0)

    # --- Stock Movements ---

    def test_used_movement(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, tx_id = perform_stock_movement("R001", "used", 10, "biriyani")
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 90)
        self.assertEqual(item["used"], 10)

    def test_purchased_movement(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, tx_id = perform_stock_movement("R001", "purchased", 50)
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 150)
        self.assertEqual(item["purchased"], 50)

    def test_damaged_movement(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, tx_id = perform_stock_movement("R001", "damaged", 5)
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 95)
        self.assertEqual(item["damaged"], 5)

    def test_insufficient_stock(self):
        add_item("R001", "Rice", "kg", 10, 10, 40)
        ok, msg, tx_id = perform_stock_movement("R001", "used", 20, "biriyani")
        self.assertFalse(ok)
        self.assertIn("Insufficient", msg)

    def test_transfer_woods(self):
        add_item("C001", "Chicken", "kg", 20, 20, 10)
        ok, msg, tx_id = perform_stock_movement("C001", "woods", 5)
        self.assertTrue(ok)
        item = get_item_by_id("C001")
        self.assertEqual(item["current_stock"], 15)
        self.assertEqual(item["woods"], 5)

    def test_stock_adjustment(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, tx_id = perform_stock_movement("R001", "stock adjustment", 150)
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 150)

    # --- Queries ---

    def test_low_stock(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)  # 2.5 days left (low)
        add_item("O001", "Oil", "L", 50, 50, 5)  # 10 days (ok)
        add_item("S001", "Salt", "kg", 2, 2, 1)  # 2 days (low)
        low = get_low_stock_items()
        self.assertEqual(len(low), 2)  # Rice and Salt

    def test_zero_stock(self):
        add_item("R001", "Rice", "kg", 100, 0, 40)
        add_item("S001", "Sugar", "kg", 50, 50, 20)
        zero = get_zero_stock_items()
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0]["item_id"], "R001")

    # --- Purposes ---

    def test_add_purpose(self):
        ok, msg = add_purpose("test_purpose")
        self.assertTrue(ok)
        purposes = list_purposes()
        self.assertIn("test_purpose", purposes)

    def test_remove_purpose(self):
        add_purpose("test_purpose")
        ok, msg = remove_purpose("test_purpose")
        self.assertTrue(ok)
        purposes = list_purposes()
        self.assertNotIn("test_purpose", purposes)

    # --- Settings ---

    def test_settings(self):
        set_setting("test_key", "test_value")
        value = get_setting("test_key")
        self.assertEqual(value, "test_value")

    def test_secret_word(self):
        set_secret_word("mysecret")
        self.assertTrue(verify_secret_word("mysecret"))
        self.assertFalse(verify_secret_word("wrong"))

    # --- Undo ---

    def test_undo(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        perform_stock_movement("R001", "used", 10, "biriyani")
        ok, msg = undo_last_action()
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 100)

    def test_undo_purchased(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        perform_stock_movement("R001", "purchased", 50)
        ok, msg = undo_last_action()
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["current_stock"], 100)

    # --- Reset Day ---

    def test_reset_day(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        perform_stock_movement("R001", "used", 10, "biriyani")  # current: 100 -> 90
        ok, msg = reset_day()
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertEqual(item["starting_stock"], 90)  # current_stock carried forward
        self.assertEqual(item["used"], 0)  # counters reset

    # --- Export ---

    def test_export_csv(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, filepath = export_to_csv()
        self.assertTrue(ok)
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))

    def test_export_excel(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, filepath = export_to_excel()
        self.assertTrue(ok)
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))

    # --- Bulk Import ---

    def test_bulk_import(self):
        items = [
            {"item_id": "R001", "item_name": "Rice", "unit": "kg", "starting_stock": "100", "current_stock": "100", "avg_daily_usage": "40"},
            {"item_id": "S001", "item_name": "Sugar", "unit": "kg", "starting_stock": "50", "current_stock": "50", "avg_daily_usage": "20"},
        ]
        success, failed, errors = bulk_import_items(items)
        self.assertEqual(success, 2)
        self.assertEqual(failed, 0)
        items = list_all_items()
        self.assertEqual(len(items), 2)

    # --- Backup ---

    def test_create_backup(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, filepath = create_backup("test backup")
        self.assertTrue(ok)
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))

    def test_restore_backup(self):
        add_item("R001", "Rice", "kg", 100, 100, 40)
        ok, msg, filepath = create_backup("for restore")
        self.assertTrue(ok)

        # Delete item
        delete_all_items()
        items = list_all_items()
        self.assertEqual(len(items), 0)

        # Restore
        ok, msg = restore_backup(filepath)
        self.assertTrue(ok)
        item = get_item_by_id("R001")
        self.assertIsNotNone(item)


if __name__ == "__main__":
    unittest.main()
