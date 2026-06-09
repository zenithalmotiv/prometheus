"""
Tests for Prometheus AI service.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_service import AIService, ai_service


class TestAIService(unittest.TestCase):
    """Test cases for AI service parsing."""

    def setUp(self):
        self.ai = AIService()
        # Disable Gemini for tests (use fallback parser)
        self.ai.enabled = False

    # --- Fallback Parser Tests ---

    def test_parse_used(self):
        success, actions = self.ai.parse_with_fallback("used 5 kg rice for biriyani")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "used")
        self.assertEqual(actions[0].quantity, 5)
        self.assertEqual(actions[0].unit, "kg")
        self.assertEqual(actions[0].item_name, "rice")
        self.assertEqual(actions[0].purpose, "biriyani")

    def test_parse_purchased(self):
        success, actions = self.ai.parse_with_fallback("purchased 25 kg sugar")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "purchased")
        self.assertEqual(actions[0].quantity, 25)
        self.assertEqual(actions[0].unit, "kg")
        self.assertEqual(actions[0].item_name, "sugar")

    def test_parse_damaged(self):
        success, actions = self.ai.parse_with_fallback("damaged 2 kg onion")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "damaged")
        self.assertEqual(actions[0].quantity, 2)

    def test_parse_wipro_in(self):
        success, actions = self.ai.parse_with_fallback("wipro in 3 L oil")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "wipro in")
        self.assertEqual(actions[0].quantity, 3)

    def test_parse_wipro_out(self):
        success, actions = self.ai.parse_with_fallback("wipro out 1 kg jeera")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "wipro out")

    def test_parse_woods_transfer(self):
        success, actions = self.ai.parse_with_fallback("woods 2 kg chicken")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "woods")
        self.assertEqual(actions[0].quantity, 2)
        self.assertEqual(actions[0].destination, "woods")

    def test_parse_garden_cafe(self):
        success, actions = self.ai.parse_with_fallback("garden cafe 5 kg potato")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "garden cafe")

    def test_parse_check_stock(self):
        success, actions = self.ai.parse_with_fallback("check rice")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "check")
        self.assertEqual(actions[0].item_name, "rice")

    def test_parse_low_stock(self):
        success, actions = self.ai.parse_with_fallback("low stock")
        self.assertTrue(success)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "low stock")

    def test_parse_conversational(self):
        success, actions = self.ai.parse_with_fallback("We used around 5 kilos of rice today for biriyani, please update it")
        self.assertTrue(success)
        self.assertGreaterEqual(len(actions), 1)
        self.assertEqual(actions[0].action, "used")
        self.assertEqual(actions[0].quantity, 5)

    def test_parse_no_action(self):
        success, actions = self.ai.parse_with_fallback("hello how are you")
        self.assertFalse(success)

    # --- Quantity Extraction ---

    def test_extract_quantity_kg(self):
        qty = self.ai._extract_quantity("used 5 kg rice")
        self.assertEqual(qty, 5)

    def test_extract_quantity_decimal(self):
        qty = self.ai._extract_quantity("used 2.5 kg rice")
        self.assertEqual(qty, 2.5)

    def test_extract_quantity_grams(self):
        qty = self.ai._extract_quantity("used 500 g sugar")
        self.assertEqual(qty, 500)

    def test_extract_quantity_no_unit(self):
        qty = self.ai._extract_quantity("used 5 rice")
        self.assertEqual(qty, 5)

    # --- Unit Extraction ---

    def test_extract_unit_kg(self):
        unit = self.ai._extract_unit("used 5 kg rice")
        self.assertEqual(unit, "kg")

    def test_extract_unit_litres(self):
        unit = self.ai._extract_unit("bought 2 litres of milk")
        self.assertEqual(unit, "L")

    def test_extract_unit_pieces(self):
        unit = self.ai._extract_unit("used 10 pieces of bread")
        self.assertEqual(unit, "pcs")

    def test_extract_unit_default(self):
        unit = self.ai._extract_unit("used 5 rice")
        self.assertEqual(unit, "pcs")

    # --- Confirmation Formatting ---

    def test_format_confirmation(self):
        from models import ParsedAction
        actions = [
            ParsedAction(action="used", item_name="rice", quantity=5, unit="kg", purpose="biriyani", confidence=0.9),
            ParsedAction(action="purchased", item_name="sugar", quantity=10, unit="kg", confidence=0.9),
        ]
        msg = self.ai.format_for_confirmation(actions)
        self.assertIn("rice", msg)
        self.assertIn("sugar", msg)
        self.assertIn("biriyani", msg)
        self.assertIn("Please confirm", msg)


if __name__ == "__main__":
    unittest.main()
