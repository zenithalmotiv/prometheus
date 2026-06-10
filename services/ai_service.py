"""
AI Service for Prometheus.
Handles natural language understanding using Gemini API.
Converts conversational input into structured inventory actions.
"""

import json
import re
from typing import Optional, Dict, Any, Tuple
from dataclasses import asdict

from app.config import config
from models import ParsedAction


# Try importing Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Movement keywords for fallback parser
MOVEMENT_KEYWORDS = {
    "used": ["used", "use", "consumed", "ate", "cooked", "took", "spent"],
    "purchased": ["purchased", "bought", "buy", "ordered", "received", "got"],
    "damaged": ["damaged", "spoiled", "broken", "wasted", "rotten", "bad"],
    "wipro in": ["wipro in", "wipro received", "received from wipro"],
    "wipro out": ["wipro out", "sent to wipro", "wipro sent"],
    "rajagiri main": ["rajagiri main", "sent to rajagiri", "rajagiri canteen"],
    "woods": ["woods", "sent to woods"],
    "garden cafe": ["garden cafe", "sent to garden cafe"],
    "bba canteen": ["bba canteen", "sent to bba canteen"],
    "bba tea counter": ["bba tea counter", "bba tea", "sent to bba tea"],
    "check": ["check", "show", "tell me about", "what is the stock", "how much"],
    "low stock": ["low stock", "what to order", "order list", "what should i buy"],
    "list": ["list all", "show all", "inventory list", "all items"],
    "delete_item": ["delete", "remove", "delete item", "remove item", "get rid of", "drop"],
}

UNITS = ["kg", "g", "gram", "grams", "l", "litre", "liter", "litres", "ml", "pcs", "piece", "pieces", "packet", "packets", "box", "boxes", "bottle", "bottles", "tin", "tins", "can", "cans"]


