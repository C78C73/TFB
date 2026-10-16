"""Alpaca paper/live runner for one strategy.

Safety rails:
  * Paper trading unless ALPACA_PAPER=false AND --live is passed.
  * Only touches positions it opened itself (tracked in bot_state.json), so it
    can share an account with your other Pi bot without closing its trades.
  * --budget caps how many dollars this bot may put to work.
  * --daily-loss-limit flattens this bot's positions and stops buying for the day.
  * Pattern-day-trader guard for accounts under $25k.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .strategies import Strategy

log = logging.getLogger("microbot")
STATE_FILE = Path(__file__).resolve().parent.parent / "bot_state.json"
PDT_EQUITY = 25_000.0


@dataclass
class LiveSettings:
    symbols: list
    budget: float = 1000.0
    daily_loss_limit: float = 25.0
    entry_delay_min: int = 5          # wait after the open for spreads to settle
    exit_before_close_min: int = 5    # flatten intraday trades this long before the close
    dry_run: bool = False


class State:
    """Positions this bot owns + per-day flags, persisted to JSON."""

    def __init__(self, path: Path = STATE_FILE):
        self.path = Path(path)
        self.data = {"positions": {}, "day": None, "entered_today": False, "halted_today": False,
                     "start_equity": None}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, default=str))

    @property
    def positions(self) -> dict:
        return self.data["positions"]

    def new_day(self, today: date, equity: float) -> None:
        if self.data["day"] != today.isoformat():
            self.data.update(day=today.isoformat(), entered_today=False, halted_today=False,
                             start_equity=equity)
            self.save()


def trading_days_held(entry_day: str, today: date) -> int:
    return int(np.busday_count(date.fromisoformat(entry_day), today))


class Bot:
    def __init__(
        self,
        strategy: Strategy,
        settings: LiveSettings,
        trading,                                   # alpaca TradingClient (or a fake in tests)
        get_daily_bars: Callable[[list], dict],    # symbols -> {sym: bars up to yesterday}
        get_price: Callable[[str], float],         # latest trade price
        state: Optional[State] = None,
        now: Callable[[], datetime] = None,
        sleep: Callable[[float], None] = None,
    ):
        self.s = strategy
        self.cfg = settings
        self.trading = trading
        self.get_daily_bars = get_daily_bars
        self.get_price = get_price
        self.state = state or State()
        self.sleep = sleep or __import__("time").sleep
        self.now = now or (lambda: pd.Timestamp.now(tz="America/New_York").to_pydatetime())

    # ------------------------------------------------------------ orders
    def _buy(self, symbol: str, notional: float) -> tuple:
        """Market-buy $notional (fractional). Returns (avg fill price, shares)."""
        notional = round(notional, 2)
        if self.cfg.dry_run:
            price = self.get_price(symbol)
            log.info("[dry-run] BUY %s $%.2f @ ~%.2f", symbol, notional, price)
            return price, notional / price
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        order = self.trading.submit_order(MarketOrderRequest(
            symbol=symbol, notional=notional, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
        for _ in range(30):                      # market orders fill in well under 30s
            if str(getattr(order, "status", "")).lower().endswith("filled") and order.filled_qty:
                break
            self.sleep(1)
            order = self.trading.get_order_by_id(order.id)
        price = float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else self.get_price(symbol)
        qty = float(order.filled_qty) if getattr(order, "filled_qty", None) else notional / price
        log.info("BUY %s $%.2f -> %.6f sh @ %.2f", symbol, notional, qty, price)
        return price, qty

    def _sell(self, symbol: str, reason: str) -> None:
        pos = self.state.positions.get(symbol) or {}
        if self.cfg.dry_run:
            log.info("[dry-run] SELL %s (%s)", symbol, reason)
        else:
            from alpaca.trading.requests import ClosePositionRequest
            try:
                held = float(self.trading.get_open_position(symbol).qty)
            except Exception:
                held = 0.0
            if held > 0:
                # sell only the shares this bot bought, never another bot's
                qty = min(float(pos.get("qty") or held), held)
                self.trading.close_position(symbol, close_options=ClosePositionRequest(qty=f"{qty:.9f}"))
                log.info("SELL %s %.6f sh (%s)", symbol, qty, reason)
            else:
                log.warning("%s no longer held (closed elsewhere?); forgetting it", symbol)
        self.state.positions.pop(symbol, None)
        self.state.save()

    # ------------------------------------------------------------ steps
    def _equity(self) -> float:
        return float(self.trading.get_account().equity)

    def enter(self) -> list:
        """Once per day, shortly after the open: buy today's top signals."""
        acct = self.trading.get_account()
        equity = float(acct.equity)
        if self.s.intraday and equity < PDT_EQUITY and int(getattr(acct, "daytrade_count", 0)) >= 3:
            log.warning("PDT guard: 3 day trades in 5 days on a <$25k account; no new day trades today")
            self.state.data["entered_today"] = True
            self.state.save()
            return []

        bars = self.get_daily_bars(self.cfg.symbols)
        today = self.now().date()
        candidates = []
        for sym, df in bars.items():
            df = df[df.index.date < today]            # only completed days
            if len(df) < 2 or sym in self.state.positions:
                continue
            if bool(self.s.signal(df).iloc[-1]):
                score = float(self.s.rank(df).iloc[-1]) if self.s.rank else 0.0
                candidates.append((score, sym))
        candidates.sort(reverse=True)

        slots = max(1, min(self.s.max_positions, len(self.cfg.symbols)))
        free = slots - len(self.state.positions)
        in_use = sum(p["cost"] for p in self.state.positions.values())
        per_slot = self.cfg.budget / slots
        cash = float(getattr(acct, "cash", equity))
        bought = []
        for _, sym in candidates[:max(0, free)]:
            notional = min(per_slot, self.cfg.budget - in_use, cash)
            if notional < 1.0:                        # Alpaca's fractional minimum
                break
            price, qty = self._buy(sym, notional)
            self.state.positions[sym] = {
                "entry_day": today.isoformat(), "entry": price, "cost": round(notional, 2),
                "qty": qty,
                "stop": price * (1 - self.s.stop_loss) if self.s.stop_loss is not None else None,
                "target": price * (1 + self.s.take_profit) if self.s.take_profit is not None else None,
            }
            in_use += notional
            cash -= notional
            bought.append(sym)
        self.state.data["entered_today"] = True
        self.state.save()
        return bought

    def manage(self) -> list:
        """Every poll: stop-loss / take-profit / daily-loss checks."""
        sold = []
        start = self.state.data.get("start_equity")
        if start is not None and not self.state.data["halted_today"]:
            if self._equity() - float(start) <= -self.cfg.daily_loss_limit:
                log.warning("Daily loss limit hit; flattening and halting for today")
                for sym in list(self.state.positions):
                    self._sell(sym, "daily_loss_limit")
                    sold.append(sym)
                self.state.data["halted_today"] = True
                self.state.save()
                return sold
        for sym, pos in list(self.state.positions.items()):
            price = self.get_price(sym)
            if pos["stop"] is not None and price <= pos["stop"]:
                self._sell(sym, f"stop {price:.2f}")
                sold.append(sym)
            elif pos["target"] is not None and price >= pos["target"]:
                self._sell(sym, f"target {price:.2f}")
                sold.append(sym)
        return sold

    def end_of_day(self) -> list:
        """A few minutes before the close: intraday flatten + time stops."""
        today = self.now().date()
        sold = []
        for sym, pos in list(self.state.positions.items()):
            held = trading_days_held(pos["entry_day"], today)
            if self.s.intraday:
                self._sell(sym, "end of day")
                sold.append(sym)
            elif held >= self.s.max_hold_days:
                self._sell(sym, f"time stop ({held}d)")
                sold.append(sym)
        return sold

    def tick(self) -> str:
        """One pass of the main loop. Returns what it did (for logs/tests)."""
        clock = self.trading.get_clock()
        if not clock.is_open:
            return "closed"
        now = self.now()
        self.state.new_day(now.date(), self._equity())
        close_at = pd.Timestamp(clock.next_close).tz_convert("America/New_York").to_pydatetime()
        open_at = datetime.combine(now.date(), dtime(9, 30), tzinfo=close_at.tzinfo)

        if now >= close_at - timedelta(minutes=self.cfg.exit_before_close_min):
            self.end_of_day()
            return "eod"
        if (not self.state.data["entered_today"] and not self.state.data["halted_today"]
                and now >= open_at + timedelta(minutes=self.cfg.entry_delay_min)):
            self.enter()
        self.manage()
        return "open"


# ------------------------------------------------------------------ wiring
def make_alpaca_bot(strategy: Strategy, settings: LiveSettings, live: bool = False) -> Bot:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    from alpaca.trading.client import TradingClient

    from .data import fetch_alpaca, load_env

    load_env()
    key, secret = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    paper = not (live and os.environ.get("ALPACA_PAPER", "true").lower() == "false")
    log.info("Connecting to Alpaca (%s)", "PAPER" if paper else "*** LIVE MONEY ***")
    trading = TradingClient(key, secret, paper=paper)
    data = StockHistoricalDataClient(key, secret)

    def get_daily_bars(symbols):
        start = (date.today() - timedelta(days=420)).isoformat()
        return fetch_alpaca(symbols, start)

    def get_price(symbol):
        trade = data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
        return float(trade[symbol].price)

    return Bot(strategy, settings, trading, get_daily_bars, get_price)
