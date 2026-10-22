"""Backtest configuration loaded from environment variables."""

import json
import os
from dataclasses import dataclass, field
from typing import List

from ..settings import settings
from ..signals import PIVOT_LOOKBACK_DAYS


def load_watchlist_tickers(path: str = settings.WATCHLIST_FILE) -> List[str]:
    """Load tickers from watchlist.json ({"tickers": [...]} or legacy {"kr": [...]})."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tickers") or data.get("kr") or []
    except Exception as e:
        print(f"⚠️  Failed to load watchlist: {e}")
        return []


@dataclass
class BacktestConfig:
    """Pivot breakout backtest parameters."""

    # Period (YYYY-MM-DD)
    start_date: str = os.getenv("BACKTEST_START_DATE", "2024-01-01")
    end_date: str = os.getenv("BACKTEST_END_DATE", "2024-12-31")

    # Capital
    initial_capital: float = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "10000000"))
    position_size_pct: float = float(os.getenv("BACKTEST_POSITION_SIZE_PCT", "0.1"))

    # Strategy (percent values, same units as the live bot). Defaults match the
    # bot; overriding them tests a different strategy than the bot trades.
    lookback_period: int = int(os.getenv("BACKTEST_LOOKBACK_PERIOD", PIVOT_LOOKBACK_DAYS))
    volume_surge_pct: float = float(settings.VOLUME_SURGE_MIN)
    breakout_pct_max: float = float(settings.BREAKOUT_MAX)

    # Risk management (fractions)
    stop_loss_pct: float = float(os.getenv("BACKTEST_STOP_LOSS_PCT", "0.08"))
    take_profit_pct: float = float(os.getenv("BACKTEST_TAKE_PROFIT_PCT", "0.20"))
    holding_days_max: int = int(os.getenv("BACKTEST_HOLDING_DAYS_MAX", "30"))

    tickers: List[str] = field(default_factory=load_watchlist_tickers)


default_config = BacktestConfig()
