"""Configuration settings loaded from environment variables."""

import os

from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Settings:
    """Application settings from environment variables."""

    # Telegram
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    CHAT_ID: str = os.getenv("CHAT_ID", "")

    # Scan settings
    SCAN_INTERVAL: int = int(os.getenv("SCAN_INTERVAL", "1800"))

    # Pattern detection
    VOLUME_SURGE_MIN: int = int(os.getenv("VOLUME_SURGE_MIN", "50"))
    BREAKOUT_MAX: int = int(os.getenv("BREAKOUT_MAX", "5"))

    # Risk management
    STOP_LOSS_PERCENT: float = float(os.getenv("STOP_LOSS_PERCENT", "-7.5"))

    # Data settings
    ANALYSIS_PERIOD_DAYS: int = int(os.getenv("ANALYSIS_PERIOD_DAYS", "120"))

    # Watchlist file
    WATCHLIST_FILE: str = os.getenv("WATCHLIST_FILE", "watchlist.json")

    @classmethod
    def is_configured(cls) -> bool:
        """Check if required settings are configured."""
        return bool(
            cls.TELEGRAM_TOKEN
            and cls.TELEGRAM_TOKEN != "YOUR_BOT_TOKEN_HERE"
            and cls.CHAT_ID
        )


settings = Settings()
