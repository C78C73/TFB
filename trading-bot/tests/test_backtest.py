import numpy as np
import pandas as pd
import pytest

from microbot import optimize
from microbot.backtest import prepare, run, year_windows, with_params
from microbot.strategies import Strategy, builtin_strategies, rsi, sma
from microbot.synthetic import fake_bars

NO_COST = dict(slippage=0.0, sec_fee=0.0)


def bars_from(rows, start="2024-01-01"):
    """rows: list of (open, high, low, close)."""
    idx = pd.bdate_range(start, periods=len(rows))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1e6
    return df


def signal_on(days):
    """Strategy whose signal is True only on the given row numbers."""
    def sig(df):
        s = pd.Series(False, index=df.index)
        s.iloc[list(days)] = True
        return s
    return sig


def strat(days, **kw):
    base = dict(name="t", signal=signal_on(days), intraday=False, max_hold_days=5,
                stop_loss=0.02, take_profit=0.01, max_positions=1)
    base.update(kw)
    return Strategy(**base)


def go(bars, s, **kw):
    prep = prepare(bars, s)
    params = dict(NO_COST, starting_capital=1000.0)
    params.update(kw)
    return run(prep, s, prep.dates[0], prep.dates[-1], **params)


FLAT = (100, 100.5, 99.5, 100)


def test_enters_next_open_not_same_day():
    b = {"A": bars_from([FLAT, (101, 101.2, 100.8, 101), FLAT, FLAT])}
    r = go(b, strat([0], max_hold_days=10, stop_loss=None, take_profit=None))
    t = r.trades[0]
    assert t.entry_date == b["A"].index[1]           # signal day 0 -> buy day 1
    assert t.entry_price == pytest.approx(101.0)      # at day 1's OPEN


def test_take_profit_fills_at_target():
    b = {"A": bars_from([FLAT, (100, 101.5, 99.5, 101), FLAT])}
    r = go(b, strat([0]))
    t = r.trades[0]
    assert t.reason == "target"
    assert t.exit_price == pytest.approx(101.0)
    assert t.pnl == pytest.approx(10.0)               # $1000 * 1%
    assert r.equity.iloc[-1] == pytest.approx(1010.0)


def test_stop_loss_fills_at_stop():
    b = {"A": bars_from([FLAT, (100, 100.5, 97, 98), FLAT])}
    t = go(b, strat([0])).trades[0]
    assert t.reason == "stop"
    assert t.exit_price == pytest.approx(98.0)
    assert t.pnl == pytest.approx(-20.0)


def test_both_touched_same_day_assumes_stop():
    b = {"A": bars_from([FLAT, (100, 102, 97, 100), FLAT])}
    t = go(b, strat([0])).trades[0]
    assert t.reason == "stop"
    assert t.pnl == pytest.approx(-20.0)


def test_gap_down_through_stop_fills_at_open():
    b = {"A": bars_from([FLAT, (100, 100.5, 99.5, 100), (95, 96, 94, 95), FLAT])}
    t = go(b, strat([0])).trades[0]
    assert t.reason == "stop_gap"
    assert t.exit_price == pytest.approx(95.0)        # worse than the 98 stop
    assert t.pnl == pytest.approx(-50.0)


def test_gap_up_through_target_fills_at_open():
    b = {"A": bars_from([FLAT, (100, 100.5, 99.5, 100), (103, 104, 102.5, 103), FLAT])}
    t = go(b, strat([0])).trades[0]
    assert t.reason == "target_gap"
    assert t.exit_price == pytest.approx(103.0)


def test_intraday_closes_same_day():
    b = {"A": bars_from([FLAT, (100, 100.6, 99.6, 100.3), FLAT])}
    r = go(b, strat([0], intraday=True))
    t = r.trades[0]
    assert t.reason == "close"
    assert t.entry_date == t.exit_date
    assert t.pnl == pytest.approx(3.0)


def test_time_stop_after_max_hold():
    b = {"A": bars_from([FLAT] * 8)}
    t = go(b, strat([0], max_hold_days=3)).trades[0]
    assert t.reason == "time"
    assert (t.exit_date - t.entry_date).days == 3     # Tue -> Fri, 3 trading days


def test_open_positions_closed_at_end_of_window():
    b = {"A": bars_from([FLAT] * 4)}
    r = go(b, strat([0], max_hold_days=100, stop_loss=None, take_profit=None))
    assert [t.reason for t in r.trades] == ["end_of_test"]
    assert r.equity.iloc[-1] == pytest.approx(1000.0)


def test_costs_reduce_pnl():
    b = {"A": bars_from([FLAT, (100, 101.5, 99.5, 101), FLAT])}
    s = strat([0])
    free = go(b, s).trades[0].pnl
    paid = go(b, s, slippage=0.001, sec_fee=0.0000278).trades[0].pnl
    assert paid < free
    # buy 100.1, target 101.101, sell fills 101.101*(1-0.001)
    shares = 1000 / 100.1
    exp = shares * 101.101 * 0.999 * (1 - 0.0000278) - 1000
    assert paid == pytest.approx(exp)


