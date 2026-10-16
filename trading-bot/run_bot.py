#!/usr/bin/env python3
"""Run one strategy against Alpaca. PAPER trading unless you pass --live.

  python run_bot.py --strategy rsi2_dip --stop-loss 0.03 --take-profit 0.015
  python run_bot.py --strategy rsi2_dip --dry-run --once   # log what it would do
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from microbot import config
from microbot.backtest import with_params
from microbot.live import LiveSettings, make_alpaca_bot
from microbot.strategies import all_strategies


def main(argv=None) -> int:
    strategies = all_strategies()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", default="rsi2_dip", choices=[n for n in strategies if n != "buy_hold"])
    p.add_argument("--stop-loss", type=float, help="e.g. 0.03 for 3%% (default: strategy's)")
    p.add_argument("--take-profit", type=float, help="e.g. 0.015 for 1.5%%")
    p.add_argument("--max-positions", type=int)
    p.add_argument("--symbols", nargs="+", default=config.BLUE_CHIPS)
    p.add_argument("--budget", type=float, default=config.STARTING_CAPITAL, help="max $ this bot uses")
    p.add_argument("--daily-loss-limit", type=float, default=25.0, help="$ loss that halts for the day")
    p.add_argument("--poll", type=int, default=60, help="seconds between checks while open")
    p.add_argument("--dry-run", action="store_true", help="log orders instead of sending them")
    p.add_argument("--once", action="store_true", help="run a single check and exit")
    p.add_argument("--live", action="store_true", help="real money (also needs ALPACA_PAPER=false)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(Path(__file__).resolve().parent / "microbot.log")])

    overrides = {k: v for k, v in {
        "stop_loss": args.stop_loss, "take_profit": args.take_profit,
        "max_positions": args.max_positions}.items() if v is not None}
    strategy = with_params(strategies[args.strategy], **overrides)
    settings = LiveSettings(symbols=args.symbols, budget=args.budget,
                            daily_loss_limit=args.daily_loss_limit, dry_run=args.dry_run)
    bot = make_alpaca_bot(strategy, settings, live=args.live)
    logging.info("Strategy %s | SL %s | TP %s | budget $%.0f", strategy.name,
                 strategy.stop_loss, strategy.take_profit, settings.budget)

    while True:
        try:
            status = bot.tick()
        except Exception:
            logging.exception("tick failed; retrying next poll")
            status = "error"
        if args.once:
            logging.info("status: %s", status)
            return 0
        time.sleep(args.poll if status in ("open", "error") else 300)


if __name__ == "__main__":
    sys.exit(main())
