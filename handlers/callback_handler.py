"""
Callback Query Handler for Prometheus.
Handles all inline button interactions.
"""

import csv
import io
from typing import Dict, Any, Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.config import config
from services.inventory_service import (
    add_single_item, delete_single_item, delete_all,
    set_avg_usage, set_unit, edit_item_details,
    process_stock_movement, adjust_stock,
    change_starting_stock, change_current_stock,
    find_item, get_all_items, check_stock,
    get_low_stock, get_order, get_zero_stock,
    get_items_by_section, generate_daily_report,
    get_all_purposes, create_purpose, delete_purpose,
    undo_action, do_reset_day,
    do_backup, get_backups, do_restore,
    do_export_csv, do_export_excel,
    parse_csv_import, check_secret_word, change_secret_word,
    get_current_secret_word,
)
from services.ai_service import ai_service, ParsedAction, NO_QTY_ACTIONS
from db.database import get_working_date

# ---------------------------------------------------------------------------
# In-memory user session store
# ---------------------------------------------------------------------------
# NOTE: sessions are lost on bot restart. Users will need to /unlock again.
# This is acceptable for a single-instance canteen bot. A future improvement
# would persist unlock state in the database.
user_sessions: Dict[int, Dict[str, Any]] = {}


def get_session(user_id: int) -> Dict[str, Any]:
    """Get or create user session."""
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "locked": True,
            "pending_actions": [],
            "temp_data": {},
        }
    return user_sessions[user_id]


def is_unlocked(user_id: int) -> bool:
    return not get_session(user_id)["locked"]


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Movement", callback_data="menu_movement")],
        [InlineKeyboardButton("Reports",      callback_data="menu_reports")],
        [InlineKeyboardButton("Inventory",    callback_data="menu_inventory")],
        [InlineKeyboardButton("Admin",        callback_data="menu_admin")],
    ])


def movement_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Used",         callback_data="mov_used"),
         InlineKeyboardButton("Purchased",    callback_data="mov_purchased")],
        [InlineKeyboardButton("Damaged",      callback_data="mov_damaged"),
         InlineKeyboardButton("Wipro In",     callback_data="mov_wipro_in")],
        [InlineKeyboardButton("Wipro Out",    callback_data="mov_wipro_out")],
        [InlineKeyboardButton("Rajagiri Main",callback_data="mov_rajagiri_main"),
         InlineKeyboardButton("Woods",        callback_data="mov_woods")],
        [InlineKeyboardButton("Garden Cafe",  callback_data="mov_garden_cafe"),
         InlineKeyboardButton("BBA Canteen",  callback_data="mov_bba_canteen")],
        [InlineKeyboardButton("BBA Tea Counter", callback_data="mov_bba_tea_counter")],
        [InlineKeyboardButton("Stock Adjustment", callback_data="mov_adjustment")],
        [InlineKeyboardButton("Back",         callback_data="menu_main")],
    ])


def reports_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check Stock",    callback_data="rep_check")],
        [InlineKeyboardButton("Low Stock",      callback_data="rep_low")],
        [InlineKeyboardButton("Order List",     callback_data="rep_order")],
        [InlineKeyboardButton("Daily Report",   callback_data="rep_daily")],
        [InlineKeyboardButton("List All Items", callback_data="rep_list")],
        [InlineKeyboardButton("Zero Stock",     callback_data="rep_zero")],
        [InlineKeyboardButton("List by Section",callback_data="rep_section")],
        [InlineKeyboardButton("Back",           callback_data="menu_main")],
    ])


def inventory_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Item",         callback_data="inv_add")],
        [InlineKeyboardButton("Add Multiple",     callback_data="inv_add_multi")],
        [InlineKeyboardButton("Bulk Import (CSV)",callback_data="inv_bulk")],
        [InlineKeyboardButton("Edit Item",        callback_data="inv_edit")],
        [InlineKeyboardButton("Delete Item",      callback_data="inv_delete")],
        [InlineKeyboardButton("Set Avg Usage",    callback_data="inv_avg")],
        [InlineKeyboardButton("Set Unit",         callback_data="inv_unit")],
        [InlineKeyboardButton("Manage Purposes",  callback_data="inv_purposes")],
        [InlineKeyboardButton("Back",             callback_data="menu_main")],
    ])


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Lock Bot",         callback_data="adm_lock")],
        [InlineKeyboardButton("Reset Day",        callback_data="adm_reset")],
        [InlineKeyboardButton("Undo Last Action", callback_data="adm_undo")],
        [InlineKeyboardButton("Backup",           callback_data="adm_backup")],
        [InlineKeyboardButton("Restore",          callback_data="adm_restore")],
        [InlineKeyboardButton("Export CSV",       callback_data="adm_csv")],
        [InlineKeyboardButton("Export Excel",     callback_data="adm_excel")],
        [InlineKeyboardButton("Change Secret",    callback_data="adm_secret")],
        [InlineKeyboardButton("Delete All Items", callback_data="adm_delete_all")],
        [InlineKeyboardButton("Back",             callback_data="menu_main")],
    ])


