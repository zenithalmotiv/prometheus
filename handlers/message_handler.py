"""
Message Handler for Prometheus.
Handles text messages and document uploads.
"""

import csv
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.config import config
from services.inventory_service import (
    add_single_item, delete_single_item, set_avg_usage, set_unit,
    edit_item_details, process_stock_movement, adjust_stock,
    find_item, get_all_items, check_stock, get_items_by_section,
    get_all_purposes, create_purpose,
    parse_csv_import,
    change_secret_word,
    do_restore, get_backups,
)
from services.ai_service import ai_service
from handlers.callback_handler import (
    get_session, main_menu_keyboard, inventory_menu_keyboard,
    item_select_keyboard, purposes_menu_keyboard, admin_menu_keyboard,
)


def auto_item_id(item_name: str, existing_ids: list) -> str:
    """Generate a unique item ID from the item name."""
    base = re.sub(r'[^A-Za-z]', '', item_name).upper()[:3] or "ITM"
    counter = 1
    candidate = f"{base}{counter:03d}"
    while candidate in existing_ids:
        counter += 1
        candidate = f"{base}{counter:03d}"
    return candidate


def _looks_like_item_id(s: str) -> bool:
    """Return True if the string looks like a custom item ID (e.g. R001, ITM1)."""
    return bool(re.fullmatch(r'[A-Za-z]{1,5}\d+', s.strip()))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler - routes to specific handlers based on state."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    session = get_session(user_id)

    if session.get("locked", True):
        await update.message.reply_text(
            "Bot is locked. Send `/unlock <secret>` to access."
        )
        return

    awaiting = context.user_data.get("awaiting", "")

    if awaiting == "movement_item":
        await handle_movement_item(update, context, text)
    elif awaiting == "movement_qty":
        await handle_movement_qty(update, context, text)
    elif awaiting == "custom_purpose":
        await handle_custom_purpose(update, context, text)
    elif awaiting == "check_stock":
        await handle_check_stock(update, context, text)
    elif awaiting == "add_item":
        await handle_add_item(update, context, text)
    elif awaiting == "add_multi":
        await handle_add_multiple(update, context, text)
    elif awaiting == "bulk_import":
        await handle_bulk_import_text(update, context, text)
    elif awaiting == "edit_item":
        await handle_edit_item(update, context, text)
    elif awaiting == "set_avg":
        await handle_set_avg(update, context, text)
    elif awaiting == "set_unit":
        await handle_set_unit(update, context, text)
    elif awaiting == "add_purpose":
        await handle_add_purpose(update, context, text)
    elif awaiting == "change_secret":
        await handle_change_secret(update, context, text)
    elif awaiting == "adjustment":
        await handle_adjustment(update, context, text)
    elif awaiting == "ai_confirm":
        await handle_ai_confirmation(update, context, text)
    elif awaiting == "restore_select":
        await handle_restore_select(update, context, text)
    else:
        await try_ai_mode(update, context, text)

    if awaiting not in ("movement_qty", "custom_purpose"):
        context.user_data["awaiting"] = ""


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (for CSV import)."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    if session.get("locked", True):
        await update.message.reply_text("Bot is locked.")
        return

    doc = update.message.document
    if not doc:
        return

    if doc.file_name.endswith(".csv"):
        file = await doc.get_file()
        content = await file.download_as_bytearray()
        csv_text = content.decode("utf-8")

        success, failed, errors = parse_csv_import(csv_text)
        msg = f"Import complete:\n- Success: {success}\n- Failed: {failed}"
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:10])
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("Please upload a .csv file.")


# ---- Specific Handlers ----

