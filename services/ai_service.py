"""
AI Service for Prometheus.
Handles natural language understanding using Gemini API.
Converts conversational input into structured inventory actions.
"""

import json
import re
from typing import Optional, Tuple

from app.config import config
from models import ParsedAction


# Try importing Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Fallback rule-based keyword map
# ---------------------------------------------------------------------------
MOVEMENT_KEYWORDS = {
    # Stock movements
    "used":           ["used", "use", "consumed", "ate", "cooked", "took", "spent"],
    "purchased":      ["purchased", "bought", "buy", "ordered", "received", "got", "purchase"],
    "damaged":        ["damaged", "spoiled", "broken", "wasted", "rotten", "bad", "expired"],
    "wipro in":       ["wipro in", "wipro received", "received from wipro"],
    "wipro out":      ["wipro out", "sent to wipro", "wipro sent"],
    "rajagiri main":  ["rajagiri main", "sent to rajagiri", "rajagiri canteen", "rajagiri"],
    "woods":          ["woods", "sent to woods"],
    "garden cafe":    ["garden cafe", "sent to garden cafe", "garden"],
    "bba canteen":    ["bba canteen", "sent to bba canteen"],
    "bba tea counter":["bba tea counter", "bba tea", "sent to bba tea"],
    # Queries
    "check":          ["check", "tell me about", "what is the stock", "how much", "stock of", "how many"],
    "low_stock":      ["low stock", "what to order", "order list", "what should i buy", "running low", "low items"],
    "order_list":     ["order list", "need to order", "items to order", "order"],
    "daily_report":   ["daily report", "today report", "report", "today's report", "todays report"],
    "list":           ["list all", "show all", "inventory list", "all items", "item list", "list items",
                       "give me the list", "show me the list", "show items", "show list"],
    "zero_stock":     ["zero stock", "out of stock", "empty stock", "no stock"],
    # Exports
    "export_csv":     ["export csv", "give me csv", "download csv", "get csv", "csv export",
                       "send csv", "export as csv", "give me the csv"],
    "export_excel":   ["export excel", "give me excel", "download excel", "get excel", "excel export",
                       "send excel", "export as excel", "give me the excel", "xlsx"],
    # Item management
    "add_item":       ["add item", "new item", "add new item", "create item", "add a new", "add rice",
                       "add sugar", "add oil", "add to inventory"],
    "delete_item":    ["delete", "remove", "delete item", "remove item", "get rid of", "drop item"],
    "set_avg":        ["set average", "set avg", "average usage", "avg usage", "daily usage"],
    "set_unit":       ["set unit", "change unit", "unit is"],
    # Admin
    "undo":           ["undo", "undo last", "revert", "take back", "cancel last"],
    "backup":         ["backup", "create backup", "make backup", "save backup"],
    "reset_day":      ["reset day", "reset today", "new day"],
    "stock_adjust":   ["adjust stock", "set stock to", "stock adjustment", "correct stock",
                       "change stock to", "current stock is", "update stock"],
}

UNITS = [
    "kg", "g", "gram", "grams", "l", "litre", "liter", "litres", "ml",
    "pcs", "piece", "pieces", "packet", "packets", "box", "boxes",
    "bottle", "bottles", "tin", "tins", "can", "cans"
]

NO_QTY_ACTIONS = {
    "check", "low_stock", "order_list", "daily_report", "list",
    "zero_stock", "export_csv", "export_excel", "undo", "backup", "reset_day"
}


