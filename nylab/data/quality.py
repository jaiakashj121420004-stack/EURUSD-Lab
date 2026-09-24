"""nylab.data.quality -- data-quality checks, DATA_AND_TIME.md S5 / S3.

Phase 1 reports these (data_quality.json / summary.json) but does NOT filter the DAY table with
them -- v0 didn't either, and Phase 1 acceptance requires matching v0's numbers exactly. Once
thin/gappy days are validated (Phase 5.6-adjacent), filtering can be turned on deliberately.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def check_bars(bars: pd.DataFrame) -> dict:
    """bars needs: server, open, high, low, close. Read-only -- returns a report, never mutates."""
    diffs = bars["server"].diff().dt.total_seconds().div(60)
    modal = diffs.mode()
    bar_minutes = float(modal.iloc[0]) if len(modal) else float("nan")

    ohlc_ok = (bars["low"] <= bars[["open", "close"]].min(axis=1) + 1e-9) & \
              (bars[["open", "close"]].max(axis=1) <= bars["high"] + 1e-9)

    med_range = (bars["high"] - bars["low"]).median()
    spikes = (bars["high"] - bars["low"]) > 15 * med_range

    report = dict(
        n_bars=int(len(bars)),
        first=str(bars["server"].min()),
        last=str(bars["server"].max()),
        bar_minutes=bar_minutes,
        bar_interval_ok=bool(np.isfinite(bar_minutes) and bar_minutes <= 15),
        ohlc_bad_bars=int((~ohlc_ok).sum()),
        duplicate_timestamps=int(bars["server"].duplicated().sum()),
        price_spike_bars=int(spikes.sum()),
    )
    if "spread_pts" in bars.columns and bars["spread_pts"].notna().any():
        report["median_spread_pts"] = float(bars["spread_pts"].median())
        report["p95_spread_pts"] = float(bars["spread_pts"].quantile(0.95))
    return report


def flag_days(bars_with_td_h: pd.DataFrame, day_range_pips: pd.Series) -> pd.DataFrame:
    """Per-td thin_day / gappy flags. bars_with_td_h needs 'td' and 'h' columns.
    day_range_pips: Series indexed by td, in pips (e.g. nylab.days build_days()'s day_range)."""
    bar_count = bars_with_td_h.groupby("td").size()
    thin_by_count = bar_count < 0.7 * bar_count.median()

    med_range = day_range_pips.rolling(20, min_periods=5).median()
    thin_by_range = day_range_pips < 0.3 * med_range

    thin = thin_by_count.reindex(day_range_pips.index, fill_value=False) | thin_by_range.fillna(False)

    intraday = bars_with_td_h[(bars_with_td_h["h"] >= 2) & (bars_with_td_h["h"] < 16)]
    missing = intraday.groupby("td")["server"].apply(
        lambda s: (s.sort_values().diff().dt.total_seconds().div(300) - 1).clip(lower=0).sum()
    )
    gappy = missing.reindex(day_range_pips.index, fill_value=0) > 3

    return pd.DataFrame({"thin_day": thin.astype(bool), "gappy": gappy.astype(bool)})
