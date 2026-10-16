"""Defaults for the micro blue-chip bot. Override anything from the CLI."""
from __future__ import annotations

# Large, liquid, low-volatility "blue chip" names. Fractional shares mean a
# $1,000 account can still hold slices of these.
BLUE_CHIPS = [
    "AAPL", "MSFT", "JNJ", "PG", "KO", "PEP", "JPM", "V",
    "WMT", "HD", "MCD", "COST", "MRK", "UNH", "XOM",
]
BENCHMARK = "SPY"

STARTING_CAPITAL = 1000.0
DAILY_PROFIT_TARGET = 2.0      # "a couple bucks a day"
FIRST_YEAR = 2020              # backtest each year from here to the current year

# Costs. Alpaca is commission-free, but you still pay the spread and a tiny
# SEC fee on sells. Slippage is applied to every fill.
SLIPPAGE_PCT = 0.0005          # 0.05% per side
SEC_FEE_RATE = 0.0000278       # fraction of sell notional

# Stop-loss / take-profit grid the optimizer sweeps (percent moves).
STOP_LOSS_GRID = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05]
TAKE_PROFIT_GRID = [0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03]
