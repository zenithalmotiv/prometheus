# Prometheus V1 - Canteen Inventory Bot

A Telegram-based inventory management system for Rajagiri canteen, designed for fast daily use on Android phones. Supports buttons, commands, and AI-powered natural language understanding.

## Features

- **Hybrid Interaction**: Buttons for daily workflow, commands for speed, AI for natural language
- **Full Stock Management**: All movement types (used, purchased, damaged, transfers, adjustments)
- **Smart Reordering**: 3-day reorder rule with low stock alerts
- **Daily Reports**: Complete end-of-day transaction summaries with optional auto-send scheduler
- **Undo Support**: Safely reverse the last stock-affecting action (restores stock and daily counters)
- **Backup & Restore**: Database snapshots with safety backups
- **Bulk Import/Export**: CSV and Excel support
- **Secret-Word Access**: Simple, secure access control
- **AI Mode**: Optional Gemini-powered natural language understanding

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings:
# - TELEGRAM_BOT_TOKEN (from @BotFather)
# - SECRET_WORD (for bot access)
# - GEMINI_API_KEY (optional, for AI mode)
# - DAILY_REPORT_CHAT_ID (optional, for auto daily report)
```

### 3. Run the Bot

```bash
python bot.py
```

The bot will start in polling mode and create the SQLite database automatically.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from @BotFather |
| `SECRET_WORD` | Yes | `prometheus` | Secret word to unlock the bot |
| `GEMINI_API_KEY` | No | - | Google Gemini API key for AI mode |
| `DATABASE_PATH` | No | `prometheus.db` | SQLite database file path |
| `REORDER_DAYS` | No | `3` | Reorder threshold in days |
| `DAILY_REPORT_CHAT_ID` | No | - | Telegram chat/group ID to send daily report to |
| `DAILY_REPORT_TIME` | No | `20:30` | Time to send daily report (HH:MM, 24h IST) |
| `ENVIRONMENT` | No | `development` | dev/prod environment |

## Usage

### Unlock the Bot

```
/unlock <your_secret_word>
```

### Main Menu

```
/menu
```

### Stock Movements (Commands)

```
/used 5 kg rice for biriyani
/purchased 25 kg sugar
/damaged 2 kg onion
/wipro_in 3 L oil
/wipro_out 1 kg jeera
/rajagiri_main 2 kg chicken
/woods 2 kg chicken
/garden_cafe 5 kg potato
/bba_canteen 1 kg butter
/bba_tea 500 g sugar
```

### Queries

```
/check rice
/low_stock
/order_list
/daily_report
/list_all
/zero_stock
```

### Item Management

```
/add_item R001 | Rice | kg | 100 | 100 | 40
/set_avg rice 35
/set_unit oil L
/delete_item R001
```

### Admin

```
/undo
/reset_day
/backup
/restore
/export_csv
/export_excel
/change_secret new_secret
```

### AI Natural Language

Just type naturally! The bot will understand and ask for confirmation before making changes:

```
We used around 5 kilos of rice today for biriyani, please update it
Send 2 kg sugar to Woods and check whether rice needs ordering
I think 3 packets got damaged, maybe the atta one
What all should we buy for the next three days?
```

## Button Workflow

The bot provides an intuitive menu system:

1. **Add Movement** - Select action type, then item, then quantity
2. **Reports** - View stock status, low stock, daily reports
3. **Inventory** - Add, edit, delete items, manage purposes
4. **Admin** - Lock/unlock, undo, backup, export, reset day

## Database Schema

### Items Table
- `item_id`, `item_name`, `unit`, `starting_stock`, `current_stock`
- `used`, `purpose`, `wipro_in`, `wipro_out`
- `rajagiri_main`, `woods`, `garden_cafe`, `bba_canteen`, `bba_tea_counter`
- `purchased`, `damaged`, `avg_daily_usage`
- `location`, `category`, `last_updated`, `last_updated_by`, `working_date`

### Transactions Table
Complete audit log of every stock movement.

### Purposes Table
Predefined usage purposes (biriyani, meals, sambar, etc.)

### Settings Table
Configuration: secret word, reorder days, working date.

### Undo Log Table
Reversible action history for undo support.

## Running Tests

```bash
python -m pytest tests/ -v
```

Or run individual test files:

```bash
python tests/test_database.py
python tests/test_ai_service.py
python tests/test_helpers.py
```

## Bulk Import (CSV)

Upload a CSV file or paste CSV content with columns:
- Required: `item_id`, `item_name`, `unit`
- Optional: `starting_stock`, `current_stock`, `avg_daily_usage`, `location`, `category`

## Backup & Restore

Backups are stored in the `backups/` directory. Each restore creates a safety backup of the current state before overwriting.

## Daily Auto-Report

To enable automatic end-of-day reports, set `DAILY_REPORT_CHAT_ID` in your `.env`:

```env
DAILY_REPORT_CHAT_ID=123456789
DAILY_REPORT_TIME=20:30
```

Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot) on Telegram. For group chats, add the bot to the group and use the group's chat ID (starts with `-`).

## Architecture

```
prometheus/
├── app/              # Configuration
├── bot.py            # Main entry point + scheduler
├── db/               # Database layer (SQLite)
├── handlers/         # Telegram handlers (commands, callbacks, messages)
├── models/           # Data models
├── services/         # Business logic (inventory, AI)
├── utils/            # Helper utilities
├── tests/            # Unit tests
├── .env.example      # Environment template
├── requirements.txt  # Dependencies
└── seed_items.csv    # Sample inventory data
```

## AI Mode

AI mode uses Google Gemini for natural language understanding. It is **optional** - if disabled, buttons and commands work fully.

- Set `GEMINI_API_KEY` in `.env` to enable
- AI never silently changes stock - confirmation is always required
- Falls back to rule-based parsing if Gemini is unavailable

## License

MIT
