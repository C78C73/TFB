#!/usr/bin/env python3
"""Backtest the micro blue-chip strategies one calendar year at a time.

Examples:
  python backtest.py                          # defaults, every year 2020 -> now
  python backtest.py --optimize               # sweep stop-loss / take-profit grid
  python backtest.py --strategies rsi2_dip pi_bot buy_hold --optimize
  python backtest.py --csv-dir ~/my_bars      # use your own CSVs instead of Alpaca
  python backtest.py --synthetic              # FAKE data, just to check it runs
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from microbot import config, optimize
from microbot.backtest import prepare, run
from microbot.data import get_bars, read_csv
from microbot.strategies import all_strategies

RESULTS = Path(__file__).resolve().parent / "results"
SHOW = ["strategy", "year", "stop_loss", "take_profit", "profit", "return_pct", "avg_per_day",
        "days_hit_target_pct", "worst_day", "trades", "win_rate_pct", "max_drawdown_pct", "sharpe"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategies", nargs="+", help="names to run (default: all)")
    p.add_argument("--symbols", nargs="+", default=config.BLUE_CHIPS)
    p.add_argument("--first-year", type=int, default=config.FIRST_YEAR)
    p.add_argument("--last-year", type=int, default=date.today().year)
    p.add_argument("--capital", type=float, default=config.STARTING_CAPITAL)
    p.add_argument("--target", type=float, default=config.DAILY_PROFIT_TARGET, help="$/day goal")
    p.add_argument("--slippage", type=float, default=config.SLIPPAGE_PCT)
    p.add_argument("--optimize", action="store_true", help="sweep stop-loss / take-profit grid")
    p.add_argument("--refresh", action="store_true", help="re-download data")
    p.add_argument("--csv-dir", help="folder of SYMBOL.csv files (date,open,high,low,close,volume)")
    p.add_argument("--synthetic", action="store_true", help="FAKE random data (testing only)")
    p.add_argument("--out", default=str(RESULTS))
    return p.parse_args(argv)


def load(args) -> dict:
    # one year of warm-up so 200-day averages exist on Jan 1 of the first year
    warmup = f"{args.first_year - 1}-01-01"
    end = f"{args.last_year}-12-31"
    if args.synthetic:
        from microbot.synthetic import fake_bars
        print("!! SYNTHETIC RANDOM DATA - results mean nothing about real markets !!")
        return fake_bars(args.symbols, start=warmup, end=min(end, date.today().isoformat()))
    if args.csv_dir:
        bars = {}
        for s in args.symbols:
            path = Path(args.csv_dir) / f"{s}.csv"
            if path.exists():
                bars[s] = read_csv(path).loc[warmup:end]
            else:
                print(f"[data] {path} missing; skipping {s}")
        return bars
    return get_bars(args.symbols, warmup, None, refresh=args.refresh)


def fmt(df: pd.DataFrame) -> str:
    df = df.copy()
    for col in ("stop_loss", "take_profit"):
        if col in df:
            df[col] = df[col].map(lambda v: "none" if pd.isna(v) else f"{100 * v:.2g}%")
    return df.to_string(index=False)


def main(argv=None) -> int:
    args = parse_args(argv)
    strategies = all_strategies()
    names = args.strategies or list(strategies)
    unknown = [n for n in names if n not in strategies]
    if unknown:
        print(f"Unknown strategies {unknown}. Available: {list(strategies)}")
        return 2

    bars = load(args)
    if not bars:
        print("No data loaded.")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    kw = dict(starting_capital=args.capital, slippage=args.slippage, daily_target=args.target)

    summary, wf_all, years_all = [], [], []
    for name in names:
        strat = strategies[name]
        prep = prepare(bars, strat)
        years = optimize.windows_for(prep, args.first_year, args.last_year)
        if not years:
            print(f"No data in {args.first_year}-{args.last_year}")
            return 1
        full_start, full_end = years[0][1], years[-1][2]
        print(f"\n=== {name}: {strat.description}")

        rows = pd.DataFrame(optimize.per_year(prep, strat, years, **kw))
        rows["mode"] = "default params"
        years_all.append(rows)
        print(fmt(rows[SHOW]))
        whole = run(prep, strat, full_start, full_end, **kw).metrics()
        whole.update(mode="default params, whole period")
        summary.append(whole)

        if args.optimize and "benchmark" not in strat.tags:
            grid = optimize.sweep(prep, strat, years, **kw)
            grid.to_csv(out / f"grid_{name}.csv", index=False)
            print(f"\n--- most consistent stop/target pairs across {len(years)} years")
            print(optimize.robust_pairs(grid).to_string(index=False))
            wf = optimize.walk_forward(grid, strat)
            if not wf.empty:
                print("\n--- walk-forward (each year uses only earlier years to pick stop/target)")
                print(fmt(wf[SHOW + ["params_from"]]))
                wf["mode"] = "walk-forward"
                wf_all.append(wf)
                summary.append({
                    "strategy": name, "mode": "walk-forward total",
                    "profit": round(wf["profit"].sum(), 2),
                    "avg_per_day": round(wf["profit"].sum() / wf["trading_days"].sum(), 3),
                    "years_profitable": int((wf["profit"] > 0).sum()),
                    "years": len(wf),
                })

    print("\n================ COMPARISON (starting capital "
          f"${args.capital:,.0f} each year, goal ${args.target:.2f}/day) ================")
    cols = ["strategy", "mode", "profit", "return_pct", "avg_per_day", "days_hit_target_pct",
            "trades", "win_rate_pct", "max_drawdown_pct", "sharpe", "years_profitable", "years"]
    s = pd.DataFrame(summary)
    print(s[[c for c in cols if c in s]].to_string(index=False))

    pd.DataFrame([r for df in years_all for r in df.to_dict("records")]).to_csv(
        out / "per_year_default.csv", index=False)
    if wf_all:
        pd.concat(wf_all).to_csv(out / "walk_forward.csv", index=False)
    s.to_csv(out / "summary.csv", index=False)
    print(f"\nCSV results written to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