def section_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Rajagiri Main",   callback_data="sec_rajagiri main")],
        [InlineKeyboardButton("Woods",           callback_data="sec_woods")],
        [InlineKeyboardButton("Garden Cafe",     callback_data="sec_garden cafe")],
        [InlineKeyboardButton("BBA Canteen",     callback_data="sec_bba canteen")],
        [InlineKeyboardButton("BBA Tea Counter", callback_data="sec_bba tea counter")],
        [InlineKeyboardButton("Back",            callback_data="menu_reports")],
    ])


def purposes_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("List Purposes",  callback_data="pur_list")],
        [InlineKeyboardButton("Add Purpose",    callback_data="pur_add")],
        [InlineKeyboardButton("Remove Purpose", callback_data="pur_remove")],
        [InlineKeyboardButton("Back",           callback_data="menu_inventory")],
    ])


def yes_no_keyboard(cb_yes: str, cb_no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes", callback_data=cb_yes),
        InlineKeyboardButton("No",  callback_data=cb_no),
    ]])


def item_select_keyboard(items: list, callback_prefix: str) -> InlineKeyboardMarkup:
    """
    Build an item-selection keyboard.
    callback_prefix must be short enough that prefix + item_id stays <= 64 bytes.
    Use prefixes like "si_" (sel item), "di_" (del item), "ei_" (edit), etc.
    """
    keyboard = []
    for item in items:
        btn_text = f"{item['item_name']} ({item['current_stock']} {item['unit']})"
        cb = f"{callback_prefix}{item['item_id']}"
        # Telegram limit: 64 bytes. Silently truncate if somehow exceeded.
        if len(cb.encode()) > 64:
            cb = cb.encode()[:64].decode(errors="ignore")
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb)])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="menu_main")])
    return InlineKeyboardMarkup(keyboard)


