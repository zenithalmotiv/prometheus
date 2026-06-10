"""
AI Service for Prometheus.
Handles natural language understanding using Gemini API.
Uses direct httpx REST calls — no google-generativeai package needed.
"""

import json
import logging
import re
from typing import Optional, Tuple, List

import httpx

from app.config import config
from models import ParsedAction          # models package, not root models.py

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)

# ---------------------------------------------------------------------------
# Fallback rule-based keyword map
# ---------------------------------------------------------------------------
MOVEMENT_KEYWORDS = {
    "used":            ["used", "use", "consumed", "ate", "cooked", "took", "spent"],
    "purchased":       ["purchased", "bought", "buy", "ordered", "received", "got", "purchase"],
    "damaged":         ["damaged", "spoiled", "broken", "wasted", "rotten", "bad", "expired"],
    "wipro in":        ["wipro in", "wipro received", "received from wipro"],
    "wipro out":       ["wipro out", "sent to wipro", "wipro sent"],
    "rajagiri main":   ["rajagiri main", "sent to rajagiri", "rajagiri canteen", "rajagiri"],
    "woods":           ["woods", "sent to woods"],
    "garden cafe":     ["garden cafe", "sent to garden cafe", "garden"],
    "bba canteen":     ["bba canteen", "sent to bba canteen"],
    "bba tea counter": ["bba tea counter", "bba tea", "sent to bba tea"],
    "check":           ["check", "tell me about", "what is the stock", "how much", "stock of", "how many"],
    "low_stock":       ["low stock", "what to order", "what should i buy", "running low", "low items"],
    "order_list":      ["order list", "need to order", "items to order"],
    "daily_report":    ["daily report", "today report", "report", "today's report", "todays report"],
    "list":            [
        "list all", "show all", "inventory list", "all items", "item list",
        "list items", "give me the list", "show me the list", "show items", "show list",
    ],
    "zero_stock":      ["zero stock", "out of stock", "empty stock", "no stock"],
    "export_csv":      [
        "export csv", "give me csv", "download csv", "get csv", "csv export",
        "send csv", "export as csv", "give me the csv",
    ],
    "export_excel":    [
        "export excel", "give me excel", "download excel", "get excel", "excel export",
        "send excel", "export as excel", "give me the excel", "xlsx",
    ],
    "add_item":        ["add item", "new item", "add new item", "create item", "add a new", "add to inventory"],
    "delete_item":     ["delete", "remove", "delete item", "remove item", "get rid of", "drop item"],
    "set_avg":         ["set average", "set avg", "average usage", "avg usage", "daily usage"],
    "set_unit":        ["set unit", "change unit", "unit is"],
    "undo":            ["undo", "undo last", "revert", "take back", "cancel last"],
    "backup":          ["backup", "create backup", "make backup", "save backup"],
    "reset_day":       ["reset day", "reset today", "new day"],
    "stock_adjust":    [
        "adjust stock", "set stock to", "stock adjustment", "correct stock",
        "change stock to", "update stock",
    ],
}

UNITS = [
    "kg", "g", "gram", "grams", "l", "litre", "liter", "litres", "ml",
    "pcs", "piece", "pieces", "packet", "packets", "box", "boxes",
    "bottle", "bottles", "tin", "tins", "can", "cans",
]

# Actions that need no quantity (read-only or admin triggers)
NO_QTY_ACTIONS = frozenset({
    "check", "low_stock", "order_list", "daily_report", "list",
    "zero_stock", "export_csv", "export_excel", "undo", "backup", "reset_day",
})

ADD_ITEM_TRIGGERS = [
    "add item", "add new item", "new item", "create item", "add a new", "add to inventory",
]