async def handle_movement_item(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle item name/ID input for movement."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    item = find_item(text)
    if not item:
        matches = []
        all_items = get_all_items()
        for it in all_items:
            if text.lower() in it["item_name"].lower() or text.lower() in it["item_id"].lower():
                matches.append(it)

        if matches:
            kb = item_select_keyboard(matches[:15], "sel_item")
            await update.message.reply_text(
                f"Multiple matches for '{text}'. Select one:",
                reply_markup=kb
            )
        else:
            await update.message.reply_text(
                f"Item '{text}' not found. Try again or use /cancel."
            )
            context.user_data["awaiting"] = "movement_item"
        return

    session["temp_data"]["item_id"] = item["item_id"]
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

        await update.message.reply_text(
            f"Select purpose for *{action.title()}* of *{item['item_name']}*:",
            reply_markup=InlineKeyboardMarkup(purposes_kb),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"*{action.title()}* - {item['item_name']} ({item['current_stock']} {item['unit']})\n"
            f"Enter quantity:",
            parse_mode="Markdown"
        )
        context.user_data["awaiting"] = "movement_qty"


async def handle_movement_qty(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle quantity input for movement."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    try:
        qty = float(text.strip())
        if qty <= 0:
            await update.message.reply_text("Quantity must be positive. Try again:")
            context.user_data["awaiting"] = "movement_qty"
            return
    except ValueError:
        await update.message.reply_text("Invalid quantity. Enter a number:")
        context.user_data["awaiting"] = "movement_qty"
        return

    action = session["temp_data"].get("action", "")
    item_id = session["temp_data"].get("item_id", "")
    purpose = session["temp_data"].get("purpose", "")
    destination = ""

    if action in ["rajagiri main", "woods", "garden cafe", "bba canteen", "bba tea counter"]:
        destination = action

    ok, msg, tx_id = process_stock_movement(
        item_id=item_id,
        action=action,
        quantity=qty,
        purpose=purpose,
        destination=destination,
        performed_by=str(user_id),
    )

    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    context.user_data["awaiting"] = ""


async def handle_custom_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle custom purpose input."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    session["temp_data"]["purpose"] = text
    action = session["temp_data"].get("action", "")
    item_id = session["temp_data"].get("item_id", "")

    item = find_item(item_id)
    item_name = item["item_name"] if item else item_id

    await update.message.reply_text(
        f"*{action.title()}* - {item_name}\n"
        f"Purpose: {text}\n"
        f"Enter quantity:",
        parse_mode="Markdown"
    )
    context.user_data["awaiting"] = "movement_qty"


async def handle_check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle stock check request."""
    ok, msg = check_stock(text)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())


async def handle_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle add single item input."""
    parts = [p.strip() for p in text.split("|")]
    existing_ids = [it["item_id"] for it in get_all_items()]

    if len(parts) < 2:
        await update.message.reply_text(
            "Invalid format. Use:\n"
            "`Name | unit | stock | avg_usage`\n"
            "Example: `Rice | kg | 150 | 40`",
            parse_mode="Markdown"
        )
        return

    if _looks_like_item_id(parts[0]) and len(parts) >= 3:
        item_id = parts[0]
        item_name = parts[1]
        unit = parts[2] if len(parts) > 2 else "pcs"
        starting_stock = float(parts[3]) if len(parts) > 3 else 0
        current_stock = float(parts[4]) if len(parts) > 4 else starting_stock
        avg_usage = float(parts[5]) if len(parts) > 5 else 0
    else:
        item_name = parts[0]
        unit = parts[1] if len(parts) > 1 else "pcs"
        starting_stock = float(parts[2]) if len(parts) > 2 else 0
        current_stock = starting_stock
        avg_usage = float(parts[3]) if len(parts) > 3 else 0
        item_id = auto_item_id(item_name, existing_ids)

    ok, msg = add_single_item(
        item_id=item_id,
        item_name=item_name,
        unit=unit,
        starting_stock=starting_stock,
        current_stock=current_stock,
        avg_daily_usage=avg_usage,
    )
    await update.message.reply_text(
        f"{msg}\nID assigned: `{item_id}`" if ok else msg,
        reply_markup=inventory_menu_keyboard(),
        parse_mode="Markdown"
    )


async def handle_add_multiple(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle multiple items input."""
    lines = text.strip().split("\n")
    items_data = []
    existing_ids = [it["item_id"] for it in get_all_items()]

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue

        if _looks_like_item_id(parts[0]) and len(parts) >= 3:
            item_id = parts[0]
            item_name = parts[1]
            unit = parts[2] if len(parts) > 2 else "pcs"
            starting_stock = float(parts[3]) if len(parts) > 3 else 0
            avg_usage = float(parts[5]) if len(parts) > 5 else 0
            existing_ids.append(item_id)
        else:
            item_name = parts[0]
            unit = parts[1] if len(parts) > 1 else "pcs"
            starting_stock = float(parts[2]) if len(parts) > 2 else 0
            avg_usage = float(parts[3]) if len(parts) > 3 else 0
            item_id = auto_item_id(item_name, existing_ids)
            existing_ids.append(item_id)

        items_data.append({
            "item_id": item_id,
            "item_name": item_name,
            "unit": unit,
            "starting_stock": starting_stock,
            "current_stock": starting_stock,
            "avg_daily_usage": avg_usage,
        })

    if items_data:
        from services.inventory_service import add_multiple_items
        success, failed, errors = add_multiple_items(items_data)
        msg = f"Added {success} items, {failed} failed."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:10])
        await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())
    else:
        await update.message.reply_text(
            "No valid items found. Use format:\n"
            "`Name | unit | stock | avg_usage`",
            parse_mode="Markdown"
        )


async def handle_bulk_import_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle bulk import from pasted CSV text."""
    success, failed, errors = parse_csv_import(text)
    msg = f"Import complete:\n- Success: {success}\n- Failed: {failed}"
    if errors:
        msg += "\n\nErrors:\n" + "\n".join(errors[:10])
    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_edit_item(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle edit item input."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    item_id = session["temp_data"].get("edit_item_id", "")

    if not item_id:
        await update.message.reply_text("Error: No item selected.", reply_markup=inventory_menu_keyboard())
        return

    if ":" in text:
        key, value = text.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in ("name", "item_name"):
            ok, msg = edit_item_details(item_id, item_name=value)
        elif key == "location":
            ok, msg = edit_item_details(item_id, location=value)
        elif key == "category":
            ok, msg = edit_item_details(item_id, category=value)
        else:
            ok, msg = False, f"Unknown field: {key}"
    else:
        parts = [p.strip() for p in text.split("|")]
        name = parts[0] if len(parts) > 0 else None
        location = parts[1] if len(parts) > 1 else None
        category = parts[2] if len(parts) > 2 else None
        ok, msg = edit_item_details(item_id, item_name=name, location=location, category=category)

    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_set_avg(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle set average usage input."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    item_id = session["temp_data"].get("avg_item_id", "")
    try:
        avg = float(text.strip())
        ok, msg = set_avg_usage(item_id, avg)
    except ValueError:
        ok, msg = False, "Invalid number."
    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_set_unit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle set unit input."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    item_id = session["temp_data"].get("unit_item_id", "")
    ok, msg = set_unit(item_id, text.strip())
    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_add_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle add purpose input."""
    ok, msg = create_purpose(text.strip())
    await update.message.reply_text(msg, reply_markup=purposes_menu_keyboard())


async def handle_change_secret(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle change secret word input."""
    change_secret_word(text.strip())
    await update.message.reply_text("Secret word updated.", reply_markup=main_menu_keyboard())


async def handle_adjustment(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle stock adjustment input."""
    parts = text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "Format: `<item_name_or_id> <new_stock_value>`\nExample: `rice 100`",
            parse_mode="Markdown"
        )
        return

    item_identifier = parts[0]
    try:
        new_stock = float(parts[1].strip())
    except ValueError:
        await update.message.reply_text("Invalid stock value. Enter a number.")
        return

    item = find_item(item_identifier)
    if not item:
        await update.message.reply_text(f"Item '{item_identifier}' not found.")
        return

    ok, msg, tx_id = adjust_stock(item["item_id"], new_stock, str(update.effective_user.id))
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())


async def handle_restore_select(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle restore backup selection by number or path."""
    backups = get_backups()
    backup_path = None
    try:
        idx = int(text.strip()) - 1
        if 0 <= idx < len(backups):
            backup_path = backups[idx]["filename"]
    except ValueError:
        backup_path = text.strip()

    if not backup_path:
        await update.message.reply_text("Invalid selection.")
        context.user_data["awaiting"] = "restore_select"
        return

    ok, msg = do_restore(backup_path)
    await update.message.reply_text(msg, reply_markup=admin_menu_keyboard())


async def handle_ai_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle AI action confirmation response."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    actions = session.get("pending_actions", [])

    if text.lower() in ("yes", "y", "confirm", "ok"):
        results = []
        from services.ai_service import ParsedAction
        for parsed in actions:
            if isinstance(parsed, ParsedAction):
                if parsed.action in ["check", "low stock", "list"]:
                    results.append(f"Skipped query: {parsed.item_name}")
                    continue

                # Handle delete_item separately - no stock movement needed
                if parsed.action == "delete_item":
                    item = find_item(parsed.item_name)
                    if not item:
                        results.append(f"Item '{parsed.item_name}' not found.")
                        continue
                    ok, msg = delete_single_item(item["item_id"])
                    results.append(msg)
                    continue

                item = find_item(parsed.item_name)
                if not item:
                    results.append(f"Item '{parsed.item_name}' not found.")
                    continue

                ok, msg, tx_id = process_stock_movement(
                    item_id=item["item_id"],
                    action=parsed.action,
                    quantity=parsed.quantity,
                    purpose=parsed.purpose,
                    destination=parsed.destination,
                    performed_by=str(user_id),
                )
                results.append(msg)

        session["pending_actions"] = []
        await update.message.reply_text(
            "*Actions executed:*\n" + "\n".join(f"- {r}" for r in results),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )

    elif text.lower() in ("no", "n", "cancel"):
        session["pending_actions"] = []
        await update.message.reply_text("Action cancelled.", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(
            "Please reply with *yes* to confirm or *no* to cancel.",
            parse_mode="Markdown"
        )
        context.user_data["awaiting"] = "ai_confirm"


async def try_ai_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Try to parse message using AI mode."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    success, actions = ai_service.parse(text)

    if success and actions:
        stock_actions = [a for a in actions if a.action not in ["check", "low stock", "list"]]

        if stock_actions:
            session["pending_actions"] = actions
            confirmation_msg = ai_service.format_for_confirmation(actions)
            kb = [
                [InlineKeyboardButton("Yes", callback_data="ai_confirm_yes"),
                 InlineKeyboardButton("No", callback_data="ai_confirm_no")],
            ]
            await update.message.reply_text(
                confirmation_msg,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
            context.user_data["awaiting"] = "ai_confirm"
        else:
            for action in actions:
                if action.action == "check":
                    ok, msg = check_stock(action.item_name)
                    await update.message.reply_text(msg, parse_mode="Markdown")
                elif action.action == "low stock":
                    from services.inventory_service import get_low_stock
                    items = get_low_stock()
                    if items:
                        lines = ["*Low Stock:*\n"]
                        for item in items:
                            status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
                            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
                        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
                    else:
                        await update.message.reply_text("No low stock items.")
                elif action.action == "list":
                    items = get_all_items()
                    lines = [f"*{len(items)} items:*\n"]
                    for item in items[:30]:
                        lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']}")
                    if len(items) > 30:
                        lines.append(f"... and {len(items) - 30} more")
                    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "I didn't understand that. Use the menu buttons or try:\n"
            "- `/menu` for main menu\n"
            "- `/help` for commands\n"
            "- Natural language like 'used 5 kg rice for biriyani'",
            reply_markup=main_menu_keyboard()
        )