def _backup_select_keyboard(backups: List[Dict]) -> InlineKeyboardMarkup:
    """
    Build backup selection keyboard using index numbers (not file paths) in
    callback_data so we never exceed the 64-byte limit.
    Stores the full paths in the session instead.
    """
    keyboard = []
    for idx, b in enumerate(backups[:10]):
        fname = b["filename"]
        short = fname.split("/")[-1]          # just the filename
        if len(short) > 40:
            short = "\u2026" + short[-37:]
        keyboard.append([
            InlineKeyboardButton(short, callback_data=f"bksel_{idx}")
        ])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="menu_admin")])
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------------
# Main callback dispatcher
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    data     = query.data
    user_id  = update.effective_user.id
    session  = get_session(user_id)

    # -- Navigation --
    if data == "menu_main":
        await query.edit_message_text(
            "*Prometheus Main Menu*", reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
    elif data == "menu_movement":
        await query.edit_message_text(
            "*Add Movement* \u2014 Select action:", reply_markup=movement_menu_keyboard(),
            parse_mode="Markdown"
        )
    elif data == "menu_reports":
        await query.edit_message_text(
            "*Reports* \u2014 Select report:", reply_markup=reports_menu_keyboard(),
            parse_mode="Markdown"
        )
    elif data == "menu_inventory":
        await query.edit_message_text(
            "*Inventory Management*", reply_markup=inventory_menu_keyboard(),
            parse_mode="Markdown"
        )
    elif data == "menu_admin":
        await query.edit_message_text(
            "*Admin Panel*", reply_markup=admin_menu_keyboard(),
            parse_mode="Markdown"
        )

    # -- Movement selection --
    elif data.startswith("mov_"):
        action = data[len("mov_"):]
        session["temp_data"] = {"action": action}

        if action == "adjustment":
            await query.edit_message_text(
                "Enter item name/ID and the new stock value.\n"
                "Format: <item> <new_stock>\nExample: rice 100"
            )
            context.user_data["awaiting"] = "adjustment"
        else:
            await query.edit_message_text(
                f"{action.replace('_', ' ').title()} \u2014 Enter item name or ID:"
            )
            context.user_data["awaiting"] = "movement_item"

    # -- Reports --
    # IMPORTANT: rep_section must be checked BEFORE the generic rep_ branch
    elif data == "rep_section":
        await query.edit_message_text(
            "List by Section \u2014 Select section:",
            reply_markup=section_menu_keyboard()
        )
    elif data.startswith("rep_"):
        await _handle_report_callback(update, context, data)

    # -- Section items --
    elif data.startswith("sec_"):
        section = data[len("sec_"):]
        items   = get_items_by_section(section)
        if items:
            col_key = section.replace(" ", "_")
            lines   = [f"{section.title()} \u2014 Items:"]
            for item in items:
                qty = item.get(col_key, 0)
                lines.append(f"- {item['item_name']}: {qty} {item['unit']}")
            await query.edit_message_text(
                "\n".join(lines), reply_markup=section_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                f"No items found for {section.title()}.",
                reply_markup=section_menu_keyboard()
            )

    # -- Inventory management --
    elif data.startswith("inv_"):
        await _handle_inventory_callback(update, context, data)

    # -- Purposes --
    elif data.startswith("pur_"):
        await _handle_purpose_callback(update, context, data)

    # -- Admin --
    elif (
        data.startswith("adm_")
        or data in ("delall_confirm", "reset_confirm")
        or data.startswith("bksel_")
        or data.startswith("bkconf_")
    ):
        await _handle_admin_callback(update, context, data)

    # -- AI confirmation --
    elif data == "ai_confirm_yes":
        await _execute_pending_actions(update, context)
    elif data == "ai_confirm_no":
        session["pending_actions"] = []
        await query.edit_message_text("Action cancelled.", reply_markup=main_menu_keyboard())

    # -- Delete item confirmation --
    # Prefix "dc_" = "del confirm" (short, won't exceed 64 bytes for any item_id)
    elif data.startswith("dc_"):
        item_id = data[len("dc_"):]
        ok, msg = delete_single_item(item_id)
        await query.edit_message_text(msg, reply_markup=inventory_menu_keyboard())

    # -- Item selected from list (movement flow) --
    elif data.startswith("si_"):     # si = select item
        await _handle_item_selected(update, context, data[len("si_"):])

    # -- Purpose selected for "used" action --
    elif data.startswith("ps_"):     # ps = purpose select
        await _handle_purpose_selected(update, context, data[len("ps_"):])

    # -- Item action callbacks (edit / avg / unit) --
    elif data.startswith("ei_"):     # ei = edit item
        await _handle_edit_item_cb(update, context, data[len("ei_"):])
    elif data.startswith("di_"):     # di = delete item (show confirm)
        await _handle_delete_item_cb(update, context, data[len("di_"):])
    elif data.startswith("ai_"):     # ai = avg item  (NOT ai_confirm — handled above)
        if not data.startswith("ai_confirm"):
            await _handle_avg_item_cb(update, context, data[len("ai_"):])
    elif data.startswith("ui_"):     # ui = unit item
        await _handle_unit_item_cb(update, context, data[len("ui_"):])

    else:
        await query.edit_message_text(
            "Unknown action. Please use /menu.", reply_markup=main_menu_keyboard()
        )


# ---------------------------------------------------------------------------
# Report sub-handler
# ---------------------------------------------------------------------------

async def _handle_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query  = update.callback_query
    action = data[len("rep_"):]

    if action == "check":
        await query.edit_message_text("Enter item name or ID to check stock:")
        context.user_data["awaiting"] = "check_stock"

    elif action == "low":
        items = get_low_stock()
        if items:
            lines = ["Low Stock Items:\n"]
            for item in items:
                status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
                lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3990] + "...(truncated)"
        else:
            msg = "No low stock items."
        await query.edit_message_text(msg)

    elif action == "order":
        items = get_order()
        if items:
            lines = ["Order List:\n"]
            for item in items:
                status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
                lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3990] + "...(truncated)"
        else:
            msg = "No items need ordering."
        await query.edit_message_text(msg)

    elif action == "daily":
        report = generate_daily_report()
        lines  = [f"Daily Report \u2014 {report['date']}\n"]
        for section, label in [
            ("used_items",      "Used"),
            ("purchased_items", "Purchased"),
            ("damaged_items",   "Damaged"),
            ("wipro_in",        "Wipro In"),
            ("wipro_out",       "Wipro Out"),
            ("transfers",       "Transfers"),
            ("adjustments",     "Adjustments"),
        ]:
            if report.get(section):
                lines.append(f"\n{label}:")
                for t in report[section]:
                    lines.append(f"  - {t['item_name']}: {t.get('quantity', '')} {t.get('unit', '')}")
        if report.get("low_stock"):
            lines.append("\nLow Stock:")
            for item in report["low_stock"]:
                lines.append(f"  - {item['item_name']}: {item['current_stock']} {item['unit']}")
        lines.append(f"\nTotal transactions: {report['total_transactions']}")
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:3990] + "...(truncated)"
        await query.edit_message_text(msg)

    elif action == "list":
        items = get_all_items()
        if items:
            lines = [f"All Items ({len(items)}):\n"]
            for item in items:
                lines.append(f"- {item['item_name']} ({item['item_id']}): {item['current_stock']} {item['unit']}")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3990] + "...(truncated)"
            await query.edit_message_text(msg)
        else:
            await query.edit_message_text("No items in inventory.")

    elif action == "zero":
        items = get_zero_stock()
        if items:
            lines = ["Zero Stock Items:\n"]
            for item in items:
                lines.append(f"- {item['item_name']} ({item['item_id']})")
            await query.edit_message_text("\n".join(lines))
        else:
            await query.edit_message_text("No zero stock items.")