class AIService:
    """Service for AI-powered natural language understanding."""

    def __init__(self):
        self.enabled = config.gemini_enabled and GEMINI_AVAILABLE
        self.model = None
        if self.enabled:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
            except Exception:
                self.enabled = False

    def _build_system_prompt(self) -> str:
        return """You are Prometheus, a canteen inventory management assistant.
Parse the user's natural language message into a structured JSON action.

AVAILABLE ACTIONS (use EXACTLY these values):

Stock movements (need item_name + quantity + unit):
  used, purchased, damaged,
  wipro_in, wipro_out,
  rajagiri_main, woods, garden_cafe, bba_canteen, bba_tea_counter

Queries (no quantity needed):
  check_stock    - check stock of a specific item (need item_name)
  low_stock      - show low stock items
  order_list     - show items that need ordering
  daily_report   - today's activity report
  list_all       - list all inventory items
  zero_stock     - show items with zero stock

Exports:
  export_csv     - export inventory as CSV file
  export_excel   - export inventory as Excel file

Item management:
  add_item       - add a new item (need item_name, unit, starting_stock, current_stock, avg_daily_usage)
  delete_item    - delete an item (need item_name)
  set_avg        - set average daily usage (need item_name + quantity)
  set_unit       - set unit for an item (need item_name + unit)
  stock_adjust   - adjust/correct current stock to a specific value (need item_name + quantity)

Admin:
  undo           - undo last action
  backup         - create a backup
  reset_day      - reset the day

RULES:
- For add_item: extract item_name, unit, starting_stock (as quantity), avg_daily_usage
  Example: "add item rice with 150 kg starting stock and avg use 40 kg" →
  action=add_item, item_name=rice, unit=kg, quantity=150, avg_daily_usage=40
- For stock_adjust: quantity is the NEW stock value
- For set_avg: quantity is the new average usage value
- For check_stock: item_name is required
- If uncertain, set confidence below 0.7 and explain in note
- Multiple items in one message → return array of actions
- "give me the excel", "send excel", "export excel" → export_excel
- "give me the list", "show all items", "item list" → list_all
- "daily report", "today report" → daily_report
- "low stock", "running low" → low_stock

Respond ONLY with valid JSON:
{
    "actions": [
        {
            "action": "used",
            "item_name": "rice",
            "quantity": 5,
            "unit": "kg",
            "purpose": "biriyani",
            "destination": "",
            "avg_daily_usage": 0,
            "confidence": 0.95,
            "note": ""
        }
    ]
}
"""

    def parse_with_gemini(self, text: str) -> Tuple[bool, list]:
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
            response_text = response.text.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)
            actions = data.get("actions", [])

            action_map = {
                "wipro_in":        "wipro in",
                "wipro_out":       "wipro out",
                "rajagiri_main":   "rajagiri main",
                "garden_cafe":     "garden cafe",
                "bba_canteen":     "bba canteen",
                "bba_tea_counter": "bba tea counter",
                "check_stock":     "check",
                "low_stock":       "low_stock",
                "order_list":      "order_list",
                "daily_report":    "daily_report",
                "list_all":        "list",
                "zero_stock":      "zero_stock",
                "export_csv":      "export_csv",
                "export_excel":    "export_excel",
                "add_item":        "add_item",
                "delete_item":     "delete_item",
                "set_avg":         "set_avg",
                "set_unit":        "set_unit",
                "stock_adjust":    "stock_adjust",
                "undo":            "undo",
                "backup":          "backup",
                "reset_day":       "reset_day",
            }

            parsed_actions = []
            for a in actions:
                raw_action = a.get("action", "").lower().replace(" ", "_").replace("-", "_")
                action = action_map.get(raw_action, raw_action)

                parsed_actions.append(ParsedAction(
                    action=action,
                    item_name=a.get("item_name", ""),
                    quantity=float(a.get("quantity", 0) or 0),
                    unit=a.get("unit", ""),
                    purpose=a.get("purpose", ""),
                    destination=a.get("destination", ""),
                    raw_input=text,
                    confidence=float(a.get("confidence", 0.8) or 0.8),
                    extra={"avg_daily_usage": float(a.get("avg_daily_usage", 0) or 0)},
                ))

            return True, parsed_actions

        except Exception as e:
            return False, [str(e)]

    def parse_with_fallback(self, text: str) -> Tuple[bool, list]:
        text_lower = text.lower().strip()
        actions = []

        parts = re.split(r'\s+and\s+|\s*,\s*', text_lower)
        for part in parts:
            action = self._parse_single_action(part, text_lower)
            if action:
                actions.append(action)

        return len(actions) > 0, actions

    def _parse_single_action(self, text: str, full_text: str = "") -> Optional[ParsedAction]:
        text_lower = text.lower().strip()
        src = full_text or text_lower

        detected_action = None
        # Check longer/more-specific keywords first to avoid partial matches
        for action, keywords in sorted(MOVEMENT_KEYWORDS.items(), key=lambda x: -max(len(k) for k in x[1])):
            for kw in keywords:
                if kw in src:
                    detected_action = action
                    break
            if detected_action:
                break

        if not detected_action:
            return None

        # No quantity / no item needed
        if detected_action in NO_QTY_ACTIONS:
            item_name = ""
            if detected_action == "check":
                item_name = self._extract_item_name_simple(src, detected_action)
            return ParsedAction(
                action=detected_action,
                item_name=item_name,
                quantity=0, unit="", purpose="", destination="",
                raw_input=text, confidence=0.75,
            )

        # delete_item
        if detected_action == "delete_item":
            item_name = self._extract_item_name_for_delete(src)
            return ParsedAction(
                action="delete_item",
                item_name=item_name,
                quantity=0, unit="", purpose="", destination="",
                raw_input=text, confidence=0.85,
            )

        # add_item
        if detected_action == "add_item":
            return self._parse_add_item(src, text)

        # set_avg
        if detected_action == "set_avg":
            qty = self._extract_quantity(src)
            item = self._extract_item_name_simple(src, detected_action)
            return ParsedAction(
                action="set_avg",
                item_name=item, quantity=qty, unit="",
                purpose="", destination="",
                raw_input=text, confidence=0.75,
            )

        # set_unit
        if detected_action == "set_unit":
            unit = self._extract_unit(src)
            item = self._extract_item_name_simple(src, detected_action)
            return ParsedAction(
                action="set_unit",
                item_name=item, quantity=0, unit=unit,
                purpose="", destination="",
                raw_input=text, confidence=0.75,
            )

        # stock_adjust
        if detected_action == "stock_adjust":
            qty = self._extract_quantity(src)
            item = self._extract_item_name_simple(src, detected_action)
            return ParsedAction(
                action="stock_adjust",
                item_name=item, quantity=qty, unit="",
                purpose="", destination="",
                raw_input=text, confidence=0.75,
            )

        # undo / backup / reset_day
        if detected_action in ("undo", "backup", "reset_day"):
            return ParsedAction(
                action=detected_action,
                item_name="", quantity=0, unit="",
                purpose="", destination="",
                raw_input=text, confidence=0.8,
            )

        # --- Stock movements (need qty + item) ---
        quantity = self._extract_quantity(src)
        unit = self._extract_unit(src)
        item_name = self._extract_item_name(src, detected_action, quantity, unit)
        purpose = self._extract_purpose(src) if detected_action == "used" else ""
        destination = detected_action if detected_action in [
            "rajagiri main", "woods", "garden cafe", "bba canteen", "bba tea counter"
        ] else ""

        if detected_action == "check":
            return ParsedAction(
                action="check", item_name=item_name, quantity=0, unit=unit,
                purpose="", destination="", raw_input=text, confidence=0.7,
            )

        if not item_name or quantity <= 0:
            return None

        return ParsedAction(
            action=detected_action,
            item_name=item_name, quantity=quantity, unit=unit,
            purpose=purpose, destination=destination,
            raw_input=text, confidence=0.7,
        )

    def _parse_add_item(self, text: str, raw: str) -> Optional[ParsedAction]:
        """Extract add_item fields from natural language."""
        # Extract quantities — look for multiple numbers
        nums = re.findall(r'(\d+\.?\d*)', text)
        starting_stock = float(nums[0]) if nums else 0
        avg_daily_usage = float(nums[1]) if len(nums) > 1 else 0
        unit = self._extract_unit(text)

        # Guess item name — remove keywords, numbers, units, filler
        name = text
        for kw in MOVEMENT_KEYWORDS.get("add_item", []):
            name = name.replace(kw, "")
        name = re.sub(r'\d+\.?\d*', '', name)
        for u in UNITS:
            name = re.sub(rf'\b{u}\b', '', name)
        filler = r'\b(with|starting|current|stock|average|avg|use|usage|daily|a|an|the|and|for|of|in|kg|g|l|ml|pcs)\b'
        name = re.sub(filler, '', name).strip()

        return ParsedAction(
            action="add_item",
            item_name=name,
            quantity=starting_stock,
            unit=unit,
            purpose="",
            destination="",
            raw_input=raw,
            confidence=0.75,
            extra={"avg_daily_usage": avg_daily_usage},
        )

    def _extract_item_name_for_delete(self, text: str) -> str:
        for kw in MOVEMENT_KEYWORDS.get("delete_item", []):
            text = text.replace(kw, "")
        text = re.sub(r'\b(the|item|a|an|please|from|inventory)\b', '', text)
        return text.strip()

    def _extract_item_name_simple(self, text: str, action: str) -> str:
        """Simple extraction: strip keywords, numbers, units."""
        result = text
        for kw in MOVEMENT_KEYWORDS.get(action, []):
            result = result.replace(kw, "")
        result = re.sub(r'\d+\.?\d*', '', result)
        for u in UNITS:
            result = re.sub(rf'\b{u}\b', '', result)
        result = re.sub(r'\b(of|the|a|an|and|with|from|to)\b', '', result)
        return result.strip()

    def _extract_quantity(self, text: str) -> float:
        matches = re.findall(
            r'(\d+\.?\d*)\s*(?:kg|g|gram|grams|l|litre|liter|litres|ml|pcs|piece|pieces|packet|packets|box|boxes|bottle|bottles|tin|tins|can|cans)',
            text
        )
        if matches:
            return float(matches[0])
        matches = re.findall(r'(\d+\.?\d*)', text)
        if matches:
            return float(matches[0])
        return 0

    def _extract_unit(self, text: str) -> str:
        for unit in UNITS:
            if re.search(rf'\b{unit}\b', text):
                norm = {
                    "gram": "g", "grams": "g",
                    "litre": "L", "liter": "L", "litres": "L", "liters": "L",
                    "piece": "pcs", "pieces": "pcs",
                    "packet": "packet", "packets": "packet",
                    "box": "box", "boxes": "box",
                    "bottle": "bottle", "bottles": "bottle",
                    "tin": "tin", "tins": "tin",
                    "can": "can", "cans": "can",
                }
                return norm.get(unit, unit)
        return "pcs"

    def _extract_item_name(self, text: str, action: str, quantity: float, unit: str) -> str:
        text_clean = text
        for kw in MOVEMENT_KEYWORDS.get(action, []):
            text_clean = text_clean.replace(kw, "")
        if quantity:
            text_clean = re.sub(rf'{re.escape(str(int(quantity) if quantity == int(quantity) else quantity))}\s*{re.escape(unit)}', '', text_clean)
        text_clean = re.sub(r'\d+\.?\d*', '', text_clean)
        if action == "used":
            for p in [" for ", " to make ", " to prepare ", " in "]:
                if p in text_clean:
                    text_clean = text_clean.split(p, 1)[0]
                    break
        text_clean = re.sub(r'\b(kg|g|l|ml|pcs|of|the|a|an|and|with|from|to)\b', '', text_clean)
        return text_clean.strip()

    def _extract_purpose(self, text: str) -> str:
        for pk in ["for", "to make", "to prepare", "in"]:
            if pk in text:
                parts = text.split(pk, 1)
                if len(parts) > 1:
                    purpose = parts[1].strip()
                    return re.sub(r'[.,;!?].*', '', purpose).strip()
        return ""

    def parse(self, text: str) -> Tuple[bool, list]:
        if self.enabled:
            success, actions = self.parse_with_gemini(text)
            if success and actions:
                return True, actions
        return self.parse_with_fallback(text)

    def format_for_confirmation(self, actions: list) -> str:
        lines = ["*Please confirm these actions:*\n"]
        for i, action in enumerate(actions, 1):
            a = action.action
            if a in NO_QTY_ACTIONS:
                labels = {
                    "export_csv": "Export CSV", "export_excel": "Export Excel",
                    "daily_report": "Daily Report", "list": "List All Items",
                    "low_stock": "Show Low Stock", "order_list": "Show Order List",
                    "zero_stock": "Show Zero Stock", "undo": "Undo Last Action",
                    "backup": "Create Backup", "reset_day": "Reset Day",
                    "check": f"Check Stock: {action.item_name}",
                }
                lines.append(f"{i}. *{labels.get(a, a.title())}*")
            elif a == "delete_item":
                lines.append(f"{i}. *Delete Item*: {action.item_name} \u26a0\ufe0f")
            elif a == "add_item":
                avg = (action.extra or {}).get("avg_daily_usage", 0)
                lines.append(
                    f"{i}. *Add Item*: {action.item_name}\n"
                    f"   Starting stock: {action.quantity} {action.unit}\n"
                    f"   Avg daily use: {avg} {action.unit}"
                )
            elif a == "set_avg":
                lines.append(f"{i}. *Set Avg Usage*: {action.item_name} → {action.quantity}")
            elif a == "set_unit":
                lines.append(f"{i}. *Set Unit*: {action.item_name} → {action.unit}")
            elif a == "stock_adjust":
                lines.append(f"{i}. *Adjust Stock*: {action.item_name} → {action.quantity}")
            else:
                lines.append(
                    f"{i}. *{a.title()}*: {action.quantity} {action.unit} of {action.item_name}"
                )
                if action.purpose:
                    lines.append(f"   Purpose: {action.purpose}")
                if action.destination:
                    lines.append(f"   Destination: {action.destination.title()}")
        lines.append("\nReply with *yes* to confirm, or *no* to cancel.")
        return "\n".join(lines)


# Global AI service instance
ai_service = AIService()
