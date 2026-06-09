"""
Inventory service layer.
Business logic and orchestration between handlers and database.
"""

import csv
import io
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from db.database import (
    add_item as db_add_item,
    get_item_by_id, get_item_by_name, find_items_by_name_partial,
    list_all_items, update_item, delete_item, delete_all_items,
    perform_stock_movement, list_items_by_section,
    get_low_stock_items, get_order_list, get_zero_stock_items,
    get_daily_report,
    add_purpose, remove_purpose, list_purposes,
    undo_last_action, reset_day,
    create_backup, list_backups, restore_backup,
    export_to_csv, export_to_excel, bulk_import_items,
    get_setting, set_setting, get_secret_word, set_secret_word, verify_secret_word,
    get_working_date, set_working_date,
)


# --- Item Management ---

def add_single_item(
    item_id: str,
    item_name: str,
    unit: str = "pcs",
    starting_stock: float = 0,
    current_stock: float = 0,
    avg_daily_usage: float = 0,
    location: str = "",
    category: str = "",
) -> Tuple[bool, str]:
    """Add a single item."""
    return db_add_item(
        item_id=item_id,
        item_name=item_name,
        unit=unit,
        starting_stock=starting_stock,
        current_stock=current_stock,
        avg_daily_usage=avg_daily_usage,
        location=location,
        category=category,
    )


def add_multiple_items(items_list: List[Dict[str, Any]]) -> Tuple[int, int, List[str]]:
    """Add multiple items."""
    return bulk_import_items(items_list)


def parse_csv_import(csv_content: str) -> Tuple[int, int, List[str]]:
    """Parse CSV string and import items."""
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        items = list(reader)
        return bulk_import_items(items)
    except Exception as e:
        return 0, 0, [f"CSV parse error: {str(e)}"]


def set_avg_usage(item_id: str, avg_usage: float) -> Tuple[bool, str]:
    """Set average daily usage for an item."""
    return update_item(item_id, {"avg_daily_usage": avg_usage})


def set_unit(item_id: str, unit: str) -> Tuple[bool, str]:
    """Set unit for an item."""
    return update_item(item_id, {"unit": unit})


def edit_item_details(
    item_id: str,
    item_name: Optional[str] = None,
    location: Optional[str] = None,
    category: Optional[str] = None,
) -> Tuple[bool, str]:
    """Edit item metadata."""
    updates = {}
    if item_name is not None:
        updates["item_name"] = item_name
    if location is not None:
        updates["location"] = location
    if category is not None:
        updates["category"] = category
    return update_item(item_id, updates)


def delete_single_item(item_id: str) -> Tuple[bool, str]:
    """Delete a single item."""
    return delete_item(item_id)


def delete_all() -> Tuple[bool, str]:
    """Delete all items."""
    return delete_all_items()


# --- Stock Movements ---

def process_stock_movement(
    item_id: str,
    action: str,
    quantity: float,
    purpose: str = "",
    destination: str = "",
    performed_by: str = "",
) -> Tuple[bool, str, Optional[int]]:
    """Process a stock movement action."""
    return perform_stock_movement(
        item_id=item_id,
        action=action,
        quantity=quantity,
        purpose=purpose,
        destination=destination,
        performed_by=performed_by,
    )


def adjust_stock(item_id: str, new_stock: float, performed_by: str = "") -> Tuple[bool, str, Optional[int]]:
    """Direct stock adjustment."""
    return perform_stock_movement(
        item_id=item_id,
        action="stock adjustment",
        quantity=new_stock,
        performed_by=performed_by,
    )


def change_starting_stock(item_id: str, value: float) -> Tuple[bool, str, Optional[int]]:
    """Change starting stock directly."""
    return perform_stock_movement(
        item_id=item_id,
        action="change starting stock",
        quantity=value,
    )


def change_current_stock(item_id: str, value: float) -> Tuple[bool, str, Optional[int]]:
    """Change current stock directly."""
    return perform_stock_movement(
        item_id=item_id,
        action="change current stock",
        quantity=value,
    )