class AIService:
    """Service for AI-powered natural language understanding."""

    def __init__(self):
        self.enabled = config.gemini_enabled and GEMINI_AVAILABLE
        self.model = None
        if self.enabled:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
            except Exception as e:
                self.enabled = False

    def _build_system_prompt(self) -> str:
        """Build the system prompt for Gemini."""
        return """You are Prometheus, a canteen inventory management assistant. 
Parse the user's natural language request into a structured JSON action.

Available actions: used, purchased, damaged, wipro_in, wipro_out, 
rajagiri_main, woods, garden_cafe, bba_canteen, bba_tea_counter, 
check_stock, low_stock, list_all, add_item, delete_item.

Rules:
- Extract item_name, quantity, unit, purpose (for "used" action), and destination (for transfers).
- Quantity must be a number. For delete_item, quantity is 0.
- Unit can be: kg, g, L, ml, pcs, packet, box, bottle, tin, can.
- If the user mentions multiple items, return an array of actions.
- If uncertain, set confidence below 0.8 and include a note.
- For delete/remove requests (e.g. "remove rice", "delete the item sugar"), use action "delete_item".

Respond ONLY with valid JSON in this format:
{
    "actions": [
        {
            "action": "used",
            "item_name": "rice",
            "quantity": 5,
            "unit": "kg",
            "purpose": "biriyani",
            "destination": "",
            "confidence": 0.95,
            "note": ""
        }
    ]
}

For check_stock: set action to "check_stock" and item_name.
For low_stock/order_list: set action to "low_stock".
For list_all: set action to "list_all".
For delete_item: set action to "delete_item" and item_name. Quantity is 0.
"""

    def parse_with_gemini(self, text: str) -> Tuple[bool, list]:
        """Parse natural language using Gemini. Returns (success, actions)."""
        if not self.enabled or not self.model:
            return False, []

        try:
            prompt = self._build_system_prompt()
            response = self.model.generate_content(
                f"{prompt}\n\nUser request: {text}",
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                )
            )

            # Extract JSON from response
            response_text = response.text.strip()
            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)
            actions = data.get("actions", [])

            parsed_actions = []
            for a in actions:
                action = a.get("action", "").lower().replace(" ", "_").replace("-", "_")
                # Normalize action names
                action_map = {
                    "wipro_in": "wipro in",
                    "wipro_out": "wipro out",
                    "rajagiri_main": "rajagiri main",
                    "garden_cafe": "garden cafe",
                    "bba_canteen": "bba canteen",
                    "bba_tea_counter": "bba tea counter",
                    "check_stock": "check",
                    "low_stock": "low stock",
                    "list_all": "list",
                    "delete_item": "delete_item",
                }
                action = action_map.get(action, action)

                parsed_actions.append(ParsedAction(
                    action=action,
                    item_name=a.get("item_name", ""),
                    quantity=float(a.get("quantity", 0)),
                    unit=a.get("unit", ""),
                    purpose=a.get("purpose", ""),
                    destination=a.get("destination", ""),
                    raw_input=text,
                    confidence=float(a.get("confidence", 0.8)),
                ))

            return True, parsed_actions

        except Exception as e:
            return False, [str(e)]

    def parse_with_fallback(self, text: str) -> Tuple[bool, list]:
        """Fallback rule-based parser."""
        text_lower = text.lower().strip()
        actions = []

        # Check for multiple items in one message (e.g., "5 kg rice and 2 L oil")
        parts = re.split(r'\s+and\s+|\s*,\s*', text_lower)

        for part in parts:
            action = self._parse_single_action(part)
            if action:
                actions.append(action)

        return len(actions) > 0, actions

    def _parse_single_action(self, text: str) -> Optional[ParsedAction]:
        """Parse a single action from text."""
        text_lower = text.lower().strip()

        # Detect action type
        detected_action = None
        for action, keywords in MOVEMENT_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    detected_action = action
                    break
            if detected_action:
                break

        if not detected_action:
            return None

        # Handle delete_item: no quantity needed, just item name
        if detected_action == "delete_item":
            item_name = self._extract_item_name_for_delete(text_lower)
            return ParsedAction(
                action="delete_item",
                item_name=item_name,
                quantity=0,
                unit="",
                purpose="",
                destination="",
                raw_input=text,
                confidence=0.85,
            )

        # Extract quantity
        quantity = self._extract_quantity(text_lower)

        # Extract unit
        unit = self._extract_unit(text_lower)

        # Extract item name
        item_name = self._extract_item_name(text_lower, detected_action, quantity, unit)

        # Extract purpose (for "used" action)
        purpose = ""
        if detected_action == "used":
            purpose = self._extract_purpose(text_lower)

        # Extract destination (for transfer actions)
        destination = ""
        if detected_action in ["rajagiri main", "woods", "garden cafe", "bba canteen", "bba tea counter"]:
            destination = detected_action

        if detected_action in ["check", "low stock", "list"]:
            return ParsedAction(
                action=detected_action,
                item_name=item_name,
                quantity=0,
                unit=unit,
                purpose=purpose,
                destination=destination,
                raw_input=text,
                confidence=0.7,
            )

        if not item_name or quantity <= 0:
            return None

        return ParsedAction(
            action=detected_action,
            item_name=item_name,
            quantity=quantity,
            unit=unit,
            purpose=purpose,
            destination=destination,
            raw_input=text,
            confidence=0.7,
        )

    def _extract_item_name_for_delete(self, text: str) -> str:
        """Extract item name from a delete/remove request."""
        # Remove delete keywords
        for kw in MOVEMENT_KEYWORDS.get("delete_item", []):
            text = text.replace(kw, "")
        # Remove filler words
        text = re.sub(r'\b(the|item|a|an|please|from|inventory)\b', '', text)
        return text.strip()

    def _extract_quantity(self, text: str) -> float:
        """Extract quantity number from text."""
        matches = re.findall(r'(\d+\.?\d*)\s*(?:kg|g|gram|grams|l|litre|liter|litres|ml|pcs|piece|pieces|packet|packets|box|boxes|bottle|bottles|tin|tins|can|cans)', text)
        if matches:
            return float(matches[0])
        matches = re.findall(r'(\d+\.?\d*)', text)
        if matches:
            return float(matches[0])
        return 0

    def _extract_unit(self, text: str) -> str:
        """Extract unit from text."""
        for unit in UNITS:
            if re.search(rf'\b{unit}\b', text):
                if unit in ["gram", "grams"]:
                    return "g"
                if unit in ["litre", "liters", "liter", "litres"]:
                    return "L"
                if unit in ["piece", "pieces"]:
                    return "pcs"
                if unit in ["packet", "packets"]:
                    return "packet"
                if unit in ["box", "boxes"]:
                    return "box"
                if unit in ["bottle", "bottles"]:
                    return "bottle"
                if unit in ["tin", "tins"]:
                    return "tin"
                if unit in ["can", "cans"]:
                    return "can"
                return unit
        return "pcs"  # default

    def _extract_item_name(self, text: str, action: str, quantity: float, unit: str) -> str:
        """Extract item name from text."""
        text_clean = text
        for kw in MOVEMENT_KEYWORDS.get(action, []):
            text_clean = text_clean.replace(kw, "")

        text_clean = re.sub(rf'{quantity}\s*{unit}', '', text_clean)
        text_clean = re.sub(r'\d+\.?\d*', '', text_clean)

        if action == "used":
            for p in [" for ", " to make ", " to prepare ", " in "]:
                if p in text_clean:
                    text_clean = text_clean.split(p, 1)[0]
                    break

        text_clean = re.sub(r'\b(kg|g|l|ml|pcs|of|the|a|an|and|with|from|to)\b', '', text_clean)
        text_clean = text_clean.strip()

        return text_clean if text_clean else ""

    def _extract_purpose(self, text: str) -> str:
        """Extract purpose from text (for 'used' action)."""
        purpose_keywords = ["for", "to make", "to prepare", "in"]
        for pk in purpose_keywords:
            if pk in text:
                parts = text.split(pk, 1)
                if len(parts) > 1:
                    purpose = parts[1].strip()
                    purpose = re.sub(r'[.,;!?].*', '', purpose).strip()
                    return purpose
        return ""

    def parse(self, text: str) -> Tuple[bool, list]:
        """
        Parse natural language text into structured actions.
        Tries Gemini first, falls back to rule-based parser.
        """
        if self.enabled:
            success, actions = self.parse_with_gemini(text)
            if success and actions:
                return True, actions

        return self.parse_with_fallback(text)

    def format_for_confirmation(self, actions: list) -> str:
        """Format parsed actions for user confirmation."""
        lines = ["*Please confirm these actions:*\n"]
        for i, action in enumerate(actions, 1):
            if action.action in ["check", "low stock", "list"]:
                lines.append(f"{i}. {action.action.title()}: {action.item_name}")
            elif action.action == "delete_item":
                lines.append(f"{i}. *Delete Item*: {action.item_name} \u26a0\ufe0f (cannot be undone)")
            else:
                lines.append(
                    f"{i}. *{action.action.title()}*: {action.quantity} {action.unit} of {action.item_name}"
                )
                if action.purpose:
                    lines.append(f"   Purpose: {action.purpose}")
                if action.destination:
                    lines.append(f"   Destination: {action.destination.title()}")
        lines.append("\nReply with *yes* to confirm, or *no* to cancel.")
        return "\n".join(lines)


# Global AI service instance
ai_service = AIService()
