"""
Utility helpers for Prometheus.
"""

import re
from typing import Optional


def parse_quantity_unit(text: str) -> tuple[float, str, str]:
    """
    Parse quantity and unit from text.
    Returns (quantity, unit, remaining_text).
    Example: "5 kg rice" -> (5.0, "kg", "rice")
    """
    units = ["kg", "g", "gram", "grams", "l", "litre", "liter", "litres", "ml",
             "pcs", "piece", "pieces", "packet", "packets", "box", "boxes",
             "bottle", "bottles", "tin", "tins", "can", "cans"]

    # Normalize
    text = text.lower().strip()

    # Try to match number + unit pattern
    pattern = r'(\d+\.?\d*)\s*(' + '|'.join(units) + r')\b'
    match = re.search(pattern, text)

    if match:
        qty = float(match.group(1))
        unit = match.group(2)
        # Normalize unit
        unit = normalize_unit(unit)
        remaining = text[:match.start()].strip() + " " + text[match.end():].strip()
        remaining = remaining.strip()
        return qty, unit, remaining

    # Try just number
    num_match = re.search(r'(\d+\.?\d*)', text)
    if num_match:
        qty = float(num_match.group(1))
        remaining = text[:num_match.start()].strip() + " " + text[num_match.end():].strip()
        remaining = remaining.strip()
        return qty, "pcs", remaining

    return 0, "pcs", text


def normalize_unit(unit: str) -> str:
    """Normalize unit to standard form."""
    unit = unit.lower().strip()
    mapping = {
        "gram": "g",
        "grams": "g",
        "litre": "L",
        "litres": "L",
        "liter": "L",
        "liters": "L",
        "l": "L",
        "piece": "pcs",
        "pieces": "pcs",
        "packet": "packet",
        "packets": "packet",
        "box": "box",
        "boxes": "box",
        "bottle": "bottle",
        "bottles": "bottle",
        "tin": "tin",
        "tins": "tin",
        "can": "can",
        "cans": "can",
    }
    return mapping.get(unit, unit)


def sanitize_item_id(name: str) -> str:
    """Create a safe item ID from a name."""
    safe = re.sub(r'[^a-zA-Z0-9]', '_', name.lower().strip())
    safe = re.sub(r'_+', '_', safe)
    safe = safe.strip('_')
    return safe[:20]


def format_stock_line(item: dict) -> str:
    """Format an item as a stock line."""
    avg = item.get("avg_daily_usage", 0) or 0
    current = item.get("current_stock", 0) or 0
    if avg > 0:
        days = current / avg
        days_str = f"({days:.1f}d)"
    else:
        days_str = ""

    return (
        f"{item.get('item_name', 'Unknown')} "
        f"[{item.get('item_id', '')}]: "
        f"{current} {item.get('unit', 'pcs')} {days_str}"
    )


def truncate_text(text: str, max_length: int = 4000) -> str:
    """Truncate text to fit Telegram message limits."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 20] + "\n...(truncated)"


def parse_csv_line(line: str) -> dict:
    """Parse a CSV-formatted line into a dict."""
    import csv
    import io
    reader = csv.DictReader(io.StringIO(line))
    rows = list(reader)
    return rows[0] if rows else {}
