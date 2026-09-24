"""nylab.replay.api -- the no-leak JSON API (REPLAY_TRAINER.md S7).

The server NEVER sends a bar, level or news-actual later than the caller's `until` timestamp.
Every function here takes `until` and filters by it; there is no code path that returns
unrevealed data. This module has no HTTP framing -- server.py wires it to routes so this stays
directly unit-testable.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from nylab.days import COLUMN_DOCS

RESAMPLE_RULE = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1D"}


class Store:
    """Holds the cached bars/days in memory (loaded once at server startup, REPLAY_TRAINER S1)."""

    def __init__(self, bars: pd.DataFrame, days: pd.DataFrame):
        self.bars = bars.sort_values("ny").reset_index(drop=True)
        self.days = days
        self.bars_by_td = {td: g for td, g in self.bars.groupby("td")}


def _parse_until(until: str) -> pd.Timestamp:
    return pd.Timestamp(until)


def list_days(store: Store, date_from=None, date_to=None, weekdays=None,
              exclude_thin=True, thin_flags: pd.DataFrame | None = None) -> list[dict]:
    """Day list for the navigator table (REPLAY_TRAINER.md S3). Outcome columns (later-session
    character etc.) don't exist until Phase 5 -- nothing to hide yet, so 'hide outcome' is a
    no-op today and will start doing real work once those columns land."""
    d = store.days
    idx = d.index
    if date_from:
        idx = idx[idx >= pd.Timestamp(date_from)]
    if date_to:
        idx = idx[idx <= pd.Timestamp(date_to)]
    d = d.loc[idx]
    if weekdays:
        d = d[d["dow"].isin(weekdays)]

    rows = []
    thin_lookup = thin_flags["thin_day"].to_dict() if thin_flags is not None else {}
    gappy_lookup = thin_flags["gappy"].to_dict() if thin_flags is not None else {}
    for td, r in d.iterrows():
        thin = bool(thin_lookup.get(td, False))
        if exclude_thin and thin:
            continue
        rows.append(dict(
            date=td.strftime("%Y-%m-%d"), weekday=int(r["dow"]),
            day_range_pips=None if pd.isna(r["day_range"]) else round(float(r["day_range"]), 1),
            ny_range_pips=None if pd.isna(r["ny_range"]) else round(float(r["ny_range"]), 1),
            lon_range_pips=None if pd.isna(r["lon_range"]) else round(float(r["lon_range"]), 1),
            ny_takes_lon_high=bool(r.get("ny_takes_lon_high", False)),
            ny_takes_lon_low=bool(r.get("ny_takes_lon_low", False)),
            thin_day=thin, gappy=bool(gappy_lookup.get(td, False)),
        ))
    return rows


def get_bars(store: Store, td: str, tf: str, until: str, context_days: int = 10) -> dict:
    """bars with close time <= until, resampled to `tf` from revealed M5 bars only, plus the
    previous `context_days` full trading days for HTF context (REPLAY_TRAINER.md S4)."""
    td_ts = pd.Timestamp(td)
    until_ts = _parse_until(until)
    all_tds = sorted(store.bars_by_td.keys())
    if td_ts not in store.bars_by_td:
        return {"bars": [], "error": f"no data for {td}"}
    idx = all_tds.index(td_ts)
    ctx_tds = all_tds[max(0, idx - context_days): idx]

    frames = [store.bars_by_td[t] for t in ctx_tds]
    frames.append(store.bars_by_td[td_ts][store.bars_by_td[td_ts]["ny"] <= until_ts])
    bars = pd.concat(frames, ignore_index=True) if frames else store.bars_by_td[td_ts].iloc[0:0]
    bars = bars.sort_values("ny")

    if bars.empty:
        return {"bars": []}

    rule = RESAMPLE_RULE.get(tf, "5min")
    if tf == "M5":
        out = bars[["ny", "open", "high", "low", "close"]]
    else:
        g = bars.set_index("ny").resample(rule, label="left", closed="left")
        out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).dropna().reset_index()

    return {"bars": [
        {"time": int(row.ny.timestamp()), "open": float(row.open), "high": float(row.high),
         "low": float(row.low), "close": float(row.close)}
        for row in out.itertuples()
    ]}


def get_levels(store: Store, td: str, until: str) -> dict:
    """Only levels whose available_at_h <= the NY hour of `until` on this td (REPLAY_TRAINER S7)."""
    td_ts = pd.Timestamp(td)
    if td_ts not in store.days.index:
        return {"levels": {}, "error": f"no day table row for {td}"}
    until_ts = _parse_until(until)
    h = (until_ts - (td_ts - pd.Timedelta(hours=7))).total_seconds() / 3600.0 - 7

    row = store.days.loc[td_ts]
    out = {}
    for col, available_at in COLUMN_DOCS.items():
        if available_at <= h and col in row.index:
            val = row[col]
            if isinstance(val, (bool, np.bool_)):
                out[col] = bool(val)
            elif pd.isna(val):
                out[col] = None
            else:
                out[col] = float(val)
    return {"levels": out, "h": round(h, 3)}


def get_news(store: Store, td: str, until: str) -> dict:
    """Stub: the economic calendar isn't built until Phase 4. Always returns an empty,
    correctly-shaped list rather than pretending news exists."""
    return {"news": [], "note": "calendar not yet imported -- see docs/ROADMAP.md Phase 4"}
