# Micro blue-chip bot (Alpaca)

Small-account bot that trades only large, steady blue-chip stocks (AAPL, MSFT,
JNJ, PG, KO, PEP, JPM, V, WMT, HD, MCD, COST, MRK, UNH, XOM) using fractional
shares, with a stop-loss / take-profit on every trade. It comes with a
backtester that tests **each calendar year on its own from 2020 to today**,
sweeps the stop/target settings, and compares strategies side by side,
including your existing Pi bot.

> Paper trade first. Nothing here is financial advice, and backtests are not a
> promise of future results.

## Setup on the Pi

```bash
cd trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # paste your Alpaca PAPER keys in here
python -m pytest            # 53 tests; all should pass
```

## 1. Backtest every year (2020 to now)

```bash
python backtest.py                 # each strategy, default stop/target, year by year
python backtest.py --optimize      # + sweep stop-loss x take-profit grid per year
```

The first run downloads daily bars from Alpaca into `data_cache/` (later runs
are offline). Results print to the screen and save as CSVs in `results/`:

| file | what's in it |
|---|---|
| `per_year_default.csv` | every strategy, every year, default settings |
| `grid_<strategy>.csv` | every stop/target pair x every year |
| `walk_forward.csv` | each year traded with the pair that won on the **earlier** years only |
| `summary.csv` | side-by-side comparison |

**Read the walk-forward numbers, not the best-in-hindsight ones.** Picking the
stop/target that did best in a year *after* seeing that year always looks great
and is mostly luck. Walk-forward is what you'd actually have earned.

The "most consistent pairs" table ranks stop/target pairs by how many years
they made money in. Prefer a pair that's green in most years over one that had
one huge year.

Useful flags: `--capital 1000`, `--target 2` ($/day goal), `--first-year 2020`,
`--slippage 0.0005`, `--strategies rsi2_dip buy_hold`, `--symbols AAPL MSFT KO`.

## 2. Compare against your current Pi bot

Open `microbot/custom_strategy.py`, paste your Pi bot's buy rule into
`pi_bot_signal`, set its stop/target/hold settings, set `ENABLED = True`, then:

```bash
python backtest.py --strategies pi_bot rsi2_dip pullback_bounce trend_scalp buy_hold --optimize
```

## 3. Run it (paper)

```bash
python run_bot.py --strategy rsi2_dip --dry-run --once     # logs what it would do
python run_bot.py --strategy rsi2_dip --stop-loss 0.03 --take-profit 0.015 --budget 1000
```

To keep it running on the Pi, add it to crontab (`crontab -e`), started each
weekday before the open (the time is Pi local time; this example is US Central):

```
25 8 * * 1-5 cd /home/pi/trading-bot && .venv/bin/python run_bot.py --strategy rsi2_dip >> cron.log 2>&1
```

The bot checks prices every 60s, buys about 5 minutes after the open, and
closes intraday trades or time-stopped trades 5 minutes before the close.

Safety rails:
- **Paper by default.** Real money needs `ALPACA_PAPER=false` in `.env` **and** `--live`.
- **It only touches positions it opened** (tracked in `bot_state.json`) and only
  sells the shares it bought, so it can share an account with your other bot.
  A separate paper account is still cleaner for comparing them.
- `--budget` caps the dollars it uses; `--daily-loss-limit` (default $25)
  flattens its positions and stops trading for the day.
- Pattern-day-trader guard: on an account under $25k it won't open new day trades
  once Alpaca reports 3 day trades in 5 days.

## Strategies

| name | idea | holds |
|---|---|---|
| `rsi2_dip` | stock above its 200-day average but very oversold (RSI(2) < 10) | up to 5 days |
| `pullback_bounce` | uptrend + red day closing near its low | up to 3 days |
| `trend_scalp` | buy uptrending names at the open with a tiny target | same day only |
| `buy_hold` | benchmark: buy all of them and hold the year | all year |

## How the backtest stays honest

- Signals use the close of day *t*; the trade fills at the **open of day t+1**.
- 0.05% slippage per side plus the SEC sell fee (both adjustable).
- Gaps through a stop fill at the (worse) open, not at the stop.
- If a day's range touches both the stop and the target, it assumes **the stop
  hit first**, because daily bars can't show which came first.
- Every year starts with fresh capital and ends flat.
- The tests check each of these rules, including that changing future prices
  can't change past trades.

## Reality check on "a couple bucks a day" with under $1,000

- $2/day on $1,000 is 0.2% a day, roughly **50% a year**. Blue chips have
  historically averaged about 8–12% a year, around **$0.30–0.50/day** on $1,000.
  Hitting $2/day consistently would mean beating the market by a lot.
- Costs matter more than usual at this size. The backtest's default slippage
  (0.05% per side) is about $1 per round trip on $1,000, half a $2 target.
  That's deliberately pessimistic: blue-chip spreads are often around 0.01%. Run
  with `--slippage 0.0001` too and compare. If a strategy only wins at the
  optimistic cost, it's fragile. Tiny same-day scalps like `trend_scalp` are
  the most sensitive to this.
- A normal day moves a blue chip about 1%, or about $10 on $1,000. A $2 target
  is well inside that day-to-day noise.
- Day trading under $25k on a **margin** account is limited to 3 day trades per
  5 days (pattern-day-trader rule; check Alpaca's current rules). A **cash**
  account avoids that but must wait for funds to settle (T+1). The swing
  strategies (`rsi2_dip`, `pullback_bounce`) avoid the problem.

Let the backtest decide: if no strategy beats `buy_hold` in the walk-forward
results across most years, buying and holding is the better plan.
