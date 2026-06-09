"""
Prometheus - Telegram Inventory Bot
Main entry point.
"""

import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from app.config import config
from db.database import init_db

from handlers.command_handler import (
    start_command, unlock_command, lock_command, menu_command, help_command, cancel_command,
    used_command, purchased_command, damaged_command,
    wipro_in_command, wipro_out_command,
    rajagiri_main_command, woods_command, garden_cafe_command,
    bba_canteen_command, bba_tea_command,
    check_command, low_stock_command, order_list_command,
    daily_report_command, list_all_command, zero_stock_command,
    add_item_command, set_avg_command, set_unit_command, delete_item_command,
    undo_command, reset_day_command, backup_command, restore_command,
    export_csv_command, export_excel_command, change_secret_command,
    edit_current_stock_command, stock_adjustment_command, bulk_import_command,
)
from handlers.callback_handler import handle_callback
from handlers.message_handler import handle_message, handle_document

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def setup_handlers(application: Application):
    """Register all command and message handlers."""

    # Start & Access
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("unlock", unlock_command))
    application.add_handler(CommandHandler("lock", lock_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # Stock Movements
    application.add_handler(CommandHandler("used", used_command))
    application.add_handler(CommandHandler("purchased", purchased_command))
    application.add_handler(CommandHandler("damaged", damaged_command))
    application.add_handler(CommandHandler("wipro_in", wipro_in_command))
    application.add_handler(CommandHandler("wipro_out", wipro_out_command))
    application.add_handler(CommandHandler("rajagiri_main", rajagiri_main_command))
    application.add_handler(CommandHandler("woods", woods_command))
    application.add_handler(CommandHandler("garden_cafe", garden_cafe_command))
    application.add_handler(CommandHandler("bba_canteen", bba_canteen_command))
    application.add_handler(CommandHandler("bba_tea", bba_tea_command))

    # Queries & Reports
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("low_stock", low_stock_command))
    application.add_handler(CommandHandler("order_list", order_list_command))
    application.add_handler(CommandHandler("daily_report", daily_report_command))
    application.add_handler(CommandHandler("list_all", list_all_command))
    application.add_handler(CommandHandler("zero_stock", zero_stock_command))

    # Item Management
    application.add_handler(CommandHandler("add_item", add_item_command))
    application.add_handler(CommandHandler("set_avg", set_avg_command))
    application.add_handler(CommandHandler("set_unit", set_unit_command))
    application.add_handler(CommandHandler("delete_item", delete_item_command))
    application.add_handler(CommandHandler("edit_current_stock", edit_current_stock_command))
    application.add_handler(CommandHandler("stock_adjustment", stock_adjustment_command))
    application.add_handler(CommandHandler("bulk_import", bulk_import_command))

    # Admin
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(CommandHandler("reset_day", reset_day_command))
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CommandHandler("restore", restore_command))
    application.add_handler(CommandHandler("export_csv", export_csv_command))
    application.add_handler(CommandHandler("export_excel", export_excel_command))
    application.add_handler(CommandHandler("change_secret", change_secret_command))

    # Callback queries (buttons)
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Documents (CSV upload)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Text messages (catch-all for AI mode and state handling)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


def main():
    """Start the bot."""
    # Validate config
    missing = config.validate()
    if missing:
        logger.error(f"Missing required config: {', '.join(missing)}")
        print(f"Error: Missing required configuration: {', '.join(missing)}")
        print("Please check your .env file.")
        sys.exit(1)

    # Initialize database
    logger.info("Initializing database...")
    init_db()
    logger.info("Database ready.")

    # Build application
    logger.info("Starting Prometheus bot...")
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    setup_handlers(application)

    # Start polling
    logger.info("Bot is running (polling mode). Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
