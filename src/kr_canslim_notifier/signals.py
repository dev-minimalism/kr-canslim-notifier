"""Pivot breakout signal, shared by the live bot and the backtest.

Both must use these functions so the backtest tests the strategy the bot
actually trades.
"""

from typing import Dict, Optional

import pandas as pd

# Days used for both the resistance (highest high) and the average volume
PIVOT_LOOKBACK_DAYS = 20


def add_pivot_indicators(
    df: pd.DataFrame, lookback: int = PIVOT_LOOKBACK_DAYS
) -> pd.DataFrame:
    """Return a copy of df with Pivot_Resist and Avg_Volume columns.

    Both look only at the previous `lookback` days (today excluded):
    - Pivot_Resist: highest High
    - Avg_Volume: mean Volume
    Rows without a full window are NaN.
    """
    df = df.copy()
    df["Pivot_Resist"] = df["High"].shift(1).rolling(window=lookback).max()
    df["Avg_Volume"] = df["Volume"].shift(1).rolling(window=lookback).mean()
    return df


def check_pivot_breakout(
    close: float,
    volume: float,
    resistance: float,
    avg_volume: float,
    volume_surge_min: float,
    breakout_max: float,
) -> Optional[Dict]:
    """Check one bar for a pivot breakout.

    Breakout: close is above the resistance by more than 0% and at most
    `breakout_max`%, and volume is at least `volume_surge_min`% above average.

    Returns:
        {"breakout_pct", "volume_surge"} as floats, or None.
    """
    if pd.isna(resistance) or pd.isna(avg_volume) or resistance <= 0 or avg_volume <= 0:
        return None

    volume_surge = (volume / avg_volume - 1) * 100
    breakout_pct = (close - resistance) / resistance * 100

    if volume_surge >= volume_surge_min and 0 < breakout_pct <= breakout_max:
        return {"breakout_pct": float(breakout_pct), "volume_surge": float(volume_surge)}
    return None
