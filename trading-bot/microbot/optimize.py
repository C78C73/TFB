"""Stop-loss / take-profit sweeps, year by year, plus an honest walk-forward test.

Picking the best stop/target *after* seeing a year's data always looks great
and is mostly luck. The walk-forward test only lets year Y use the settings
that did best on the years before Y, which is what you'd actually experience.
"""
from __future__ import annotations

import itertools
from typing import Iterable, Optional

import pandas as pd

from . import config
from .backtest import Prepared, prepare, run, year_windows
from .strategies import Strategy


def per_year(
    prep: Prepared, strategy: Strategy, years: list, stop_loss="default", take_profit="default", **kw
) -> list:
    rows = []
    for year, start, end in years:
        m = run(prep, strategy, start, end, stop_loss=stop_loss, take_profit=take_profit, **kw).metrics()
        m["year"] = year
        rows.append(m)
    return rows


def sweep(
    prep: Prepared,
    strategy: Strategy,
    years: list,
    stop_grid: Iterable[Optional[float]] = config.STOP_LOSS_GRID,
    target_grid: Iterable[Optional[float]] = config.TAKE_PROFIT_GRID,
    **kw,
) -> pd.DataFrame:
    """Every (stop, target) pair, every year. One row per (pair, year)."""
    stops, targets = list(stop_grid), list(target_grid)
    # always include the strategy's own defaults so walk-forward has a year-1 pick
    if strategy.stop_loss not in stops:
        stops.append(strategy.stop_loss)
    if strategy.take_profit not in targets:
        targets.append(strategy.take_profit)
    rows = []
    for sl, tp in itertools.product(stops, targets):
        rows.extend(per_year(prep, strategy, years, stop_loss=sl, take_profit=tp, **kw))
    return pd.DataFrame(rows)


def _pick_best(history: pd.DataFrame) -> tuple:
    """Best pair on past years: highest total profit, then Sharpe, then smaller stop."""
    g = history.groupby(["stop_loss", "take_profit"], dropna=False).agg(
        profit=("profit", "sum"), sharpe=("sharpe", "mean")
    ).reset_index()
    g = g.sort_values(["profit", "sharpe", "stop_loss"], ascending=[False, False, True])
    best = g.iloc[0]
    sl = None if pd.isna(best["stop_loss"]) else float(best["stop_loss"])
    tp = None if pd.isna(best["take_profit"]) else float(best["take_profit"])
    return sl, tp


def walk_forward(grid: pd.DataFrame, strategy: Strategy) -> pd.DataFrame:
    """For each year after the first, use the pair that won on all earlier years."""
    years = sorted(grid["year"].unique())
    rows = []
    for idx, year in enumerate(years):
        if idx == 0:
            sl, tp = strategy.stop_loss, strategy.take_profit   # no history yet: defaults
            chosen = "default"
        else:
            sl, tp = _pick_best(grid[grid["year"].isin(years[:idx])])
            chosen = "trained on " + ",".join(str(y) for y in years[:idx])
        match = grid[(grid["year"] == year)
                     & _eq(grid["stop_loss"], sl) & _eq(grid["take_profit"], tp)]
        if match.empty:  # defaults may sit outside the grid
            continue
        row = match.iloc[0].to_dict()
        row["params_from"] = chosen
        rows.append(row)
    return pd.DataFrame(rows)


def _eq(col: pd.Series, value: Optional[float]) -> pd.Series:
    if value is None:
        return col.isna()
    return (col - value).abs() < 1e-12


def best_in_hindsight(grid: pd.DataFrame) -> pd.DataFrame:
    """Best pair per year chosen with hindsight (optimistic - for reference only)."""
    idx = grid.groupby("year")["profit"].idxmax()
    return grid.loc[idx].reset_index(drop=True)


def robust_pairs(grid: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """Pairs ranked across ALL years: total profit, worst year, years profitable."""
    g = grid.groupby(["stop_loss", "take_profit"], dropna=False).agg(
        total_profit=("profit", "sum"),
        worst_year=("profit", "min"),
        years_profitable=("profit", lambda s: int((s > 0).sum())),
        years=("profit", "size"),
        avg_per_day=("avg_per_day", "mean"),
        avg_max_dd_pct=("max_drawdown_pct", "mean"),
        trades=("trades", "sum"),
    ).reset_index()
    return g.sort_values(["years_profitable", "total_profit"], ascending=False).head(top)


def prepare_all(bars: dict, strategies: dict) -> dict:
    return {name: prepare(bars, strat) for name, strat in strategies.items()}


def windows_for(prep: Prepared, first_year: int, last_year: Optional[int] = None) -> list:
    return year_windows(prep.dates, first_year, last_year)
