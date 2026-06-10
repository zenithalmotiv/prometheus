"""
Message Handler for Prometheus.
Handles text messages and document uploads.
"""

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
    do_export_csv, do_export_excel,
    get_low_stock, get_order, get_zero_stock,
    generate_daily_report,
    undo_action, do_backup,
)
from services.ai_service import ai_service, NO_QTY_ACTIONS
from handlers.callback_handler import (
    get_session, main_menu_keyboard, inventory_menu_keyboard,
    item_select_keyboard, purposes_menu_keyboard, admin_menu_keyboard,
)


def auto_item_id(item_name: str, existing_ids: list) -> str:
    base = re.sub(r'[^A-Za-z]', '', item_name).upper()[:3] or "ITM"
    counter = 1
    candidate = f"{base}{counter:03d}"
    while candidate in existing_ids:
        counter += 1
        candidate = f"{base}{counter:03d}"
    return candidate


def _looks_like_item_id(s: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z]{1,5}\d+', s.strip()))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    session = get_session(user_id)

    if session.get("locked", True):
        await update.message.reply_text("Bot is locked. Send `/unlock <secret>` to access.")
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
    user_id = update.effective_user.id
    session = get_session(user_id)
    item = find_item(text)
    if not item:
        matches = [it for it in get_all_items()
                   if text.lower() in it["item_name"].lower() or text.lower() in it["item_id"].lower()]
        if matches:
            kb = item_select_keyboard(matches[:15], "sel_item")
            await update.message.reply_text(f"Multiple matches for '{text}'. Select one:", reply_markup=kb)
        else:
            await update.message.reply_text(f"Item '{text}' not found. Try again or use /cancel.")
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
            f"Select purpose for {action.title()} of {item['item_name']}:",
            reply_markup=InlineKeyboardMarkup(purposes_kb)
        )
    else:
        await update.message.reply_text(
            f"{action.title()} - {item['item_name']} ({item['current_stock']} {item['unit']})\nEnter quantity:"
        )
        context.user_data["awaiting"] = "movement_qty"


async def handle_movement_qty(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
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
    destination = action if action in ["rajagiri main", "woods", "garden cafe", "bba canteen", "bba tea counter"] else ""
    ok, msg, tx_id = process_stock_movement(
        item_id=item_id, action=action, quantity=qty,
        purpose=purpose, destination=destination, performed_by=str(user_id),
    )
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    context.user_data["awaiting"] = ""


async def handle_custom_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    session = get_session(user_id)
    session["temp_data"]["purpose"] = text
    action = session["temp_data"].get("action", "")
    item_id = session["temp_data"].get("item_id", "")
    item = find_item(item_id)
    item_name = item["item_name"] if item else item_id
    await update.message.reply_text(
        f"{action.title()} - {item_name}\nPurpose: {text}\nEnter quantity:"
    )
    context.user_data["awaiting"] = "movement_qty"


async def handle_check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    ok, msg = check_stock(text)
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())


async def handle_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    parts = [p.strip() for p in text.split("|")]
    existing_ids = [it["item_id"] for it in get_all_items()]
    if len(parts) < 2:
        await update.message.reply_text(
            "Invalid format. Use: Name | unit | stock | avg_usage\nExample: Rice | kg | 150 | 40"
        )
        return
    if _looks_like_item_id(parts[0]) and len(parts) >= 3:
        item_id = parts[0]; item_name = parts[1]; unit = parts[2] if len(parts) > 2 else "pcs"
        starting_stock = float(parts[3]) if len(parts) > 3 else 0
        current_stock = float(parts[4]) if len(parts) > 4 else starting_stock
        avg_usage = float(parts[5]) if len(parts) > 5 else 0
    else:
        item_name = parts[0]; unit = parts[1] if len(parts) > 1 else "pcs"
        starting_stock = float(parts[2]) if len(parts) > 2 else 0
        current_stock = starting_stock
        avg_usage = float(parts[3]) if len(parts) > 3 else 0
        item_id = auto_item_id(item_name, existing_ids)
    ok, msg = add_single_item(
        item_id=item_id, item_name=item_name, unit=unit,
        starting_stock=starting_stock, current_stock=current_stock, avg_daily_usage=avg_usage,
    )
    await update.message.reply_text(
        f"{msg} ID: {item_id}" if ok else msg,
        reply_markup=inventory_menu_keyboard()
    )