# ---------------------------------------------------------------------------
# Inventory sub-handlers
# ---------------------------------------------------------------------------

async def _handle_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query  = update.callback_query
    action = data[len("inv_"):]

    if action == "add":
        await query.edit_message_text(
            "Add Item \u2014 Send details:\n"
            "Name | unit | starting_stock | avg_usage\n"
            "Example: Rice | kg | 150 | 40\n\n"
            "Or with custom ID:\n"
            "ID | name | unit | stock | current | avg\n"
            "Example: R001 | Rice | kg | 150 | 150 | 40"
        )
        context.user_data["awaiting"] = "add_item"

    elif action == "add_multi":
        await query.edit_message_text(
            "Add Multiple Items \u2014 one per line:\n"
            "Name | unit | starting_stock | avg_usage\n"
            "Example:\nRice | kg | 150 | 40\nSugar | kg | 50 | 20"
        )
        context.user_data["awaiting"] = "add_multi"

    elif action == "bulk":
        await query.edit_message_text(
            "Bulk Import \u2014 paste CSV or send a .csv file.\n"
            "Required columns: item_id, item_name, unit\n"
            "Optional: starting_stock, current_stock, avg_daily_usage, location, category"
        )
        context.user_data["awaiting"] = "bulk_import"

    elif action == "edit":
        items = get_all_items()
        if items:
            await query.edit_message_text(
                "Select item to edit:", reply_markup=item_select_keyboard(items[:20], "ei_")
            )
        else:
            await query.edit_message_text("No items to edit.")

    elif action == "delete":
        items = get_all_items()
        if items:
            await query.edit_message_text(
                "Select item to delete:", reply_markup=item_select_keyboard(items[:20], "di_")
            )
        else:
            await query.edit_message_text("No items to delete.")

    elif action == "avg":
        items = get_all_items()
        if items:
            await query.edit_message_text(
                "Select item to set average usage:",
                reply_markup=item_select_keyboard(items[:20], "ai_item_")
            )
        else:
            await query.edit_message_text("No items available.")

    elif action == "unit":
        items = get_all_items()
        if items:
            await query.edit_message_text(
                "Select item to change unit:",
                reply_markup=item_select_keyboard(items[:20], "ui_")
            )
        else:
            await query.edit_message_text("No items available.")

    elif action == "purposes":
        await query.edit_message_text("Manage Purposes", reply_markup=purposes_menu_keyboard())


async def _handle_edit_item_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    query   = update.callback_query
    session = get_session(update.effective_user.id)
    session["temp_data"]["edit_item_id"] = item_id
    await query.edit_message_text(
        f"Editing {item_id}.\n"
        "Send: name | location | category\n"
        "Or: name: New Name"
    )
    context.user_data["awaiting"] = "edit_item"


