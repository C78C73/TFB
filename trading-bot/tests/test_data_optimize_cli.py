import importlib
import os

import pandas as pd
import pytest

import backtest as cli
from microbot import custom_strategy, data, optimize, strategies
from microbot.backtest import prepare
from microbot.synthetic import fake_bars


# ------------------------------------------------------------------- data
def test_clean_bars_normalizes():
    idx = pd.to_datetime(["2024-01-03 05:00", "2024-01-02 05:00", "2024-01-03 05:00"]).tz_localize("UTC")
    raw = pd.DataFrame({"Open": [2, 1, 3], "High": [2, 1, 3], "Low": [2, 1, 3], "Close": [2, 1, 3],
                        "Volume": [1, 1, 1], "vwap": [0, 0, 0]}, index=idx)
    df = data.clean_bars(raw)
    assert list(df.columns) == data.COLUMNS
    assert df.index.tz is None and df.index.is_monotonic_increasing
    assert len(df) == 2 and df["close"].iloc[-1] == 3        # duplicate kept last
    assert str(df.index[0].date()) == "2024-01-02"


def test_clean_bars_missing_column():
    with pytest.raises(ValueError):
        data.clean_bars(pd.DataFrame({"open": [1]}))


def test_get_bars_uses_cache_without_network(tmp_path, monkeypatch):
    for s, df in fake_bars(["AAA", "BBB"], start="2019-01-01", end="2020-12-31").items():
        df.to_csv(tmp_path / f"{s}.csv")
    monkeypatch.setattr(data, "fetch_alpaca", lambda *a, **k: pytest.fail("should not download"))
    out = data.get_bars(["AAA", "BBB"], "2019-01-01", "2020-06-30", cache_dir=tmp_path)
    assert set(out) == {"AAA", "BBB"}
    assert out["AAA"].index[-1] <= pd.Timestamp("2020-06-30")