# --- Queries ---

def find_item(identifier: str) -> Optional[Dict[str, Any]]:
    """Find item by ID or name."""
    item = get_item_by_id(identifier)
    if item:
        return item
    item = get_item_by_name(identifier)
    if item:
        return item
    # Try partial match - return first match
    matches = find_items_by_name_partial(identifier)
    return matches[0] if matches else None


def find_items(identifier: str) -> List[Dict[str, Any]]:
    """Find items by partial name match."""
    return find_items_by_name_partial(identifier)


def get_all_items() -> List[Dict[str, Any]]:
    """Get all items."""
    return list_all_items()


def get_items_by_section(section: str) -> List[Dict[str, Any]]:
    """Get items by section/destination."""
    return list_items_by_section(section)


def check_stock(item_id: str) -> Tuple[bool, str]:
    """Check stock for an item."""
    item = find_item(item_id)
    if not item:
        return False, f"Item '{item_id}' not found."

    avg = item["avg_daily_usage"] or 0
    current = item["current_stock"] or 0
    if avg > 0:
        days_left = current / avg
        status = f"{round(days_left, 1)} days left"
        if days_left <= 3:
            status += " (LOW)"
    else:
        status = "N/A (no usage data)"

    msg = (
        f"*{item['item_name']}* ({item['item_id']})\n"
        f"Current Stock: {current} {item['unit']}\n"
        f"Starting Stock: {item['starting_stock']} {item['unit']}\n"
        f"Avg Daily Usage: {avg} {item['unit']}\n"
        f"Days Left: {status}\n"
        f"Location: {item['location'] or 'N/A'}\n"
        f"Category: {item['category'] or 'N/A'}"
    )
    return True, msg


def get_low_stock() -> List[Dict[str, Any]]:
    """Get low stock items."""
    return get_low_stock_items()


def get_order() -> List[Dict[str, Any]]:
    """Get order list."""
    return get_order_list()


def get_zero_stock() -> List[Dict[str, Any]]:
    """Get zero stock items."""
    return get_zero_stock_items()


def generate_daily_report() -> Dict[str, Any]:
    """Generate daily report."""
    return get_daily_report()


# --- Purposes ---

def get_all_purposes() -> List[str]:
    """Get all purposes."""
    return list_purposes()


def create_purpose(name: str) -> Tuple[bool, str]:
    """Create a new purpose."""
    return add_purpose(name)


def delete_purpose(name: str) -> Tuple[bool, str]:
    """Delete a purpose."""
    return remove_purpose(name)


# --- Access Control ---

def check_secret_word(word: str) -> bool:
    """Check if the secret word is correct."""
    return verify_secret_word(word)


def change_secret_word(new_word: str) -> None:
    """Change the secret word."""
    set_secret_word(new_word)


def get_current_secret_word() -> str:
    """Get current secret word (for admin use)."""
    return get_secret_word()


# --- Undo ---

def undo_action(performed_by: str = "") -> Tuple[bool, str]:
    """Undo last action."""
    return undo_last_action(performed_by)


# --- Reset Day ---

def do_reset_day(performed_by: str = "") -> Tuple[bool, str]:
    """Reset the day."""
    return reset_day(performed_by)


# --- Backup ---

def do_backup(note: str = "") -> Tuple[bool, str, Optional[str]]:
    """Create a backup."""
    return create_backup(note)


def get_backups() -> List[Dict[str, Any]]:
    """List backups."""
    return list_backups()


def do_restore(backup_path: str) -> Tuple[bool, str]:
    """Restore from backup."""
    return restore_backup(backup_path)


# --- Export ---

def do_export_csv() -> Tuple[bool, str, Optional[str]]:
    """Export to CSV."""
    return export_to_csv()


def do_export_excel() -> Tuple[bool, str, Optional[str]]:
    """Export to Excel."""
    return export_to_excel()
