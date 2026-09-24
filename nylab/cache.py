"""nylab.cache -- parquet cache for bars/days, reused by `run` and (Phase 2) `replay` (ROADMAP 1.8)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def save(bars: pd.DataFrame, days: pd.DataFrame, cache_dir: str = "data/cache") -> None:
    p = Path(cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(p / "bars_M5.parquet", index=False)
    days.to_parquet(p / "days.parquet")


def load(cache_dir: str = "data/cache") -> tuple[pd.DataFrame, pd.DataFrame]:
    p = Path(cache_dir)
    bars = pd.read_parquet(p / "bars_M5.parquet")
    days = pd.read_parquet(p / "days.parquet")
    return bars, days