def test_get_bars_downloads_missing(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(symbols, start, end=None):
        calls.append(list(symbols))
        return {s: fake_bars([s], start="2019-01-01", end="2019-03-01")[s] for s in symbols}
    monkeypatch.setattr(data, "fetch_alpaca", fake_fetch)
    data.get_bars(["AAA"], "2019-01-01", cache_dir=tmp_path)
    data.get_bars(["AAA"], "2019-01-01", cache_dir=tmp_path)    # second time: cache hit
    assert calls == [["AAA"]]
    assert (tmp_path / "AAA.csv").exists()


def test_load_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MICROBOT_TEST_KEY", raising=False)
    (tmp_path / ".env").write_text("# c\nMICROBOT_TEST_KEY='abc'\n\nbad line\n")
    data.load_env(tmp_path / ".env")
    assert os.environ["MICROBOT_TEST_KEY"] == "abc"


def test_fetch_alpaca_requires_keys(monkeypatch):
    monkeypatch.setattr(data, "load_env", lambda *a: None)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
        data.fetch_alpaca(["AAPL"], "2024-01-01")


# --------------------------------------------------------------- optimize
def _grid_rows():
    # pair (0.01,0.01) wins 2020 & 2021 overall; (0.02,0.02) wins only 2022
    rows = []
    for year, a, b in [(2020, 50, 10), (2021, 40, 10), (2022, -30, 100), (2023, 5, -5)]:
        rows.append(dict(year=year, stop_loss=0.01, take_profit=0.01, profit=a, sharpe=1, trading_days=252))
        rows.append(dict(year=year, stop_loss=0.02, take_profit=0.02, profit=b, sharpe=1, trading_days=252))
    return pd.DataFrame(rows)


def test_walk_forward_uses_only_past_years():
    s = strategies.Strategy(name="x", signal=lambda d: d["close"] > 0, stop_loss=0.02, take_profit=0.02)
    wf = optimize.walk_forward(_grid_rows(), s).set_index("year")
    assert wf.loc[2020, "stop_loss"] == 0.02                 # default, no history
    assert wf.loc[2021, "stop_loss"] == 0.01                 # 2020 winner
    assert wf.loc[2022, "stop_loss"] == 0.01                 # 2020+2021: 90 vs 20
    assert wf.loc[2022, "profit"] == -30                     # scored on 2022, not picked by it


def test_walk_forward_switches_when_history_changes():
    s = strategies.Strategy(name="x", signal=lambda d: d["close"] > 0, stop_loss=0.02, take_profit=0.02)
    wf = optimize.walk_forward(_grid_rows(), s).set_index("year")
    assert wf.loc[2023, "stop_loss"] == 0.02                 # 2020-22: 0.01 -> 60, 0.02 -> 120
    assert wf.loc[2023, "profit"] == -5
    assert "2022" in wf.loc[2023, "params_from"] and "2023" not in wf.loc[2023, "params_from"]


def test_best_in_hindsight_and_robust():
    g = _grid_rows()
    best = optimize.best_in_hindsight(g).set_index("year")
    assert best.loc[2022, "stop_loss"] == 0.02 and best.loc[2020, "stop_loss"] == 0.01
    g["avg_per_day"] = 0.0
    g["max_drawdown_pct"] = 0.0
    g["trades"] = 1
    r = optimize.robust_pairs(g)
    assert r.iloc[0]["years_profitable"] == 3                # (0.01,0.01): 3 of 4 years


def test_sweep_shape_and_none_values():
    bars = fake_bars(["A", "B"], start="2019-01-01", end="2021-12-31", seed=2)
    s = strategies.builtin_strategies()["pullback_bounce"]
    prep = prepare(bars, s)
    years = optimize.windows_for(prep, 2020, 2021)
    grid = optimize.sweep(prep, s, years, stop_grid=[0.01, None], target_grid=[0.01, 0.02])
    # defaults (2%, 1%) are added: 3 stops x 2 targets x 2 years
    assert len(grid) == 3 * 2 * 2
    assert grid["stop_loss"].isna().sum() == 4
    wf = optimize.walk_forward(grid, s)
    assert list(wf["year"]) == [2020, 2021]


# -------------------------------------------------------------------- CLI
def test_cli_synthetic_end_to_end(tmp_path, capsys):
    rc = cli.main(["--synthetic", "--optimize", "--symbols", "AAA", "BBB", "CCC",
                   "--first-year", "2024", "--last-year", "2025", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SYNTHETIC" in out and "COMPARISON" in out and "walk-forward" in out
    for f in ("summary.csv", "per_year_default.csv", "walk_forward.csv", "grid_rsi2_dip.csv"):
        assert (tmp_path / f).exists(), f
    per_year = pd.read_csv(tmp_path / "per_year_default.csv")
    assert set(per_year["year"]) == {2024, 2025}
    assert set(per_year["strategy"]) == {"rsi2_dip", "trend_scalp", "pullback_bounce", "buy_hold"}


def test_cli_unknown_strategy(capsys):
    assert cli.main(["--synthetic", "--strategies", "nope"]) == 2


def test_cli_csv_dir(tmp_path, capsys):
    for s, df in fake_bars(["AAA", "BBB"], start="2019-01-01", end="2021-12-31").items():
        df.to_csv(tmp_path / f"{s}.csv")
    rc = cli.main(["--csv-dir", str(tmp_path), "--symbols", "AAA", "BBB", "ZZZ",
                   "--strategies", "rsi2_dip", "--first-year", "2020", "--last-year", "2021",
                   "--out", str(tmp_path / "res")])
    assert rc == 0
    assert "ZZZ" in capsys.readouterr().out                    # missing file reported


def test_custom_strategy_plugs_in(monkeypatch):
    monkeypatch.setattr(custom_strategy, "ENABLED", True)
    assert "pi_bot" in strategies.all_strategies()
    monkeypatch.setattr(custom_strategy, "ENABLED", False)
    assert "pi_bot" not in strategies.all_strategies()


def test_run_bot_cli_parses(monkeypatch):
    run_bot = importlib.import_module("run_bot")
    captured = {}

    class FakeBot:
        def tick(self):
            return "closed"

    def fake_make(strategy, settings, live=False):
        captured.update(strategy=strategy, settings=settings, live=live)
        return FakeBot()
    monkeypatch.setattr(run_bot, "make_alpaca_bot", fake_make)
    rc = run_bot.main(["--strategy", "trend_scalp", "--stop-loss", "0.01", "--take-profit", "0.004",
                       "--budget", "500", "--dry-run", "--once"])
    assert rc == 0
    assert captured["strategy"].stop_loss == 0.01 and captured["strategy"].take_profit == 0.004
    assert captured["settings"].budget == 500 and captured["settings"].dry_run
    assert captured["live"] is False
