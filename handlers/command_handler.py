"""
Command Handler for Prometheus.
Handles all slash commands.
"""

import re
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
    check_secret_word, change_secret_word,
    parse_csv_import,
)
from services.ai_service import ai_service
from handlers.callback_handler import (
    get_session, main_menu_keyboard, movement_menu_keyboard,
    inventory_menu_keyboard, reports_menu_keyboard, admin_menu_keyboard,
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "User"
    session = get_session(user_id)

    welcome_text = (
        f"Welcome to *Prometheus*, {username}!\n\n"
        f"Your canteen inventory assistant.\n\n"
        f"The bot is currently *{'LOCKED' if session.get('locked', True) else 'UNLOCKED'}*.\n"
    )

    if session.get("locked", True):
        welcome_text += "Send `/unlock <secret>` to get started."
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    else:
        welcome_text += "Use the menu below:"
        await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )


async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unlock command."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/unlock <secret_word>`",
            parse_mode="Markdown"
        )
        return

    word = " ".join(args)
    if check_secret_word(word):
        session["locked"] = False
        await update.message.reply_text(
            "Bot *unlocked*! Welcome.\nUse the menu to get started:",
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Incorrect secret word. Try again.")


async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lock command."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    session["locked"] = True
    await update.message.reply_text("Bot is now *LOCKED*.", parse_mode="Markdown")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command."""
    user_id = update.effective_user.id
    session = get_session(user_id)

    if session.get("locked", True):
        await update.message.reply_text("Bot is locked. Send `/unlock <secret>` to access.")
        return

    await update.message.reply_text(
        "*Main Menu*",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "*Prometheus - Canteen Inventory Bot*\n\n"
        "*Access Control:*\n"
        "`/unlock <secret>` - Unlock the bot\n"
        "`/lock` - Lock the bot\n"
        "`/change_secret <new>` - Change secret word\n\n"
        "*Stock Movements:*\n"
        "`/used <qty> <unit> <item> for <purpose>` - Record usage\n"
        "`/purchased <qty> <unit> <item>` - Record purchase\n"
        "`/damaged <qty> <unit> <item>` - Record damage\n"
        "`/wipro_in <qty> <unit> <item>` - Wipro inward\n"
        "`/wipro_out <qty> <unit> <item>` - Wipro outward\n"
        "`/rajagiri_main <qty> <unit> <item>` - Transfer to Rajagiri Main\n"
        "`/woods <qty> <unit> <item>` - Transfer to Woods\n"
        "`/garden_cafe <qty> <unit> <item>` - Transfer to Garden Cafe\n"
        "`/bba_canteen <qty> <unit> <item>` - Transfer to BBA Canteen\n"
        "`/bba_tea <qty> <unit> <item>` - Transfer to BBA Tea Counter\n\n"
        "*Queries:*\n"
        "`/check <item>` - Check stock\n"
        "`/low_stock` - Low stock items\n"
        "`/order_list` - Items to order\n"
        "`/daily_report` - Today's report\n"
        "`/list_all` - All items\n"
        "`/zero_stock` - Zero stock items\n\n"
        "*Item Management:*\n"
        "`/add_item <id> | <name> | <unit> | <stock> | <avg>` - Add item\n"
        "`/set_avg <item> <value>` - Set average usage\n"
        "`/set_unit <item> <unit>` - Set unit\n"
        "`/delete_item <item>` - Delete item\n\n"
        "*Admin:*\n"
        "`/undo` - Undo last action\n"
        "`/reset_day` - Reset day\n"
        "`/backup` - Create backup\n"
        "`/restore` - Restore backup\n"
        "`/export_csv` - Export to CSV\n"
        "`/export_excel` - Export to Excel\n\n"
        "*AI Mode:*\n"
        "Just type naturally!\n"
        "Example: 'used 5 kg rice for biriyani'\n\n"
        "`/cancel` - Cancel current operation\n"
        "`/menu` - Show main menu\n"
        "`/help` - Show this help"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    session["pending_actions"] = []
    context.user_data.clear()

    await update.message.reply_text(
        "Operation cancelled.",
        reply_markup=main_menu_keyboard() if not session.get("locked", True) else None
    )


# ---- Movement Commands ----

async def used_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /used command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: `/used <qty> <unit> <item_name> for <purpose>`\n"
            "Example: `/used 5 kg rice for biriyani`",
            parse_mode="Markdown"
        )
        return

    try:
        qty = float(args[0])
        unit = args[1]

        # Find item and purpose
        remaining = " ".join(args[2:])
        purpose = ""
        if " for " in remaining:
            parts = remaining.split(" for ", 1)
            item_name = parts[0].strip()
            purpose = parts[1].strip()
        else:
            item_name = remaining

        item = find_item(item_name)
        if not item:
            await update.message.reply_text(f"Item '{item_name}' not found.")
            return

        ok, msg, tx_id = process_stock_movement(
            item["item_id"], "used", qty, purpose=purpose,
            performed_by=str(update.effective_user.id)
        )
        await update.message.reply_text(msg)

    except (ValueError, IndexError) as e:
        await update.message.reply_text(f"Invalid format. {str(e)}")


async def purchased_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /purchased command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "purchased")


async def damaged_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /damaged command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "damaged")


async def wipro_in_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wipro_in command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "wipro in")


async def wipro_out_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wipro_out command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "wipro out")


async def rajagiri_main_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rajagiri_main command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "rajagiri main")


async def woods_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /woods command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "woods")


async def garden_cafe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /garden_cafe command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "garden cafe")


async def bba_canteen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bba_canteen command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "bba canteen")


async def bba_tea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bba_tea command."""
    if not await check_unlocked(update):
        return
    await handle_movement_command(update, context, "bba tea counter")


async def handle_movement_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Generic handler for movement commands."""
    args = context.args
    if len(args) < 3:
        cmd = action.replace(" ", "_")
        await update.message.reply_text(
            f"Usage: `/{cmd} <qty> <unit> <item_name>`\n"
            f"Example: `/{cmd} 5 kg rice`",
            parse_mode="Markdown"
        )
        return

    try:
        qty = float(args[0])
        unit = args[1]
        item_name = " ".join(args[2:])

        item = find_item(item_name)
        if not item:
            await update.message.reply_text(f"Item '{item_name}' not found.")
            return

        ok, msg, tx_id = process_stock_movement(
            item["item_id"], action, qty,
            destination=action if action in ["rajagiri main", "woods", "garden cafe", "bba canteen", "bba tea counter"] else "",
            performed_by=str(update.effective_user.id)
        )
        await update.message.reply_text(msg)

    except (ValueError, IndexError):
        await update.message.reply_text("Invalid format. Check /help for usage.")


# ---- Query Commands ----

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/check <item_name>`", parse_mode="Markdown")
        return

    item_name = " ".join(args)
    ok, msg = check_stock(item_name)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def low_stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /low_stock command."""
    if not await check_unlocked(update):
        return

    items = get_low_stock()
    if items:
        lines = ["*Low Stock Items:*\n"]
        for item in items:
            status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("No low stock items.")


async def order_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /order_list command."""
    if not await check_unlocked(update):
        return

    items = get_order()
    if items:
        lines = ["*Order List:*\n"]
        for item in items:
            status = "URGENT" if item["urgent"] else f"{item['days_left']} days left"
            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']} ({status})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("No items need ordering.")


async def daily_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /daily_report command."""
    if not await check_unlocked(update):
        return

    report = generate_daily_report()
    lines = [f"*Daily Report - {report['date']}*\n"]

    if report["used_items"]:
        lines.append("*Used:*")
        for t in report["used_items"]:
            lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']} ({t['purpose']})")
        lines.append("")

    if report["purchased_items"]:
        lines.append("*Purchased:*")
        for t in report["purchased_items"]:
            lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']}")
        lines.append("")

    if report["damaged_items"]:
        lines.append("*Damaged:*")
        for t in report["damaged_items"]:
            lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']}")
        lines.append("")

    if report["wipro_in"]:
        lines.append("*Wipro In:*")
        for t in report["wipro_in"]:
            lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']}")
        lines.append("")

    if report["wipro_out"]:
        lines.append("*Wipro Out:*")
        for t in report["wipro_out"]:
            lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']}")
        lines.append("")

    if report["transfers"]:
        lines.append("*Transfers:*")
        for t in report["transfers"]:
            lines.append(f"- {t['item_name']}: {t['quantity']} {t['unit']} -> {t['action']}")
        lines.append("")

    if report["adjustments"]:
        lines.append("*Adjustments:*")
        for t in report["adjustments"]:
            lines.append(f"- {t['item_name']}: {t['notes']}")
        lines.append("")

    if report["low_stock"]:
        lines.append("*Low Stock:*")
        for item in report["low_stock"]:
            lines.append(f"- {item['item_name']}: {item['current_stock']} {item['unit']}")
        lines.append("")

    lines.append(f"Total transactions today: {report['total_transactions']}")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3990] + "...\n(truncated)"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def list_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list_all command."""
    if not await check_unlocked(update):
        return

    items = get_all_items()
    if items:
        lines = [f"*All Items ({len(items)}):*\n"]
        for item in items:
            lines.append(
                f"- {item['item_name']} ({item['item_id']}): "
                f"{item['current_stock']} {item['unit']}"
            )
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:3990] + "...\n(truncated)"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("No items in inventory.")


async def zero_stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /zero_stock command."""
    if not await check_unlocked(update):
        return

    items = get_zero_stock()
    if items:
        lines = ["*Zero Stock Items:*\n"]
        for item in items:
            lines.append(f"- {item['item_name']} ({item['item_id']})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("No zero stock items.")


# ---- Item Management Commands ----

async def add_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add_item command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/add_item item_id | name | unit | starting_stock | current_stock | avg_usage`\n"
            "Example: `/add_item R001 | Rice | kg | 100 | 100 | 40`",
            parse_mode="Markdown"
        )
        return

    text = " ".join(args)
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Invalid format. Need at least: item_id | name | unit")
        return

    ok, msg = add_single_item(
        item_id=parts[0],
        item_name=parts[1],
        unit=parts[2],
        starting_stock=float(parts[3]) if len(parts) > 3 else 0,
        current_stock=float(parts[4]) if len(parts) > 4 else float(parts[3]) if len(parts) > 3 else 0,
        avg_daily_usage=float(parts[5]) if len(parts) > 5 else 0,
    )
    await update.message.reply_text(msg)


async def set_avg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set_avg command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/set_avg <item> <value>`", parse_mode="Markdown")
        return

    try:
        value = float(args[-1])
        item_name = " ".join(args[:-1])
        item = find_item(item_name)
        if not item:
            await update.message.reply_text(f"Item '{item_name}' not found.")
            return
        ok, msg = set_avg_usage(item["item_id"], value)
        await update.message.reply_text(msg)
    except ValueError:
        await update.message.reply_text("Invalid value. Usage: `/set_avg <item> <number>`", parse_mode="Markdown")


async def set_unit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set_unit command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/set_unit <item> <unit>`", parse_mode="Markdown")
        return

    unit = args[-1]
    item_name = " ".join(args[:-1])
    item = find_item(item_name)
    if not item:
        await update.message.reply_text(f"Item '{item_name}' not found.")
        return
    ok, msg = set_unit(item["item_id"], unit)
    await update.message.reply_text(msg)


async def delete_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /delete_item command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/delete_item <item_id>`", parse_mode="Markdown")
        return

    item_id = " ".join(args)
    ok, msg = delete_single_item(item_id)
    await update.message.reply_text(msg)


# ---- Admin Commands ----

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command."""
    if not await check_unlocked(update):
        return

    ok, msg = undo_action(str(update.effective_user.id))
    await update.message.reply_text(msg)


async def reset_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset_day command."""
    if not await check_unlocked(update):
        return

    ok, msg = do_reset_day(str(update.effective_user.id))
    await update.message.reply_text(msg)


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /backup command."""
    if not await check_unlocked(update):
        return

    ok, msg, filepath = do_backup()
    if ok:
        await update.message.reply_text(f"{msg}\n`{filepath}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(msg)


async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /restore command."""
    if not await check_unlocked(update):
        return

    backups = get_backups()
    if backups:
        lines = ["*Available Backups:*\n"]
        for i, b in enumerate(backups[:10], 1):
            lines.append(f"{i}. `{b['filename'][:50]}`")
        lines.append("\nReply with the number to restore, or send the full path.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        context.user_data["awaiting"] = "restore_select"
    else:
        await update.message.reply_text("No backups found.")


async def export_csv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /export_csv command."""
    if not await check_unlocked(update):
        return

    ok, msg, filepath = do_export_csv()
    if ok:
        await update.message.reply_text(f"{msg}\n`{filepath}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(msg)


async def export_excel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /export_excel command."""
    if not await check_unlocked(update):
        return

    ok, msg, filepath = do_export_excel()
    if ok:
        await update.message.reply_text(f"{msg}\n`{filepath}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(msg)


async def change_secret_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /change_secret command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/change_secret <new_secret_word>`", parse_mode="Markdown")
        return

    new_word = " ".join(args)
    change_secret_word(new_word)
    await update.message.reply_text("Secret word updated successfully.")


# ---- Stock Adjustment Commands ----

async def edit_current_stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /edit_current_stock command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: `/edit_current_stock <item> <value>`", parse_mode="Markdown")
        return

    try:
        value = float(args[-1])
        item_name = " ".join(args[:-1])
        item = find_item(item_name)
        if not item:
            await update.message.reply_text(f"Item '{item_name}' not found.")
            return
        ok, msg, tx_id = change_current_stock(item["item_id"], value)
        await update.message.reply_text(msg)
    except ValueError:
        await update.message.reply_text("Invalid value.")


async def stock_adjustment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stock_adjustment command."""
    if not await check_unlocked(update):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/stock_adjustment <item> <new_stock>`\n"
            "Example: `/stock_adjustment rice 150`",
            parse_mode="Markdown"
        )
        return

    try:
        new_stock = float(args[-1])
        item_name = " ".join(args[:-1])
        item = find_item(item_name)
        if not item:
            await update.message.reply_text(f"Item '{item_name}' not found.")
            return
        ok, msg, tx_id = adjust_stock(item["item_id"], new_stock, str(update.effective_user.id))
        await update.message.reply_text(msg)
    except ValueError:
        await update.message.reply_text("Invalid stock value.")


# ---- Bulk Import Command ----

async def bulk_import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bulk_import command."""
    if not await check_unlocked(update):
        return

    await update.message.reply_text(
        "Send a CSV file or paste CSV content.\n"
        "Required columns: item_id, item_name, unit\n"
        "Optional: starting_stock, current_stock, avg_daily_usage, location, category",
        parse_mode="Markdown"
    )
    context.user_data["awaiting"] = "bulk_import"


# ---- Helper ----

async def check_unlocked(update: Update) -> bool:
    """Check if user has unlocked the bot."""
    user_id = update.effective_user.id
    session = get_session(user_id)
    if session.get("locked", True):
        await update.message.reply_text("Bot is locked. Send `/unlock <secret>` to access.")
        return False
    return True
