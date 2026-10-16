"""FAKE random-walk prices for offline testing only. Never trade on these."""
from __future__ import annotations

import numpy as np
import pandas as pd


def fake_bars(symbols, start="2019-01-01", end="2026-10-09", seed=0,
              drift=0.0003, vol=0.012, start_price=100.0) -> dict:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    out = {}
    for n, sym in enumerate(symbols):
        rets = rng.normal(drift, vol, len(dates))
        close = start_price * (1 + n * 0.1) * np.exp(np.cumsum(rets))
        prev = np.concatenate([[close[0]], close[:-1]])
        open_ = prev * np.exp(rng.normal(0, vol / 3, len(dates)))
        hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, len(dates))))
        lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, len(dates))))
        out[sym] = pd.DataFrame(
            {"open": open_, "high": hi, "low": lo, "close": close,
             "volume": rng.integers(1_000_000, 5_000_000, len(dates)).astype(float)},
            index=dates,
        )
    return out