async def handle_add_multiple(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
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
            item_id = parts[0]; item_name = parts[1]; unit = parts[2] if len(parts) > 2 else "pcs"
            starting_stock = float(parts[3]) if len(parts) > 3 else 0
            avg_usage = float(parts[5]) if len(parts) > 5 else 0
            existing_ids.append(item_id)
        else:
            item_name = parts[0]; unit = parts[1] if len(parts) > 1 else "pcs"
            starting_stock = float(parts[2]) if len(parts) > 2 else 0
            avg_usage = float(parts[3]) if len(parts) > 3 else 0
            item_id = auto_item_id(item_name, existing_ids)
            existing_ids.append(item_id)
        items_data.append({"item_id": item_id, "item_name": item_name, "unit": unit,
                           "starting_stock": starting_stock, "current_stock": starting_stock,
                           "avg_daily_usage": avg_usage})
    if items_data:
        from services.inventory_service import add_multiple_items
        success, failed, errors = add_multiple_items(items_data)
        msg = f"Added {success} items, {failed} failed."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:10])
        await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())
    else:
        await update.message.reply_text(
            "No valid items found. Use format: Name | unit | stock | avg_usage"
        )


async def handle_bulk_import_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    success, failed, errors = parse_csv_import(text)
    msg = f"Import complete:\n- Success: {success}\n- Failed: {failed}"
    if errors:
        msg += "\n\nErrors:\n" + "\n".join(errors[:10])
    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_edit_item(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    session = get_session(user_id)
    item_id = session["temp_data"].get("edit_item_id", "")
    if not item_id:
        await update.message.reply_text("Error: No item selected.", reply_markup=inventory_menu_keyboard())
        return
    if ":" in text:
        key, value = text.split(":", 1)
        key = key.strip().lower(); value = value.strip()
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
        ok, msg = edit_item_details(
            item_id,
            item_name=parts[0] if len(parts) > 0 else None,
            location=parts[1] if len(parts) > 1 else None,
            category=parts[2] if len(parts) > 2 else None,
        )
    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_set_avg(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
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
    user_id = update.effective_user.id
    session = get_session(user_id)
    item_id = session["temp_data"].get("unit_item_id", "")
    ok, msg = set_unit(item_id, text.strip())
    await update.message.reply_text(msg, reply_markup=inventory_menu_keyboard())


async def handle_add_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    ok, msg = create_purpose(text.strip())
    await update.message.reply_text(msg, reply_markup=purposes_menu_keyboard())


async def handle_change_secret(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    change_secret_word(text.strip())
    await update.message.reply_text("Secret word updated.", reply_markup=main_menu_keyboard())


async def handle_adjustment(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    parts = text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text(
            "Format: <item_name_or_id> <new_stock_value>\nExample: rice 100"
        )
        return
    try:
        new_stock = float(parts[1].strip())
    except ValueError:
        await update.message.reply_text("Invalid stock value. Enter a number.")
        return
    item = find_item(parts[0])
    if not item:
        await update.message.reply_text(f"Item '{parts[0]}' not found.")
        return
    ok, msg, tx_id = adjust_stock(item["item_id"], new_stock, str(update.effective_user.id))
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())


async def handle_restore_select(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
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


async def _execute_ai_action(parsed, user_id: int, update: Update) -> str:
    a = parsed.action

    if a == "check":
        ok, msg = check_stock(parsed.item_name)
        return msg

    if a == "list":
        items = get_all_items()
        lines = [f"{len(items)} items in inventory:"]
        for item in items[:50]:
            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']}")
        if len(items) > 50:
            lines.append(f"... and {len(items) - 50} more")
        return "\n".join(lines)

    if a == "low_stock":
        items = get_low_stock()
        if not items:
            return "No low stock items."
        lines = ["Low Stock:"]
        for item in items:
            status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
        return "\n".join(lines)

    if a == "order_list":
        items = get_order()
        if not items:
            return "No items need ordering."
        lines = ["Order List:"]
        for item in items:
            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']}")
        return "\n".join(lines)

    if a == "daily_report":
        report = generate_daily_report()
        lines = [f"Daily Report - {report['date']}"]
        for section, label in [
            ("used_items", "Used"), ("purchased_items", "Purchased"),
            ("damaged_items", "Damaged"), ("wipro_in", "Wipro In"),
            ("wipro_out", "Wipro Out"), ("transfers", "Transfers"),
        ]:
            if report.get(section):
                lines.append(f"\n{label}:")
                for t in report[section]:
                    lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']}")
        lines.append(f"\nTotal transactions: {report['total_transactions']}")
        return "\n".join(lines)

    if a == "zero_stock":
        items = get_zero_stock()
        if not items:
            return "No zero stock items."
        lines = ["Zero Stock:"]
        for item in items:
            lines.append(f"- {item['item_name']}")
        return "\n".join(lines)

    if a == "export_csv":
        return "__EXPORT_CSV__"

    if a == "export_excel":
        return "__EXPORT_EXCEL__"

    if a == "delete_item":
        item = find_item(parsed.item_name)
        if not item:
            return f"Item '{parsed.item_name}' not found."
        ok, msg = delete_single_item(item["item_id"])
        return msg

    if a == "add_item":
        existing_ids = [it["item_id"] for it in get_all_items()]
        item_id = auto_item_id(parsed.item_name, existing_ids)
        avg = (parsed.extra or {}).get("avg_daily_usage", 0)
        ok, msg = add_single_item(
            item_id=item_id,
            item_name=parsed.item_name,
            unit=parsed.unit or "pcs",
            starting_stock=parsed.quantity,
            current_stock=parsed.quantity,
            avg_daily_usage=avg,
        )
        return f"{msg} (ID: {item_id})" if ok else msg

    if a == "set_avg":
        item = find_item(parsed.item_name)
        if not item:
            return f"Item '{parsed.item_name}' not found."
        ok, msg = set_avg_usage(item["item_id"], parsed.quantity)
        return msg

    if a == "set_unit":
        item = find_item(parsed.item_name)
        if not item:
            return f"Item '{parsed.item_name}' not found."
        ok, msg = set_unit(item["item_id"], parsed.unit)
        return msg

    if a == "stock_adjust":
        item = find_item(parsed.item_name)
        if not item:
            return f"Item '{parsed.item_name}' not found."
        ok, msg, tx_id = adjust_stock(item["item_id"], parsed.quantity, str(user_id))
        return msg

    if a == "undo":
        ok, msg = undo_action(str(user_id))
        return msg

    if a == "backup":
        ok, msg, filepath = do_backup()
        return msg

    if a == "reset_day":
        from services.inventory_service import do_reset_day
        ok, msg = do_reset_day(str(user_id))
        return msg

    item = find_item(parsed.item_name)
    if not item:
        return f"Item '{parsed.item_name}' not found."
    ok, msg, tx_id = process_stock_movement(
        item_id=item["item_id"],
        action=parsed.action,
        quantity=parsed.quantity,
        purpose=parsed.purpose,
        destination=parsed.destination,
        performed_by=str(user_id),
    )
    return msg


async def handle_ai_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    session = get_session(user_id)
    actions = session.get("pending_actions", [])

    if text.lower() in ("yes", "y", "confirm", "ok"):
        results = []
        for parsed in actions:
            result = await _execute_ai_action(parsed, user_id, update)
            if result == "__EXPORT_CSV__":
                ok, msg, filepath = do_export_csv()
                if ok and filepath:
                    await update.message.reply_text("Sending CSV...")
                    with open(filepath, "rb") as f:
                        await update.message.reply_document(
                            document=f, filename=filepath.split("/")[-1],
                            caption="Inventory CSV Export"
                        )
                else:
                    results.append(msg)
            elif result == "__EXPORT_EXCEL__":
                ok, msg, filepath = do_export_excel()
                if ok and filepath:
                    await update.message.reply_text("Sending Excel...")
                    with open(filepath, "rb") as f:
                        await update.message.reply_document(
                            document=f, filename=filepath.split("/")[-1],
                            caption="Inventory Excel Export"
                        )
                else:
                    results.append(msg)
            else:
                results.append(result)

        session["pending_actions"] = []
        if results:
            await update.message.reply_text(
                "Done:\n" + "\n".join(f"- {r}" for r in results),
                reply_markup=main_menu_keyboard()
            )

    elif text.lower() in ("no", "n", "cancel"):
        session["pending_actions"] = []
        await update.message.reply_text("Action cancelled.", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("Please reply with YES to confirm or NO to cancel.")
        context.user_data["awaiting"] = "ai_confirm"


async def try_ai_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    session = get_session(user_id)

    # NOTE: ai_service.parse() is async — must be awaited
    success, actions = await ai_service.parse(text)

    if not success or not actions:
        await update.message.reply_text(
            "I didn't understand that. Try:\n"
            "- Used: used 5 kg rice for biriyani\n"
            "- Add item: add item rice 150 kg avg 40\n"
            "- List: show all items\n"
            "- Export: give me excel\n"
            "- Report: daily report\n"
            "- Check: check rice\n"
            "- Or use /menu for buttons",
            reply_markup=main_menu_keyboard()
        )
        return

    READ_ONLY = {"check", "list", "low_stock", "order_list", "daily_report", "zero_stock"}
    write_actions = [a for a in actions if a.action not in READ_ONLY]

    if write_actions:
        session["pending_actions"] = actions
        confirmation_msg = ai_service.format_for_confirmation(actions)
        kb = [[InlineKeyboardButton("Yes", callback_data="ai_confirm_yes"),
               InlineKeyboardButton("No", callback_data="ai_confirm_no")]]
        # Plain text only — no parse_mode to avoid Markdown crashes
        await update.message.reply_text(
            confirmation_msg, reply_markup=InlineKeyboardMarkup(kb)
        )
        context.user_data["awaiting"] = "ai_confirm"
    else:
        for parsed in actions:
            result = await _execute_ai_action(parsed, user_id, update)
            await update.message.reply_text(result)
