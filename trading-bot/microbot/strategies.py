"""Entry rules. Exits (stop-loss / take-profit / time) live in the backtester.

A signal on day t is computed from data up to and including t's close, and the
trade is entered at day t+1's open, so there is no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame], pd.Series]


@dataclass
class Strategy:
    name: str
    signal: SignalFn                      # bars -> bool Series ("buy tomorrow at the open")
    rank: Optional[SignalFn] = None       # higher = preferred when slots are scarce
    intraday: bool = False                # True = always flat by the close (day trade)
    max_hold_days: int = 5                # time stop for swing trades
    stop_loss: Optional[float] = 0.02     # fraction below entry, None = no stop
    take_profit: Optional[float] = 0.01   # fraction above entry, None = no target
    max_positions: int = 3
    description: str = ""
    tags: list = field(default_factory=list)


# ---------------------------------------------------------------- indicators
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 2) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


# ---------------------------------------------------------------- strategies
def _rsi2_signal(df: pd.DataFrame) -> pd.Series:
    """Connors-style dip buy: long-term uptrend, but sharply oversold short-term."""
    return (df["close"] > sma(df["close"], 200)) & (rsi(df["close"], 2) < 10)


def _rsi2_rank(df: pd.DataFrame) -> pd.Series:
    return -rsi(df["close"], 2)          # most oversold first


def _trend_scalp_signal(df: pd.DataFrame) -> pd.Series:
    """Day-trade blue chips that are in a short- and long-term uptrend."""
    c = df["close"]
    return (c > sma(c, 20)) & (sma(c, 20) > sma(c, 50))


def _trend_scalp_rank(df: pd.DataFrame) -> pd.Series:
    return df["close"] / sma(df["close"], 20)


def _pullback_signal(df: pd.DataFrame) -> pd.Series:
    """Uptrend + a red day closing near its low -> expect a small bounce."""
    c = df["close"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    near_low = (c - df["low"]) / rng < 0.25
    return (c > sma(c, 50)) & (c < c.shift(1)) & near_low


def _always(df: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=df.index)


def builtin_strategies() -> dict[str, Strategy]:
    return {
        "rsi2_dip": Strategy(
            name="rsi2_dip", signal=_rsi2_signal, rank=_rsi2_rank,
            intraday=False, max_hold_days=5, stop_loss=0.03, take_profit=0.015,
            description="Buy oversold dips (RSI2<10) in uptrends; hold up to 5 days",
        ),
        "trend_scalp": Strategy(
            name="trend_scalp", signal=_trend_scalp_signal, rank=_trend_scalp_rank,
            intraday=True, max_hold_days=0, stop_loss=0.0075, take_profit=0.005,
            description="Buy at the open, small TP/SL, always flat by the close",
        ),
        "pullback_bounce": Strategy(
            name="pullback_bounce", signal=_pullback_signal, rank=_rsi2_rank,
            intraday=False, max_hold_days=3, stop_loss=0.02, take_profit=0.01,
            description="Buy the day after a red close near the low; hold up to 3 days",
        ),
        "buy_hold": Strategy(
            name="buy_hold", signal=_always, intraday=False, max_hold_days=10**9,
            stop_loss=None, take_profit=None, max_positions=10**6,
            description="Benchmark: equal-weight the whole list on day 1 and hold",
            tags=["benchmark"],
        ),
    }


def all_strategies() -> dict[str, Strategy]:
    """Built-ins plus whatever is defined in custom_strategy.py (your Pi bot)."""
    strategies = builtin_strategies()
    try:
        from . import custom_strategy
        for strat in custom_strategy.strategies():
            strategies[strat.name] = strat
    except ImportError:
        pass
    return strategies
