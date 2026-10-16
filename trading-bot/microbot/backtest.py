"""Daily-bar portfolio backtester with stop-loss / take-profit / time exits.

Fill rules (deliberately conservative):
  * A signal on day t's close is bought at day t+1's open (+ slippage).
  * If a stock gaps through the stop or target at the open, it fills at the open.
  * If one day's range touches BOTH the stop and the target, we assume the stop
    hit first, because daily bars can't tell us which came first.
  * Intraday strategies are always closed at that day's close; swing trades
    close at the close once they've been held max_hold_days.
  * Everything still open on the last day of the test window is sold at that
    close, so each year is scored on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
import pandas as pd

from . import config
from .strategies import Strategy


@dataclass
class Prepared:
    """Bars and signals aligned on one calendar so many runs can reuse them."""
    dates: pd.DatetimeIndex
    symbols: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    signal: np.ndarray   # bool, signal at day t's close
    rank: np.ndarray     # float, higher = preferred


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    reason: str


@dataclass
class Result:
    strategy: str
    start: pd.Timestamp
    end: pd.Timestamp
    equity: pd.Series
    trades: list
    stop_loss: Optional[float]
    take_profit: Optional[float]
    starting_capital: float
    daily_target: float

    def metrics(self) -> dict:
        eq = self.equity
        start_cap = self.starting_capital
        days = len(eq)
        profit = float(eq.iloc[-1] - start_cap) if days else 0.0
        daily_pnl = eq.diff().fillna(eq.iloc[0] - start_cap) if days else eq
        rets = eq.pct_change().fillna(eq.iloc[0] / start_cap - 1) if days else eq
        peak = eq.cummax()
        max_dd = float(((eq - peak) / peak).min()) if days else 0.0
        std = float(rets.std())
        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        return {
            "strategy": self.strategy,
            "year": self.start.year if self.start.year == self.end.year else f"{self.start.year}-{self.end.year}",
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "start": self.start.date().isoformat(),
            "end": self.end.date().isoformat(),
            "trading_days": days,
            "final_equity": round(float(eq.iloc[-1]), 2) if days else start_cap,
            "profit": round(profit, 2),
            "return_pct": round(100 * profit / start_cap, 2),
            "avg_per_day": round(profit / days, 3) if days else 0.0,
            "days_hit_target_pct": round(100 * float((daily_pnl >= self.daily_target).mean()), 1) if days else 0.0,
            "losing_days_pct": round(100 * float((daily_pnl < 0).mean()), 1) if days else 0.0,
            "worst_day": round(float(daily_pnl.min()), 2) if days else 0.0,
            "trades": len(pnls),
            "win_rate_pct": round(100 * len(wins) / len(pnls), 1) if pnls else 0.0,
            "avg_trade": round(float(np.mean(pnls)), 3) if pnls else 0.0,
            "max_drawdown_pct": round(100 * max_dd, 2),
            "sharpe": round(float(rets.mean() / std * np.sqrt(252)), 2) if std > 0 else 0.0,
        }


def prepare(bars: dict, strategy: Strategy) -> Prepared:
    """Align every symbol on the union of trading days and compute signals once."""
    symbols = sorted(bars)
    if not symbols:
        raise ValueError("no bars to backtest")
    dates = pd.DatetimeIndex(sorted(set().union(*[df.index for df in bars.values()])))

    def grid(col: str) -> np.ndarray:
        return np.column_stack([bars[s][col].reindex(dates).to_numpy(dtype=float) for s in symbols])

    sig_cols, rank_cols = [], []
    for s in symbols:
        df = bars[s]
        sig = strategy.signal(df).reindex(dates)
        sig_cols.append(sig.where(sig.notna(), False).to_numpy(dtype=bool))
        if strategy.rank is not None:
            rank = strategy.rank(df).reindex(dates)
            rank_cols.append(rank.fillna(-np.inf).to_numpy(dtype=float))
        else:
            rank_cols.append(np.zeros(len(dates)))

    return Prepared(
        dates=dates, symbols=symbols,
        open=grid("open"), high=grid("high"), low=grid("low"), close=grid("close"),
        signal=np.column_stack(sig_cols), rank=np.column_stack(rank_cols),
    )


def run(
    prep: Prepared,
    strategy: Strategy,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    stop_loss: Optional[float] = "default",   # type: ignore[assignment]
    take_profit: Optional[float] = "default",  # type: ignore[assignment]
    starting_capital: float = config.STARTING_CAPITAL,
    slippage: float = config.SLIPPAGE_PCT,
    sec_fee: float = config.SEC_FEE_RATE,
    daily_target: float = config.DAILY_PROFIT_TARGET,
    min_order: float = 1.0,
) -> Result:
    """Simulate one strategy over [start, end] (inclusive)."""
    sl = strategy.stop_loss if stop_loss == "default" else stop_loss
    tp = strategy.take_profit if take_profit == "default" else take_profit
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    in_window = (prep.dates >= start) & (prep.dates <= end)
    day_idx = np.flatnonzero(in_window)
    n_sym = len(prep.symbols)
    slots = max(1, min(strategy.max_positions, n_sym))

    cash = float(starting_capital)
    # open positions: col -> dict(shares, entry, stop, target, entry_i)
    positions: dict[int, dict] = {}
    trades: list[Trade] = []
    equity_vals: list[float] = []
    last_close = np.full(n_sym, np.nan)
    prev_equity = cash

    def sell(col: int, i: int, raw_price: float, reason: str) -> None:
        nonlocal cash
        pos = positions.pop(col)
        fill = raw_price * (1 - slippage)
        gross = pos["shares"] * fill
        fee = gross * sec_fee
        cash += gross - fee
        trades.append(Trade(
            symbol=prep.symbols[col], entry_date=prep.dates[pos["entry_i"]], exit_date=prep.dates[i],
            entry_price=pos["entry"], exit_price=fill, shares=pos["shares"],
            pnl=gross - fee - pos["cost"], reason=reason,
        ))

    for k, i in enumerate(day_idx):
        o, h, l, c = prep.open[i], prep.high[i], prep.low[i], prep.close[i]

        # 1) entries at today's open from yesterday's signals (never before window start)
        if i > 0 and len(positions) < slots:
            prev = i - 1
            cand = [
                col for col in range(n_sym)
                if prep.signal[prev, col] and col not in positions and np.isfinite(o[col]) and o[col] > 0
            ]
            cand.sort(key=lambda col: prep.rank[prev, col], reverse=True)
            for col in cand:
                if len(positions) >= slots:
                    break
                notional = min(prev_equity / slots, cash)
                if notional < min_order:
                    break
                fill = o[col] * (1 + slippage)
                shares = notional / fill
                cash -= notional
                positions[col] = {
                    "shares": shares, "entry": fill, "cost": notional, "entry_i": i,
                    "stop": fill * (1 - sl) if sl is not None else None,
                    "target": fill * (1 + tp) if tp is not None else None,
                }

        # 2) exits during the day
        last_day = k == len(day_idx) - 1
        for col in list(positions):
            if not np.isfinite(c[col]):
                continue  # no bar today (halt / missing data)
            pos = positions[col]
            stop, target = pos["stop"], pos["target"]
            entered_today = pos["entry_i"] == i
            if not entered_today and stop is not None and o[col] <= stop:
                sell(col, i, o[col], "stop_gap")
            elif not entered_today and target is not None and o[col] >= target:
                sell(col, i, o[col], "target_gap")
            elif stop is not None and l[col] <= stop:
                sell(col, i, stop, "stop")          # assume stop first if both touched
            elif target is not None and h[col] >= target:
                sell(col, i, target, "target")
            elif strategy.intraday:
                sell(col, i, c[col], "close")
            elif i - pos["entry_i"] >= strategy.max_hold_days:
                sell(col, i, c[col], "time")
            elif last_day:
                sell(col, i, c[col], "end_of_test")

        # 3) mark to market
        last_close = np.where(np.isfinite(c), c, last_close)
        held = sum(p["shares"] * last_close[col] for col, p in positions.items())
        prev_equity = cash + held
        equity_vals.append(prev_equity)

    # anything left (only possible if its final bar was missing) at last known price
    if positions and len(day_idx):
        i = day_idx[-1]
        for col in list(positions):
            sell(col, i, float(last_close[col]), "end_of_test")
        equity_vals[-1] = cash

    equity = pd.Series(equity_vals, index=prep.dates[day_idx], dtype=float)
    return Result(
        strategy=strategy.name, start=start, end=end, equity=equity, trades=trades,
        stop_loss=sl, take_profit=tp, starting_capital=starting_capital, daily_target=daily_target,
    )


def year_windows(dates: pd.DatetimeIndex, first_year: int, last_year: Optional[int] = None) -> list:
    """(year, start, end) for each calendar year that has data."""
    last_year = last_year or int(dates[-1].year)
    out = []
    for year in range(first_year, last_year + 1):
        in_year = dates[(dates.year == year)]
        if len(in_year):
            out.append((year, in_year[0], in_year[-1]))
    return out


def with_params(strategy: Strategy, **kwargs) -> Strategy:
    return replace(strategy, **kwargs)