async def _handle_delete_item_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    query     = update.callback_query
    item      = find_item(item_id)
    item_name = item["item_name"] if item else item_id
    await query.edit_message_text(
        f"Delete '{item_name}'? This cannot be undone.",
        reply_markup=yes_no_keyboard(f"dc_{item_id}", "menu_inventory")
    )


async def _handle_avg_item_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    query   = update.callback_query
    # Trim the "item_" prefix added by item_select_keyboard prefix "ai_item_"
    if item_id.startswith("item_"):
        item_id = item_id[len("item_"):]
    session = get_session(update.effective_user.id)
    session["temp_data"]["avg_item_id"] = item_id
    await query.edit_message_text(
        f"Enter average daily usage for {item_id}:\n(in the item's unit per day)"
    )
    context.user_data["awaiting"] = "set_avg"


async def _handle_unit_item_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    query   = update.callback_query
    session = get_session(update.effective_user.id)
    session["temp_data"]["unit_item_id"] = item_id
    await query.edit_message_text(
        f"Enter new unit for {item_id}:\n(kg, g, L, ml, pcs, packet, etc.)"
    )
    context.user_data["awaiting"] = "set_unit"


# ---------------------------------------------------------------------------
# Item selection flow (movement)
# ---------------------------------------------------------------------------

async def _handle_item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    query   = update.callback_query
    session = get_session(update.effective_user.id)
    session["temp_data"]["item_id"] = item_id
    action  = session["temp_data"].get("action", "")

    if action == "used":
        purposes = get_all_purposes()
        kb: List = []
        row: List = []
        for i, p in enumerate(purposes):
            row.append(InlineKeyboardButton(p.title(), callback_data=f"ps_{p}"))
            if (i + 1) % 2 == 0:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("Custom Purpose", callback_data="ps_custom")])
        kb.append([InlineKeyboardButton("Cancel", callback_data="menu_main")])
        await query.edit_message_text(
            "Select purpose for Used action:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await query.edit_message_text(
            f"Enter quantity for {action.replace('_', ' ').title()}:\n(Item: {item_id})"
        )
        context.user_data["awaiting"] = "movement_qty"


async def _handle_purpose_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, purpose: str):
    query   = update.callback_query
    session = get_session(update.effective_user.id)
    session["temp_data"]["purpose"] = purpose

    if purpose == "custom":
        await query.edit_message_text("Enter custom purpose:")
        context.user_data["awaiting"] = "custom_purpose"
    else:
        await query.edit_message_text(
            f"Enter quantity for Used:\nPurpose: {purpose.title()}"
        )
        context.user_data["awaiting"] = "movement_qty"


# ---------------------------------------------------------------------------
# Purpose management
# ---------------------------------------------------------------------------

