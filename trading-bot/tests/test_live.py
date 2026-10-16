from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from microbot.live import Bot, LiveSettings, State, trading_days_held
from microbot.strategies import Strategy

NY = ZoneInfo("America/New_York")


class FakeAlpaca:
    """Just enough of alpaca TradingClient for the bot."""

    def __init__(self, equity=1000.0, cash=1000.0, daytrades=0, is_open=True):
        self.equity, self.cash, self.daytrades, self.is_open = equity, cash, daytrades, is_open
        self.orders, self.closed, self.held = [], [], {}
        self._n = 0

    def get_account(self):
        return SimpleNamespace(equity=str(self.equity), cash=str(self.cash), daytrade_count=self.daytrades)

    def get_clock(self):
        today = datetime.now(NY).date()
        return SimpleNamespace(is_open=self.is_open,
                               next_close=datetime(today.year, today.month, today.day, 16, 0, tzinfo=NY))

    def submit_order(self, req):
        self._n += 1
        self.orders.append(req)
        price = PRICES[req.symbol]
        qty = float(req.notional) / price
        self.held[req.symbol] = self.held.get(req.symbol, 0) + qty
        # first poll says "new", then "filled" (exercises the wait loop)
        self._pending = SimpleNamespace(id=str(self._n), status="filled", filled_qty=str(qty),
                                        filled_avg_price=str(price))
        return SimpleNamespace(id=str(self._n), status="new", filled_qty=None, filled_avg_price=None)

    def get_order_by_id(self, oid):
        return self._pending

    def get_open_position(self, symbol):
        if symbol not in self.held:
            raise Exception("position does not exist")
        return SimpleNamespace(qty=str(self.held[symbol]))

    def close_position(self, symbol, close_options=None):
        qty = float(close_options.qty)
        assert qty <= self.held[symbol] + 1e-9, "tried to sell more than held"
        self.held[symbol] -= qty
        if self.held[symbol] <= 1e-9:
            del self.held[symbol]
        self.closed.append((symbol, qty))


PRICES = {}


def bars(n=30, last_close=100.0):
    idx = pd.bdate_range(end=date.today() - timedelta(days=1), periods=n)
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": last_close,
                         "volume": 1e6}, index=idx)


