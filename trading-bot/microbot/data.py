"""Daily price data: download from Alpaca once, then read from a local CSV cache.

Every frame this module returns has a tz-naive DatetimeIndex (one row per
trading day) and lowercase columns: open, high, low, close, volume.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data_cache"
COLUMNS = ["open", "high", "low", "close", "volume"]


def load_env(path: str | os.PathLike | None = None) -> None:
    """Minimal .env reader so we don't need python-dotenv on the Pi."""
    env_path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a bar frame: lowercase columns, sorted tz-naive daily index."""
    df = df.rename(columns=str.lower)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"bars are missing columns: {missing}")
    df = df[COLUMNS].copy()
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df.astype(float)


def _cache_path(symbol: str, cache_dir: Path) -> Path:
    return cache_dir / f"{symbol.upper()}.csv"


def read_csv(path: str | os.PathLike) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    return clean_bars(df)


def fetch_alpaca(symbols: list[str], start: str, end: str | None = None) -> dict[str, pd.DataFrame]:
    """Download split/dividend-adjusted daily bars from Alpaca."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    load_env()
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY (see .env.example)")
    client = StockHistoricalDataClient(key, secret)

    out: dict[str, pd.DataFrame] = {}
    for feed in (DataFeed.SIP, DataFeed.IEX):
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=datetime.fromisoformat(start),
                end=datetime.fromisoformat(end) if end else None,
                adjustment=Adjustment.ALL,
                feed=feed,
            )
            raw = client.get_stock_bars(req).df
            break
        except Exception as exc:  # free plans can't query very recent SIP data
            print(f"[data] {feed.value} feed failed ({exc}); trying next feed")
    else:
        raise RuntimeError("Could not download bars from Alpaca")

    for symbol in symbols:
        if symbol in raw.index.get_level_values(0):
            out[symbol] = clean_bars(raw.xs(symbol, level=0))
    return out


def get_bars(
    symbols: list[str],
    start: str,
    end: str | None = None,
    refresh: bool = False,
    cache_dir: str | os.PathLike | None = None,
) -> dict[str, pd.DataFrame]:
    """Return {symbol: bars}, downloading only symbols missing from the cache."""
    cache = Path(cache_dir) if cache_dir else CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)

    result: dict[str, pd.DataFrame] = {}
    need: list[str] = []
    for symbol in symbols:
        path = _cache_path(symbol, cache)
        if path.exists() and not refresh:
            df = read_csv(path)
            if not df.empty and df.index[0] <= pd.Timestamp(start) + pd.Timedelta(days=7):
                result[symbol] = df
                continue
        need.append(symbol)

    if need:
        fetched = fetch_alpaca(need, start, end)
        for symbol, df in fetched.items():
            df.to_csv(_cache_path(symbol, cache))
            result[symbol] = df
        for symbol in set(need) - set(fetched):
            print(f"[data] no bars returned for {symbol}; skipping it")

    if end:
        result = {s: df.loc[:end] for s, df in result.items()}
    return result
