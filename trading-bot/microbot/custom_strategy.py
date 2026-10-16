"""Plug your existing Pi bot's entry rule in here to compare it head-to-head.

1. Copy the buy condition from your Pi bot into `pi_bot_signal` below. It gets
   one stock's daily bars (columns: open, high, low, close, volume, one row per
   day) and must return a True/False Series: True on day t means "buy at the
   open of day t+1". Only use data up to day t (no .shift(-1)!).
2. Set the stop / target / hold settings to what your Pi bot uses.
3. Set ENABLED = True and run:  python backtest.py --strategies pi_bot rsi2_dip buy_hold
"""
from __future__ import annotations

import pandas as pd

from .strategies import Strategy, sma

ENABLED = False


def pi_bot_signal(df: pd.DataFrame) -> pd.Series:
    # EXAMPLE ONLY - replace with your Pi bot's rule.
    close = df["close"]
    return close > sma(close, 10)


def strategies() -> list:
    if not ENABLED:
        return []
    return [
        Strategy(
            name="pi_bot",
            signal=pi_bot_signal,
            intraday=False,       # True if your bot always closes by end of day
            max_hold_days=5,
            stop_loss=0.02,       # fraction, e.g. 0.02 = 2%; None for no stop
            take_profit=0.01,
            max_positions=3,
            description="Existing Raspberry Pi bot",
        )
    ]