# Map Gemini action strings -> internal action strings
ACTION_MAP = {
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


class AIService:

    def __init__(self):
        self.enabled = bool(config.GEMINI_API_KEY)
        if self.enabled:
            print("[Prometheus] Gemini AI enabled (gemini-2.0-flash, httpx REST).")
        else:
            print("[Prometheus] GEMINI_API_KEY not set — rule-based fallback only.")

    # ------------------------------------------------------------------
    # Gemini REST caller
    # ------------------------------------------------------------------

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
  add_item       - add a new item (item_name, unit, starting_stock, avg_daily_usage)
  delete_item    - delete an item (item_name)
  set_avg        - set average daily usage (item_name + quantity)
  set_unit       - set unit for an item (item_name + unit)
  stock_adjust   - set current stock to an exact value (item_name + quantity)

Admin:
  undo           - undo last action
  backup         - create a backup
  reset_day      - reset the day

RULES:
- For add_item: one action even if the sentence contains "and".
- For stock_adjust: quantity is the NEW absolute stock value.
- For set_avg: quantity is the new daily usage value.
- For check_stock: item_name is required.
- Multiple DIFFERENT items -> return an array of actions.
- NEVER return an empty actions array.

Respond ONLY with valid JSON (no markdown, no explanation):
{
    "actions": [
        {
            "action": "add_item",
            "item_name": "rice",
            "quantity": 150,
            "unit": "kg",
            "purpose": "",
            "destination": "",
            "avg_daily_usage": 40,
            "confidence": 0.95,
            "note": ""
        }
    ]
}
"""

    async def parse_with_gemini(self, text: str) -> Tuple[bool, List[ParsedAction]]:
        """Call Gemini via httpx and return parsed actions."""
        if not self.enabled:
            return False, []

        payload = {
            "contents": [{"parts": [{"text": self._build_system_prompt() + f"\n\nUser request: {text}"}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }

        try:
            logger.info(f"Sending to Gemini: {text!r}")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    GEMINI_URL,
                    params={"key": config.GEMINI_API_KEY},
                    json=payload,
                )

            if resp.status_code != 200:
                logger.error(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
                return False, []

            data = resp.json()
            raw_text = (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
            )
            logger.info(f"Gemini response: {raw_text[:300]}")

            # Strip optional markdown code fences
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            parsed_json = json.loads(raw_text)
            actions_raw = parsed_json.get("actions", [])

            parsed_actions: List[ParsedAction] = []
            for a in actions_raw:
                raw_action = a.get("action", "").lower().replace(" ", "_").replace("-", "_")
                action = ACTION_MAP.get(raw_action, raw_action)
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

            logger.info(f"Gemini parsed {len(parsed_actions)} action(s).")
            return bool(parsed_actions), parsed_actions

        except Exception as e:
            logger.error(f"Gemini parse error: {e}")
            return False, []

    # ------------------------------------------------------------------
    # Rule-based fallback parser
    # ------------------------------------------------------------------

    def parse_with_fallback(self, text: str) -> Tuple[bool, List[ParsedAction]]:
        logger.info(f"Fallback parser: {text!r}")
        text_lower = text.lower().strip()
        actions: List[ParsedAction] = []

        # add_item must be handled whole (not split on "and")
        if any(t in text_lower for t in ADD_ITEM_TRIGGERS):
            action = self._parse_single_action(text_lower, text_lower)
            return (True, [action]) if action else (False, [])

        # Split on " and " / "," for multi-item sentences
        parts = re.split(r'\s+and\s+|\s*,\s*', text_lower)
        for part in parts:
            action = self._parse_single_action(part, text_lower)
            if action:
                actions.append(action)

        return bool(actions), actions

    async def parse(self, text: str) -> Tuple[bool, List[ParsedAction]]:
        """Try Gemini first; fall back to rule-based parser on failure."""
        if self.enabled:
            success, actions = await self.parse_with_gemini(text)
            if success and actions:
                return True, actions
            logger.warning("Gemini failed or returned nothing — using fallback parser.")
        return self.parse_with_fallback(text)

    # ------------------------------------------------------------------
    # Rule-based helpers
    # ------------------------------------------------------------------

    def _parse_single_action(self, text: str, full_text: str = "") -> Optional[ParsedAction]:
        text_lower = text.lower().strip()
        src = full_text.lower() if full_text else text_lower

        # Detect action by longest keyword match first
        detected: Optional[str] = None
        for action, keywords in sorted(
            MOVEMENT_KEYWORDS.items(), key=lambda x: -max(len(k) for k in x[1])
        ):
            for kw in keywords:
                if kw in src:
                    detected = action
                    break
            if detected:
                break

        if not detected:
            return None

        # -- No-quantity actions --
        if detected in NO_QTY_ACTIONS:
            item_name = self._extract_item_name_simple(src, detected) if detected == "check" else ""
            return ParsedAction(
                action=detected, item_name=item_name,
                quantity=0, raw_input=text, confidence=0.75,
            )

        if detected == "delete_item":
            return ParsedAction(
                action="delete_item",
                item_name=self._extract_item_name_for_delete(src),
                quantity=0, raw_input=text, confidence=0.85,
            )

        if detected == "add_item":
            return self._parse_add_item(src, text)

        if detected == "set_avg":
            return ParsedAction(
                action="set_avg",
                item_name=self._extract_item_name_simple(src, detected),
                quantity=self._extract_quantity(src),
                raw_input=text, confidence=0.75,
            )

        if detected == "set_unit":
            return ParsedAction(
                action="set_unit",
                item_name=self._extract_item_name_simple(src, detected),
                quantity=0, unit=self._extract_unit(src),
                raw_input=text, confidence=0.75,
            )

        if detected == "stock_adjust":
            return ParsedAction(
                action="stock_adjust",
                item_name=self._extract_item_name_simple(src, detected),
                quantity=self._extract_quantity(src),
                raw_input=text, confidence=0.75,
            )

        if detected in ("undo", "backup", "reset_day"):
            return ParsedAction(
                action=detected, item_name="", quantity=0,
                raw_input=text, confidence=0.8,
            )

        # -- Movement actions --
        quantity  = self._extract_quantity(src)
        unit      = self._extract_unit(src)
        item_name = self._extract_item_name(src, detected, quantity, unit)
        purpose   = self._extract_purpose(src) if detected == "used" else ""
        destination = (
            detected
            if detected in {"rajagiri main", "woods", "garden cafe", "bba canteen", "bba tea counter"}
            else ""
        )

        if detected == "check":
            return ParsedAction(
                action="check", item_name=item_name, quantity=0,
                raw_input=text, confidence=0.7,
            )

        if not item_name or quantity <= 0:
            return None

        return ParsedAction(
            action=detected, item_name=item_name, quantity=quantity, unit=unit,
            purpose=purpose, destination=destination,
            raw_input=text, confidence=0.7,
        )

    def _parse_add_item(self, text: str, raw: str) -> Optional[ParsedAction]:
        unit = self._extract_unit(text)
        starting_stock = 0.0
        avg_daily_usage = 0.0

        stock_match = re.search(
            r'(?:starting|current|stock|with)\s+(?:stock\s+)?(?:of\s+)?(\d+\.?\d*)',
            text
        )
        stock_match2 = re.search(
            r'(\d+\.?\d*)\s*(?:' + '|'.join(UNITS) + r')?\s*(?:in\s+)?(?:starting|current)',
            text
        )
        if stock_match:
            starting_stock = float(stock_match.group(1))
        elif stock_match2:
            starting_stock = float(stock_match2.group(1))

        avg_match = re.search(
            r'(?:average|avg|average use|avg use|average usage|avg usage|use of|usage of)'
            r'\s+(?:of\s+)?(\d+\.?\d*)',
            text
        )
        if avg_match:
            avg_daily_usage = float(avg_match.group(1))

        if starting_stock == 0.0:
            nums = re.findall(r'(\d+\.?\d*)', text)
            if nums:
                starting_stock = float(nums[0])
            if avg_daily_usage == 0.0 and len(nums) > 1:
                avg_daily_usage = float(nums[1])

        name = text
        for kw in ADD_ITEM_TRIGGERS:
            name = name.replace(kw, "")
        name = re.sub(r'\d+\.?\d*', '', name)
        for u in UNITS:
            name = re.sub(rf'\b{re.escape(u)}\b', '', name)
        filler = (
            r'\b(with|starting|current|stock|average|avg|use|usage|daily|'
            r'a|an|the|and|for|of|in|as|unit|is|are|its|into|to)\b'
        )
        name = re.sub(filler, '', name).strip()
        name = re.sub(r'\s+', ' ', name).strip()

        if not name:
            return None

        return ParsedAction(
            action="add_item", item_name=name,
            quantity=starting_stock, unit=unit,
            raw_input=raw, confidence=0.80,
            extra={"avg_daily_usage": avg_daily_usage},
        )

    def _extract_item_name_for_delete(self, text: str) -> str:
        for kw in MOVEMENT_KEYWORDS.get("delete_item", []):
            text = text.replace(kw, "")
        return re.sub(r'\b(the|item|a|an|please|from|inventory)\b', '', text).strip()

    def _extract_item_name_simple(self, text: str, action: str) -> str:
        result = text
        for kw in MOVEMENT_KEYWORDS.get(action, []):
            result = result.replace(kw, "")
        result = re.sub(r'\d+\.?\d*', '', result)
        for u in UNITS:
            result = re.sub(rf'\b{re.escape(u)}\b', '', result)
        return re.sub(r'\b(of|the|a|an|and|with|from|to)\b', '', result).strip()

    def _extract_quantity(self, text: str) -> float:
        unit_pattern = '|'.join(re.escape(u) for u in UNITS)
        matches = re.findall(rf'(\d+\.?\d*)\s*(?:{unit_pattern})', text)
        if matches:
            return float(matches[0])
        plain = re.findall(r'(\d+\.?\d*)', text)
        return float(plain[0]) if plain else 0.0

    def _extract_unit(self, text: str) -> str:
        norm = {
            "gram": "g",   "grams": "g",
            "litre": "L",  "liter": "L", "litres": "L", "liters": "L", "l": "L",
            "piece": "pcs", "pieces": "pcs",
            "packet": "packet", "packets": "packet",
            "box": "box",   "boxes": "box",
            "bottle": "bottle", "bottles": "bottle",
            "tin": "tin",   "tins": "tin",
            "can": "can",   "cans": "can",
        }
        for unit in UNITS:
            if re.search(rf'\b{re.escape(unit)}\b', text):
                return norm.get(unit, unit)
        return "pcs"

    def _extract_item_name(self, text: str, action: str, quantity: float, unit: str) -> str:
        cleaned = text
        for kw in MOVEMENT_KEYWORDS.get(action, []):
            cleaned = cleaned.replace(kw, "")
        if quantity:
            qty_str = str(int(quantity)) if quantity == int(quantity) else str(quantity)
            cleaned = re.sub(rf'{re.escape(qty_str)}\s*{re.escape(unit)}', '', cleaned)
        cleaned = re.sub(r'\d+\.?\d*', '', cleaned)
        if action == "used":
            for sep in [" for ", " to make ", " to prepare ", " in "]:
                if sep in cleaned:
                    cleaned = cleaned.split(sep, 1)[0]
                    break
        cleaned = re.sub(r'\b(kg|g|l|ml|pcs|of|the|a|an|and|with|from|to)\b', '', cleaned)
        return cleaned.strip()

    def _extract_purpose(self, text: str) -> str:
        for pk in ["for", "to make", "to prepare", "in"]:
            if pk in text:
                parts = text.split(pk, 1)
                if len(parts) > 1:
                    purpose = parts[1].strip()
                    return re.sub(r'[.,;!?].*', '', purpose).strip()
        return ""

    # ------------------------------------------------------------------
    # Confirmation message formatter
    # ------------------------------------------------------------------

    def format_for_confirmation(self, actions: List[ParsedAction]) -> str:
        lines = ["Please confirm these actions:\n"]
        labels = {
            "export_csv":   "Export CSV",
            "export_excel": "Export Excel",
            "daily_report": "Daily Report",
            "list":         "List All Items",
            "low_stock":    "Show Low Stock",
            "order_list":   "Show Order List",
            "zero_stock":   "Show Zero Stock",
            "undo":         "Undo Last Action",
            "backup":       "Create Backup",
            "reset_day":    "Reset Day",
        }
        for i, action in enumerate(actions, 1):
            a = action.action
            if a == "check":
                lines.append(f"{i}. Check Stock: {action.item_name}")
            elif a in NO_QTY_ACTIONS:
                lines.append(f"{i}. {labels.get(a, a.title())}")
            elif a == "delete_item":
                lines.append(f"{i}. DELETE ITEM: {action.item_name} (cannot be undone!)")
            elif a == "add_item":
                avg = (action.extra or {}).get("avg_daily_usage", 0)
                lines.append(
                    f"{i}. Add Item: {action.item_name}\n"
                    f"   Starting stock: {action.quantity} {action.unit}\n"
                    f"   Avg daily use: {avg} {action.unit}"
                )
            elif a == "set_avg":
                lines.append(f"{i}. Set Avg Usage: {action.item_name} -> {action.quantity}")
            elif a == "set_unit":
                lines.append(f"{i}. Set Unit: {action.item_name} -> {action.unit}")
            elif a == "stock_adjust":
                lines.append(f"{i}. Adjust Stock: {action.item_name} -> {action.quantity}")
            else:
                lines.append(
                    f"{i}. {a.title()}: {action.quantity} {action.unit} of {action.item_name}"
                )
                if action.purpose:
                    lines.append(f"   Purpose: {action.purpose}")
                if action.destination:
                    lines.append(f"   Destination: {action.destination.title()}")
        lines.append("\nReply YES to confirm, or NO to cancel.")
        return "\n".join(lines)


ai_service = AIService()