def make_bot(tmp_path, *, signal_syms=("AAA", "BBB"), intraday=False, fake=None, clock=None, **cfg):
    PRICES.clear()
    PRICES.update({"AAA": 100.0, "BBB": 50.0, "CCC": 20.0})
    fake = fake or FakeAlpaca()

    def sig(df):
        return pd.Series(df.attrs.get("sym") in signal_syms, index=df.index)

    def rank(df):
        return pd.Series({"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}[df.attrs["sym"]], index=df.index)

    def get_bars(symbols):
        out = {}
        for s in symbols:
            df = bars()
            df.attrs["sym"] = s
            out[s] = df
        return out

    strat = Strategy(name="t", signal=sig, rank=rank, intraday=intraday, max_hold_days=2,
                     stop_loss=0.02, take_profit=0.01, max_positions=2)
    settings = LiveSettings(symbols=["AAA", "BBB", "CCC"], **cfg)
    now = clock or (lambda: datetime.now(NY).replace(hour=10, minute=0))
    bot = Bot(strat, settings, fake, get_bars, lambda s: PRICES[s],
              state=State(tmp_path / "state.json"), now=now, sleep=lambda s: None)
    return bot, fake


def test_enter_buys_top_ranked_signals_with_budget_split(tmp_path):
    bot, fake = make_bot(tmp_path, budget=600)
    bought = bot.enter()
    assert bought == ["BBB", "AAA"]                        # BBB ranks higher
    assert [float(o.notional) for o in fake.orders] == [300.0, 300.0]
    pos = bot.state.positions["AAA"]
    assert pos["qty"] == pytest.approx(3.0)
    assert pos["stop"] == pytest.approx(98.0) and pos["target"] == pytest.approx(101.0)
    assert bot.state.data["entered_today"]


def test_enter_respects_cash_and_slots(tmp_path):
    bot, fake = make_bot(tmp_path, signal_syms=("AAA", "BBB", "CCC"), budget=1000,
                         fake=FakeAlpaca(cash=520.0))
    bot.enter()
    assert len(fake.orders) == 2                           # max_positions=2 even with 3 signals
    assert sum(float(o.notional) for o in fake.orders) <= 520.0 + 1e-9


def test_take_profit_and_stop_loss(tmp_path):
    bot, fake = make_bot(tmp_path, budget=600)
    bot.enter()
    PRICES["AAA"] = 101.5                                  # above 101 target
    PRICES["BBB"] = 48.9                                   # below 49 stop
    assert sorted(bot.manage()) == ["AAA", "BBB"]
    assert bot.state.positions == {}
    assert fake.held == {}


def test_nothing_sold_inside_band(tmp_path):
    bot, fake = make_bot(tmp_path)
    bot.enter()
    PRICES["AAA"] = 100.5
    assert bot.manage() == []
    assert fake.closed == []


def test_only_sells_own_shares(tmp_path):
    fake = FakeAlpaca()
    fake.held["AAA"] = 10.0                                # other Pi bot's shares
    bot, fake = make_bot(tmp_path, signal_syms=("AAA",), fake=fake, budget=300)
    bot.enter()
    PRICES["AAA"] = 90.0
    bot.manage()
    assert fake.held["AAA"] == pytest.approx(10.0)         # other bot untouched


def test_position_closed_elsewhere_is_forgotten(tmp_path):
    bot, fake = make_bot(tmp_path, signal_syms=("AAA",))
    bot.enter()
    del fake.held["AAA"]
    PRICES["AAA"] = 50.0
    bot.manage()
    assert bot.state.positions == {} and fake.closed == []


def test_daily_loss_limit_flattens_and_halts(tmp_path):
    bot, fake = make_bot(tmp_path, daily_loss_limit=20)
    bot.state.new_day(date.today(), 1000.0)
    bot.enter()
    fake.equity = 975.0
    assert sorted(bot.manage()) == ["AAA", "BBB"]
    assert bot.state.data["halted_today"]
    # halted: no re-entry the same day via tick
    bot.state.data["entered_today"] = False
    bot.tick()
    assert len(fake.orders) == 2


def test_pdt_guard_blocks_intraday_entries(tmp_path):
    bot, fake = make_bot(tmp_path, intraday=True, fake=FakeAlpaca(daytrades=3))
    assert bot.enter() == []
    assert fake.orders == []
    bot2, fake2 = make_bot(tmp_path / "x", intraday=False, fake=FakeAlpaca(daytrades=3))
    (tmp_path / "x").mkdir(exist_ok=True)
    assert bot2.enter()                                    # swing trades unaffected


def test_end_of_day_intraday_flattens(tmp_path):
    bot, fake = make_bot(tmp_path, intraday=True)
    bot.enter()
    assert sorted(bot.end_of_day()) == ["AAA", "BBB"]


def test_end_of_day_swing_time_stop(tmp_path):
    bot, fake = make_bot(tmp_path)
    bot.enter()
    assert bot.end_of_day() == []                          # held 0 days
    for p in bot.state.positions.values():
        p["entry_day"] = (date.today() - timedelta(days=7)).isoformat()
    assert sorted(bot.end_of_day()) == ["AAA", "BBB"]


def test_tick_schedule(tmp_path):
    t = {"now": datetime.now(NY).replace(hour=9, minute=31)}
    bot, fake = make_bot(tmp_path, clock=lambda: t["now"])
    assert bot.tick() == "open" and fake.orders == []      # waits entry_delay_min
    t["now"] = t["now"].replace(hour=9, minute=40)
    bot.tick()
    assert len(fake.orders) == 2
    bot.tick()
    assert len(fake.orders) == 2                           # only enters once a day
    t["now"] = t["now"].replace(hour=15, minute=56)
    assert bot.tick() == "eod"
    fake.is_open = False
    assert bot.tick() == "closed"


def test_state_persists_and_resets_daily(tmp_path):
    bot, _ = make_bot(tmp_path)
    bot.enter()
    again = State(tmp_path / "state.json")
    assert set(again.positions) == {"AAA", "BBB"} and again.data["entered_today"]
    again.new_day(date.today() + timedelta(days=1), 1000.0)
    assert not again.data["entered_today"] and set(again.positions) == {"AAA", "BBB"}


def test_dry_run_sends_no_orders(tmp_path):
    bot, fake = make_bot(tmp_path, dry_run=True)
    bot.enter()
    PRICES["AAA"] = 200
    bot.manage()
    assert fake.orders == [] and fake.closed == []


def test_ignores_todays_partial_bar(tmp_path):
    bot, fake = make_bot(tmp_path)
    seen = {}

    def sig(df):
        seen["last"] = df.index[-1].date()
        return pd.Series(True, index=df.index)
    bot.s.signal = sig

    def get_bars(symbols):
        out = {}
        for s in symbols:
            df = bars()
            df.loc[pd.Timestamp(date.today())] = [100, 101, 99, 100, 1e6]
            df.attrs["sym"] = s
            out[s] = df
        return out
    bot.get_daily_bars = get_bars
    bot.enter()
    assert seen["last"] < date.today()


def test_trading_days_held():
    assert trading_days_held("2026-10-09", date(2026, 10, 12)) == 1   # Fri -> Mon
    assert trading_days_held("2026-10-12", date(2026, 10, 12)) == 0


@pytest.mark.parametrize("live_flag,env,expect_paper", [
    (False, "true", True), (False, "false", True), (True, "true", True), (True, "false", False),
])
def test_paper_unless_both_live_switches(monkeypatch, live_flag, env, expect_paper):
    import alpaca.data.historical as hist
    import alpaca.trading.client as tc
    from microbot import live as live_mod
    from microbot.strategies import builtin_strategies

    seen = {}
    monkeypatch.setattr(tc, "TradingClient", lambda k, s, paper: seen.setdefault("paper", paper))
    monkeypatch.setattr(hist, "StockHistoricalDataClient", lambda k, s: object())
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.setenv("ALPACA_PAPER", env)
    live_mod.make_alpaca_bot(builtin_strategies()["rsi2_dip"], LiveSettings(symbols=["AAPL"]), live=live_flag)
    assert seen["paper"] is expect_paper