def test_max_positions_and_rank_order():
    rows = [FLAT] * 4
    b = {s: bars_from(rows) for s in ("A", "B", "C")}
    rank = {"A": 1.0, "B": 3.0, "C": 2.0}

    def rank_fn(df):
        # identify the symbol by object identity
        sym = next(k for k, v in b.items() if v is df)
        return pd.Series(rank[sym], index=df.index)

    s = strat([0], max_positions=2, rank=rank_fn, max_hold_days=100, stop_loss=None, take_profit=None)
    r = go(b, s)
    assert sorted(t.symbol for t in r.trades) == ["B", "C"]
    for t in r.trades:
        assert t.shares * t.entry_price == pytest.approx(500.0)   # equity / 2 slots


def test_no_double_entry_and_cash_never_negative():
    b = {"A": bars_from([FLAT] * 10)}
    s = strat(range(10), max_hold_days=100, stop_loss=None, take_profit=None)
    r = go(b, s)
    assert len(r.trades) == 1
    assert (r.equity > 0).all()


def test_missing_bar_does_not_crash():
    df = bars_from([FLAT, FLAT, (100, 101.5, 99.5, 101), FLAT, FLAT])
    other = bars_from([FLAT] * 5)
    df = df.drop(df.index[1])                         # A has no bar on day 1
    r = go({"A": df, "B": other}, strat([0], max_positions=2, rank=None))
    assert len(r.trades) >= 1
    assert np.isfinite(r.equity).all()


def test_no_lookahead_future_data_does_not_change_past_trades():
    full = fake_bars(["A", "B", "C"], start="2023-01-01", end="2024-12-31", seed=3)
    cut = pd.Timestamp("2024-06-28")
    trimmed = {k: v.loc[:cut] for k, v in full.items()}
    for s in builtin_strategies().values():
        if "benchmark" in s.tags:
            continue
        p_full, p_cut = prepare(full, s), prepare(trimmed, s)
        r_full = run(p_full, s, "2024-01-01", "2024-12-31")
        r_cut = run(p_cut, s, "2024-01-01", cut)
        done_full = [(t.symbol, t.entry_date, round(t.pnl, 9)) for t in r_full.trades if t.exit_date < cut]
        done_cut = [(t.symbol, t.entry_date, round(t.pnl, 9)) for t in r_cut.trades if t.exit_date < cut]
        assert done_full == done_cut, s.name
        assert np.allclose(r_full.equity.loc[:cut - pd.Timedelta(days=1)],
                           r_cut.equity.loc[:cut - pd.Timedelta(days=1)])


def test_equity_matches_trade_pnl():
    bars = fake_bars(["A", "B", "C", "D"], start="2022-01-01", end="2024-12-31", seed=11)
    for s in builtin_strategies().values():
        r = run(prepare(bars, s), s, "2023-01-01", "2024-12-31")
        assert r.equity.iloc[-1] - 1000 == pytest.approx(sum(t.pnl for t in r.trades), abs=1e-6), s.name


def test_each_year_starts_fresh():
    bars = fake_bars(["A", "B"], start="2019-01-01", end="2022-12-31", seed=5)
    s = builtin_strategies()["rsi2_dip"]
    prep = prepare(bars, s)
    years = year_windows(prep.dates, 2020, 2022)
    assert [y for y, _, _ in years] == [2020, 2021, 2022]
    rows = optimize.per_year(prep, s, years)
    for row, (year, start, end) in zip(rows, years):
        r = run(prep, s, start, end)
        assert row["profit"] == pytest.approx(r.equity.iloc[-1] - 1000, abs=0.01)
        assert row["start"].startswith(str(year))


def test_metrics_values():
    b = {"A": bars_from([FLAT, (100, 101.5, 99.5, 101), FLAT])}
    m = go(b, strat([0]), daily_target=2.0).metrics()
    assert m["profit"] == pytest.approx(10.0)
    assert m["trades"] == 1 and m["win_rate_pct"] == 100.0
    assert m["trading_days"] == 3
    assert m["days_hit_target_pct"] == pytest.approx(33.3)
    assert m["max_drawdown_pct"] == 0.0


def test_with_params_overrides_sl_tp():
    s = with_params(builtin_strategies()["rsi2_dip"], stop_loss=0.01, take_profit=None)
    assert s.stop_loss == 0.01 and s.take_profit is None


def test_rsi_and_sma():
    up = pd.Series(np.arange(1, 30, dtype=float))
    assert rsi(up, 2).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(30, 1, -1, dtype=float))
    assert rsi(down, 2).iloc[-1] == pytest.approx(0.0)
    assert sma(up, 3).iloc[-1] == pytest.approx(28.0)
    assert np.isnan(sma(up, 3).iloc[1])
