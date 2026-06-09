"""
Configuration module for Prometheus.
Loads environment variables and provides centralized config access.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Access Control
    SECRET_WORD: str = os.getenv("SECRET_WORD", "prometheus")

    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "prometheus.db")

    # Business Logic
    REORDER_DAYS: int = int(os.getenv("REORDER_DAYS", "3"))

    # Webhook (optional)
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))

    # Daily Report Scheduler
    DAILY_REPORT_CHAT_ID: str = os.getenv("DAILY_REPORT_CHAT_ID", "")
    DAILY_REPORT_TIME: str = os.getenv("DAILY_REPORT_TIME", "20:30")  # HH:MM 24h IST

    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def daily_report_enabled(self) -> bool:
        return bool(self.DAILY_REPORT_CHAT_ID)

    def validate(self) -> list[str]:
        """Validate required configuration. Returns list of missing fields."""
        missing = []
        if not self.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.SECRET_WORD:
            missing.append("SECRET_WORD")
        return missing


# Global config instance
config = Config()