async def _handle_purpose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query  = update.callback_query

    if data == "pur_list":
        purposes = get_all_purposes()
        if purposes:
            await query.edit_message_text(
                "Available Purposes:\n" + "\n".join(f"- {p.title()}" for p in purposes),
                reply_markup=purposes_menu_keyboard()
            )
        else:
            await query.edit_message_text("No purposes defined.", reply_markup=purposes_menu_keyboard())

    elif data == "pur_add":
        await query.edit_message_text("Enter new purpose name:")
        context.user_data["awaiting"] = "add_purpose"

    elif data == "pur_remove":
        purposes = get_all_purposes()
        if purposes:
            kb = [[InlineKeyboardButton(p.title(), callback_data=f"purdel_{p}")] for p in purposes]
            kb.append([InlineKeyboardButton("Cancel", callback_data="menu_inventory")])
            await query.edit_message_text("Select purpose to remove:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text("No purposes to remove.")

    elif data.startswith("purdel_"):
        purpose = data[len("purdel_"):]
        ok, msg = delete_purpose(purpose)
        await query.edit_message_text(msg, reply_markup=purposes_menu_keyboard())


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query   = update.callback_query
    user_id = update.effective_user.id
    session = get_session(user_id)

    if data == "adm_lock":
        session["locked"] = True
        await query.edit_message_text("Bot is now LOCKED. Send /unlock <secret> to access.")

    elif data == "adm_reset":
        await query.edit_message_text(
            "Reset Day \u2014 carries current stock as starting stock and resets all counters.\nAre you sure?",
            reply_markup=yes_no_keyboard("reset_confirm", "menu_admin")
        )

    elif data == "adm_undo":
        ok, msg = undo_action(str(user_id))
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())

    elif data == "adm_backup":
        ok, msg, filepath = do_backup()
        text = f"{msg}\nSaved to: {filepath}" if ok else msg
        await query.edit_message_text(text, reply_markup=admin_menu_keyboard())

    elif data == "adm_restore":
        backups = get_backups()
        if backups:
            # Store full paths in session; use index in callback_data (avoids 64-byte limit)
            session["temp_data"]["backup_list"] = [b["filename"] for b in backups[:10]]
            await query.edit_message_text(
                "Select backup to restore:",
                reply_markup=_backup_select_keyboard(backups)
            )
        else:
            await query.edit_message_text("No backups found.", reply_markup=admin_menu_keyboard())

    elif data.startswith("bksel_"):
        idx   = int(data[len("bksel_"):])
        paths = session["temp_data"].get("backup_list", [])
        if 0 <= idx < len(paths):
            backup_path = paths[idx]
            short = backup_path.split("/")[-1]
            await query.edit_message_text(
                f"Restore from:\n{short}\n\nThis will overwrite current data. Continue?",
                reply_markup=yes_no_keyboard(f"bkconf_{idx}", "menu_admin")
            )
        else:
            await query.edit_message_text("Invalid selection.", reply_markup=admin_menu_keyboard())

    elif data.startswith("bkconf_"):
        idx   = int(data[len("bkconf_"):])
        paths = session["temp_data"].get("backup_list", [])
        if 0 <= idx < len(paths):
            ok, msg = do_restore(paths[idx])
            await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())
        else:
            await query.edit_message_text("Backup path not found.", reply_markup=admin_menu_keyboard())

    elif data == "adm_csv":
        ok, msg, filepath = do_export_csv()
        if ok and filepath:
            await query.edit_message_text("Exporting\u2026 sending file now.")
            with open(filepath, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename=filepath.split("/")[-1],
                    caption="Inventory CSV Export"
                )
        else:
            await query.edit_message_text(msg)

    elif data == "adm_excel":
        ok, msg, filepath = do_export_excel()
        if ok and filepath:
            await query.edit_message_text("Exporting\u2026 sending file now.")
            with open(filepath, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename=filepath.split("/")[-1],
                    caption="Inventory Excel Export"
                )
        else:
            await query.edit_message_text(msg)

    elif data == "adm_secret":
        await query.edit_message_text("Enter new secret word:")
        context.user_data["awaiting"] = "change_secret"

    elif data == "adm_delete_all":
        await query.edit_message_text(
            "WARNING: Delete ALL items? This cannot be undone!",
            reply_markup=yes_no_keyboard("delall_confirm", "menu_admin")
        )

    elif data == "delall_confirm":
        ok, msg = delete_all()
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())

    elif data == "reset_confirm":
        ok, msg = do_reset_day(str(user_id))
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())


# ---------------------------------------------------------------------------
# AI pending-action execution
# ---------------------------------------------------------------------------

async def _execute_pending_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute AI-confirmed actions after the Yes button is pressed."""
    from handlers.message_handler import _execute_ai_action
    query   = update.callback_query
    user_id = update.effective_user.id
    session = get_session(user_id)
    actions = session.get("pending_actions", [])

    if not actions:
        await query.edit_message_text("No pending actions.", reply_markup=main_menu_keyboard())
        return

    try:
        await query.edit_message_text("Processing\u2026")
    except Exception:
        pass

    results = []
    for parsed in actions:
        if not isinstance(parsed, ParsedAction):
            continue
        result = await _execute_ai_action(parsed, user_id, update)

        if result == "__EXPORT_CSV__":
            ok, msg, filepath = do_export_csv()
            if ok and filepath:
                with open(filepath, "rb") as f:
                    await query.message.reply_document(
                        document=f, filename=filepath.split("/")[-1],
                        caption="Inventory CSV Export"
                    )
            else:
                results.append(msg)
        elif result == "__EXPORT_EXCEL__":
            ok, msg, filepath = do_export_excel()
            if ok and filepath:
                with open(filepath, "rb") as f:
                    await query.message.reply_document(
                        document=f, filename=filepath.split("/")[-1],
                        caption="Inventory Excel Export"
                    )
            else:
                results.append(msg)
        else:
            results.append(result)

    session["pending_actions"] = []
    if results:
        await query.message.reply_text(
            "Done:\n" + "\n".join(f"- {r}" for r in results),
            reply_markup=main_menu_keyboard()
        )
