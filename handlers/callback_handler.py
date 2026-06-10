"""
Callback Query Handler for Prometheus.
Handles all inline button interactions.
"""

import csv
import io
from typing import Dict, Any, Optional
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

# Conversation states
(
    WAITING_ITEM_ID, WAITING_ITEM_NAME, WAITING_UNIT,
    WAITING_QTY, WAITING_PURPOSE, WAITING_CONFIRM,
    WAITING_ITEM_SELECT, WAITING_NEW_VALUE,
    WAITING_SECRET_WORD, WAITING_NEW_SECRET,
    WAITING_AI_CONFIRM, WAITING_CSV,
    WAITING_BACKUP_SELECT, WAITING_NOTE,
    WAITING_MULTIPLE_ITEMS,
    MENU,
) = range(16)

# Store user session data
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
    """Check if user has unlocked the bot."""
    session = get_session(user_id)
    return not session["locked"]


def require_unlock(func):
    """Decorator to require unlock for sensitive actions."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_unlocked(user_id):
            await update.callback_query.answer("Bot is locked. Please unlock first.", show_alert=True)
            return
        return await func(update, context)
    return wrapper


# ---- Keyboard Builders ----

def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Movement", callback_data="menu_movement")],
        [InlineKeyboardButton("Reports", callback_data="menu_reports")],
        [InlineKeyboardButton("Inventory", callback_data="menu_inventory")],
        [InlineKeyboardButton("Admin", callback_data="menu_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)


def movement_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Used", callback_data="mov_used"),
         InlineKeyboardButton("Purchased", callback_data="mov_purchased")],
        [InlineKeyboardButton("Damaged", callback_data="mov_damaged"),
         InlineKeyboardButton("Wipro In", callback_data="mov_wipro_in")],
        [InlineKeyboardButton("Wipro Out", callback_data="mov_wipro_out")],
        [InlineKeyboardButton("Rajagiri Main", callback_data="mov_rajagiri_main"),
         InlineKeyboardButton("Woods", callback_data="mov_woods")],
        [InlineKeyboardButton("Garden Cafe", callback_data="mov_garden_cafe"),
         InlineKeyboardButton("BBA Canteen", callback_data="mov_bba_canteen")],
        [InlineKeyboardButton("BBA Tea Counter", callback_data="mov_bba_tea_counter")],
        [InlineKeyboardButton("Stock Adjustment", callback_data="mov_adjustment")],
        [InlineKeyboardButton("Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def reports_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Check Stock", callback_data="rep_check")],
        [InlineKeyboardButton("Low Stock", callback_data="rep_low")],
        [InlineKeyboardButton("Order List", callback_data="rep_order")],
        [InlineKeyboardButton("Daily Report", callback_data="rep_daily")],
        [InlineKeyboardButton("List All Items", callback_data="rep_list")],
        [InlineKeyboardButton("Zero Stock", callback_data="rep_zero")],
        [InlineKeyboardButton("List by Section", callback_data="rep_section")],
        [InlineKeyboardButton("Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def inventory_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Item", callback_data="inv_add")],
        [InlineKeyboardButton("Add Multiple", callback_data="inv_add_multi")],
        [InlineKeyboardButton("Bulk Import (CSV)", callback_data="inv_bulk")],
        [InlineKeyboardButton("Edit Item", callback_data="inv_edit")],
        [InlineKeyboardButton("Delete Item", callback_data="inv_delete")],
        [InlineKeyboardButton("Set Avg Usage", callback_data="inv_avg")],
        [InlineKeyboardButton("Set Unit", callback_data="inv_unit")],
        [InlineKeyboardButton("Manage Purposes", callback_data="inv_purposes")],
        [InlineKeyboardButton("Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Lock Bot", callback_data="adm_lock")],
        [InlineKeyboardButton("Reset Day", callback_data="adm_reset")],
        [InlineKeyboardButton("Undo Last Action", callback_data="adm_undo")],
        [InlineKeyboardButton("Backup", callback_data="adm_backup")],
        [InlineKeyboardButton("Restore", callback_data="adm_restore")],
        [InlineKeyboardButton("Export CSV", callback_data="adm_csv")],
        [InlineKeyboardButton("Export Excel", callback_data="adm_excel")],
        [InlineKeyboardButton("Change Secret", callback_data="adm_secret")],
        [InlineKeyboardButton("Delete All Items", callback_data="adm_delete_all")],
        [InlineKeyboardButton("Back", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def section_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Rajagiri Main", callback_data="sec_rajagiri main")],
        [InlineKeyboardButton("Woods", callback_data="sec_woods")],
        [InlineKeyboardButton("Garden Cafe", callback_data="sec_garden cafe")],
        [InlineKeyboardButton("BBA Canteen", callback_data="sec_bba canteen")],
        [InlineKeyboardButton("BBA Tea Counter", callback_data="sec_bba tea counter")],
        [InlineKeyboardButton("Back", callback_data="menu_reports")],
    ]
    return InlineKeyboardMarkup(keyboard)


def purposes_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("List Purposes", callback_data="pur_list")],
        [InlineKeyboardButton("Add Purpose", callback_data="pur_add")],
        [InlineKeyboardButton("Remove Purpose", callback_data="pur_remove")],
        [InlineKeyboardButton("Back", callback_data="menu_inventory")],
    ]
    return InlineKeyboardMarkup(keyboard)


def yes_no_keyboard(callback_yes: str, callback_no: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Yes", callback_data=callback_yes),
         InlineKeyboardButton("No", callback_data=callback_no)],
    ]
    return InlineKeyboardMarkup(keyboard)


def item_select_keyboard(items: list, callback_prefix: str) -> InlineKeyboardMarkup:
    keyboard = []
    for item in items:
        btn_text = f"{item['item_name']} ({item['current_stock']} {item['unit']})"
        callback = f"{callback_prefix}_{item['item_id']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback)])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="menu_main")])
    return InlineKeyboardMarkup(keyboard)


# ---- Callback Handlers ----

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    session = get_session(user_id)

    if data == "menu_main":
        await query.edit_message_text(
            "*Prometheus Main Menu*",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif data == "menu_movement":
        await query.edit_message_text(
            "*Add Movement* - Select action:",
            reply_markup=movement_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif data == "menu_reports":
        await query.edit_message_text(
            "*Reports* - Select report:",
            reply_markup=reports_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif data == "menu_inventory":
        await query.edit_message_text(
            "*Inventory Management*",
            reply_markup=inventory_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif data == "menu_admin":
        await query.edit_message_text(
            "*Admin Panel*",
            reply_markup=admin_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    elif data.startswith("mov_"):
        action = data.replace("mov_", "")
        session["temp_data"] = {"action": action}

        if action == "adjustment":
            await query.edit_message_text(
                "Enter the item name or ID and the new stock value.\n"
                "Format: <item_name> <new_stock>\n"
                "Example: rice 100",
            )
            context.user_data["awaiting"] = "adjustment"
            return

        await query.edit_message_text(
            f"{action.replace('_', ' ').title()} - Enter item name or ID:",
        )
        context.user_data["awaiting"] = "movement_item"
        return

    elif data.startswith("rep_"):
        await handle_report_callback(update, context, data)
        return

    elif data == "rep_section":
        await query.edit_message_text(
            "List by Section - Select section:",
            reply_markup=section_menu_keyboard(),
        )
        return

    elif data.startswith("sec_"):
        section = data.replace("sec_", "")
        items = get_items_by_section(section)
        if items:
            lines = [f"{section.title()} - Items:"]
            for item in items:
                lines.append(
                    f"- {item['item_name']}: {item.get(section.replace(' ', '_'), 0)} {item['unit']}"
                )
            await query.edit_message_text("\n".join(lines))
        else:
            await query.edit_message_text(
                f"No items found for {section.title()}.",
                reply_markup=section_menu_keyboard()
            )
        return

    elif data.startswith("inv_"):
        await handle_inventory_callback(update, context, data)
        return

    elif data.startswith("pur_"):
        await handle_purpose_callback(update, context, data)
        return

    elif data.startswith("adm_") or data in ("delall_confirm", "reset_confirm") or data.startswith("restore_sel_") or data.startswith("restore_conf_"):
        await handle_admin_callback(update, context, data)
        return

    elif data == "ai_confirm_yes":
        await execute_pending_actions(update, context)
        return

    elif data == "ai_confirm_no":
        session["pending_actions"] = []
        await query.edit_message_text(
            "Action cancelled.",
            reply_markup=main_menu_keyboard()
        )
        return

    elif data.startswith("del_confirm_"):
        item_id = data.replace("del_confirm_", "")
        ok, msg = delete_single_item(item_id)
        await query.edit_message_text(msg, reply_markup=inventory_menu_keyboard())
        return

    elif data.startswith("sel_item_"):
        item_id = data.replace("sel_item_", "")
        session["temp_data"]["item_id"] = item_id
        action = session["temp_data"].get("action", "")

        if action == "used":
            purposes = get_all_purposes()
            purposes_kb = []
            row = []
            for i, p in enumerate(purposes):
                row.append(InlineKeyboardButton(p.title(), callback_data=f"pur_sel_{p}"))
                if (i + 1) % 2 == 0:
                    purposes_kb.append(row)
                    row = []
            if row:
                purposes_kb.append(row)
            purposes_kb.append([InlineKeyboardButton("Custom Purpose", callback_data="pur_sel_custom")])
            purposes_kb.append([InlineKeyboardButton("Cancel", callback_data="menu_main")])
            await query.edit_message_text(
                f"Select purpose for Used action:",
                reply_markup=InlineKeyboardMarkup(purposes_kb),
            )
            return
        else:
            await query.edit_message_text(
                f"Enter quantity for {action.replace('_', ' ').title()}:\n(Item: {item_id})",
            )
            context.user_data["awaiting"] = "movement_qty"
            return

    elif data.startswith("pur_sel_"):
        purpose = data.replace("pur_sel_", "")
        session["temp_data"]["purpose"] = purpose

        if purpose == "custom":
            await query.edit_message_text("Enter custom purpose:")
            context.user_data["awaiting"] = "custom_purpose"
            return

        await query.edit_message_text(
            f"Enter quantity for Used:\nPurpose: {purpose.title()}",
        )
        context.user_data["awaiting"] = "movement_qty"
        return

    elif data.startswith(("edit_", "del_", "avg_", "unit_")):
        await handle_item_action_callback(update, context, data)
        return

    else:
        await query.edit_message_text(
            "Unknown action. Please use the menu.",
            reply_markup=main_menu_keyboard()
        )


async def handle_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    action = data.replace("rep_", "")

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
            await query.edit_message_text("\n".join(lines))
        else:
            await query.edit_message_text("No low stock items found.")

    elif action == "order":
        items = get_order()
        if items:
            lines = ["Order List:\n"]
            for item in items:
                status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
                lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
            await query.edit_message_text("\n".join(lines))
        else:
            await query.edit_message_text("No items need ordering.")

    elif action == "daily":
        report = generate_daily_report()
        lines = [f"Daily Report - {report['date']}\n"]
        for section, label in [
            ("used_items", "Used"), ("purchased_items", "Purchased"),
            ("damaged_items", "Damaged"), ("wipro_in", "Wipro In"),
            ("wipro_out", "Wipro Out"), ("transfers", "Transfers"),
            ("adjustments", "Adjustments"),
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
            msg = msg[:3990] + "...\n(truncated)"
        await query.edit_message_text(msg)

    elif action == "list":
        items = get_all_items()
        if items:
            lines = [f"All Items ({len(items)}):\n"]
            for item in items:
                lines.append(f"- {item['item_name']} ({item['item_id']}): {item['current_stock']} {item['unit']}")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3990] + "...\n(truncated)"
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


async def handle_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    action = data.replace("inv_", "")
    user_id = update.effective_user.id
    session = get_session(user_id)

    if action == "add":
        await query.edit_message_text(
            "Add Item - Send details in format:\n"
            "Name | unit | starting_stock | avg_usage\n"
            "Example: Rice | kg | 150 | 40\n\n"
            "Or with custom ID:\n"
            "ID | name | unit | stock | current | avg\n"
            "Example: R001 | Rice | kg | 150 | 150 | 40",
        )
        context.user_data["awaiting"] = "add_item"

    elif action == "add_multi":
        await query.edit_message_text(
            "Add Multiple Items - Send one per line:\n"
            "Name | unit | starting_stock | avg_usage\n"
            "Example:\n"
            "Rice | kg | 150 | 40\n"
            "Sugar | kg | 50 | 20",
        )
        context.user_data["awaiting"] = "add_multi"

    elif action == "bulk":
        await query.edit_message_text(
            "Bulk Import - Send CSV content or file:\n"
            "Required columns: item_id, item_name, unit\n"
            "Optional: starting_stock, current_stock, avg_daily_usage, location, category",
        )
        context.user_data["awaiting"] = "bulk_import"

    elif action == "edit":
        items = get_all_items()
        if items:
            kb = item_select_keyboard(items[:20], "edit")
            await query.edit_message_text("Select item to edit:", reply_markup=kb)
        else:
            await query.edit_message_text("No items to edit.")

    elif action == "delete":
        items = get_all_items()
        if items:
            kb = item_select_keyboard(items[:20], "del")
            await query.edit_message_text("Select item to delete:", reply_markup=kb)
        else:
            await query.edit_message_text("No items to delete.")

    elif action == "avg":
        items = get_all_items()
        if items:
            kb = item_select_keyboard(items[:20], "avg")
            await query.edit_message_text("Select item to set average usage:", reply_markup=kb)
        else:
            await query.edit_message_text("No items available.")

    elif action == "unit":
        items = get_all_items()
        if items:
            kb = item_select_keyboard(items[:20], "unit")
            await query.edit_message_text("Select item to change unit:", reply_markup=kb)
        else:
            await query.edit_message_text("No items available.")

    elif action == "purposes":
        await query.edit_message_text("Manage Purposes", reply_markup=purposes_menu_keyboard())


async def handle_item_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    user_id = update.effective_user.id
    session = get_session(user_id)

    if data.startswith("edit_"):
        item_id = data.replace("edit_", "")
        session["temp_data"]["edit_item_id"] = item_id
        await query.edit_message_text(
            f"Editing item {item_id}.\n"
            f"Send: name | location | category\n"
            f"Or: name: New Name",
        )
        context.user_data["awaiting"] = "edit_item"

    elif data.startswith("del_"):
        item_id = data[len("del_"):]
        session["temp_data"]["delete_item_id"] = item_id
        item = find_item(item_id)
        item_name = item["item_name"] if item else item_id
        await query.edit_message_text(
            f"Delete {item_name}? This cannot be undone.",
            reply_markup=yes_no_keyboard(f"del_confirm_{item_id}", "menu_inventory"),
        )

    elif data.startswith("avg_"):
        item_id = data.replace("avg_", "")
        session["temp_data"]["avg_item_id"] = item_id
        await query.edit_message_text(
            f"Enter average daily usage for {item_id}:\n(in the item's unit per day)",
        )
        context.user_data["awaiting"] = "set_avg"

    elif data.startswith("unit_"):
        item_id = data.replace("unit_", "")
        session["temp_data"]["unit_item_id"] = item_id
        await query.edit_message_text(
            f"Enter new unit for {item_id}:\n(kg, g, L, ml, pcs, packet, etc.)",
        )
        context.user_data["awaiting"] = "set_unit"


async def handle_purpose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    action = data.replace("pur_", "")

    if action == "list":
        purposes = get_all_purposes()
        if purposes:
            await query.edit_message_text(
                "Available Purposes:\n" + "\n".join(f"- {p.title()}" for p in purposes),
                reply_markup=purposes_menu_keyboard(),
            )
        else:
            await query.edit_message_text("No purposes defined.", reply_markup=purposes_menu_keyboard())

    elif action == "add":
        await query.edit_message_text("Enter new purpose name:")
        context.user_data["awaiting"] = "add_purpose"

    elif action == "remove":
        purposes = get_all_purposes()
        if purposes:
            kb = [[InlineKeyboardButton(p.title(), callback_data=f"pur_del_{p}")] for p in purposes]
            kb.append([InlineKeyboardButton("Cancel", callback_data="menu_inventory")])
            await query.edit_message_text("Select purpose to remove:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text("No purposes to remove.")

    elif data.startswith("pur_del_"):
        purpose = data.replace("pur_del_", "")
        ok, msg = delete_purpose(purpose)
        await query.edit_message_text(msg, reply_markup=purposes_menu_keyboard())


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    action = data.replace("adm_", "")
    user_id = update.effective_user.id
    session = get_session(user_id)

    if action == "lock":
        session["locked"] = True
        await query.edit_message_text("Bot is now LOCKED. Send /unlock <secret> to access.")

    elif action == "reset":
        await query.edit_message_text(
            "Reset Day - This will carry current stock as starting stock and reset all counters.\nAre you sure?",
            reply_markup=yes_no_keyboard("reset_confirm", "menu_admin"),
        )

    elif action == "undo":
        ok, msg = undo_action(str(user_id))
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())

    elif action == "backup":
        ok, msg, filepath = do_backup()
        if ok:
            await query.edit_message_text(f"{msg}\nPath: {filepath}", reply_markup=admin_menu_keyboard())
        else:
            await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())

    elif action == "restore":
        backups = get_backups()
        if backups:
            kb = []
            for b in backups[:10]:
                fname = b['filename']
                short = fname[-40:] if len(fname) > 40 else fname
                kb.append([InlineKeyboardButton(short, callback_data=f"restore_sel_{fname}")])
            kb.append([InlineKeyboardButton("Cancel", callback_data="menu_admin")])
            await query.edit_message_text("Select backup to restore:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text("No backups found.", reply_markup=admin_menu_keyboard())

    elif data.startswith("restore_sel_"):
        backup_path = data.replace("restore_sel_", "")
        await query.edit_message_text(
            f"Restore from {backup_path}?\nThis will overwrite current data.",
            reply_markup=yes_no_keyboard(f"restore_conf_{backup_path}", "menu_admin"),
        )

    elif data.startswith("restore_conf_"):
        backup_path = data.replace("restore_conf_", "")
        ok, msg = do_restore(backup_path)
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())

    elif action == "csv":
        ok, msg, filepath = do_export_csv()
        if ok and filepath:
            await query.edit_message_text("Exporting... sending file now.")
            with open(filepath, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename=filepath.split("/")[-1],
                    caption="Inventory CSV Export"
                )
        else:
            await query.edit_message_text(msg)

    elif action == "excel":
        ok, msg, filepath = do_export_excel()
        if ok and filepath:
            await query.edit_message_text("Exporting... sending file now.")
            with open(filepath, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename=filepath.split("/")[-1],
                    caption="Inventory Excel Export"
                )
        else:
            await query.edit_message_text(msg)

    elif action == "secret":
        await query.edit_message_text("Enter new secret word:")
        context.user_data["awaiting"] = "change_secret"

    elif action == "delete_all":
        await query.edit_message_text(
            "WARNING: Delete ALL items? This cannot be undone!",
            reply_markup=yes_no_keyboard("delall_confirm", "menu_admin"),
        )

    elif data == "delall_confirm":
        ok, msg = delete_all()
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())

    elif data == "reset_confirm":
        ok, msg = do_reset_day(str(user_id))
        await query.edit_message_text(msg, reply_markup=admin_menu_keyboard())


async def execute_pending_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute pending AI-parsed actions after Yes button press."""
    from handlers.message_handler import _execute_ai_action
    query = update.callback_query
    user_id = update.effective_user.id
    session = get_session(user_id)
    actions = session.get("pending_actions", [])

    if not actions:
        await query.edit_message_text("No pending actions.", reply_markup=main_menu_keyboard())
        return

    # Dismiss the confirm message first (plain text, no parse_mode to avoid entity errors)
    try:
        await query.edit_message_text("Processing...")
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
                await query.message.reply_text("Sending CSV...")
                with open(filepath, "rb") as f:
                    await query.message.reply_document(
                        document=f,
                        filename=filepath.split("/")[-1],
                        caption="Inventory CSV Export"
                    )
            else:
                results.append(msg)
        elif result == "__EXPORT_EXCEL__":
            ok, msg, filepath = do_export_excel()
            if ok and filepath:
                await query.message.reply_text("Sending Excel...")
                with open(filepath, "rb") as f:
                    await query.message.reply_document(
                        document=f,
                        filename=filepath.split("/")[-1],
                        caption="Inventory Excel Export"
                    )
            else:
                results.append(msg)
        else:
            results.append(result)

    session["pending_actions"] = []
    if results:
        # Use plain text (no parse_mode) to avoid Markdown entity crashes
        # from item names or file paths containing underscores/special chars
        await query.message.reply_text(
            "Done:\n" + "\n".join(f"- {r}" for r in results),
            reply_markup=main_menu_keyboard()
        )
