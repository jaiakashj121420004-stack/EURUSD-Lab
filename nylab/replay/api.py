"""nylab.replay.api -- the no-leak JSON API (REPLAY_TRAINER.md S7).

The server NEVER sends a bar, level or news-actual later than the caller's `until` timestamp.
Every function here takes `until` and filters by it; there is no code path that returns
unrevealed data. This module has no HTTP framing -- server.py wires it to routes so this stays
directly unit-testable.

ROADMAP 6.1/6.2/6.5 (2026-09-27): `list_days()` now does real filtering on session character,
news, raids, ADR ratio and a free-text DSL expression (the SAME safe DSL nylab.hyp_dsl already
uses for hypotheses -- no second expression language to maintain), and enforces the "hide
outcome columns" toggle for real. Both depend on `nylab run` having attached session-feature and
calendar columns to the day table before it was cached -- a cache built before Phase 5/4 (or a
test fixture that only calls `days_mod.build_days()` directly) simply won't HAVE those columns,
so every new filter/column here is written to check `col in d.columns` first and either skip
gracefully or return a clear error, never crash on an older/thinner cache. get_news() also does
real work now, reading calendar events attached to the Store at server startup (server.py).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from nylab import calendar_features
from nylab import hyp_dsl
from nylab import sessions as sessions_mod
from nylab.days import COLUMN_DOCS

RESAMPLE_RULE = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1D"}

# Character label vocabulary (nylab.sessions._label_character) -- exposed so the frontend can
# build a fixed multi-select instead of scraping distinct values off whatever happens to be in
# the cache.
SESSION_CHARACTERS = ["chop", "quiet", "normal", "trend", "reversal", "range_both"]
DAY_TYPES = ["inside_day", "outside_day", "trend_day", "reversal_day", "range_day", "normal_day"]

# Scheduling flags: known the moment the trading day opens (available_at_h -7, same status as
# PDH/PDL) -- these are NOT spoilers, they're "an event is on the calendar today", exactly what
# a real economic calendar shows you in advance.
NEWS_SCHEDULE_FLAGS = ["has_nfp", "has_cpi", "has_fomc", "has_ecb", "red_usd_0830", "red_eur_london"]

# Raid/level-take flags a filter can require (REPLAY_TRAINER.md S3 "raids: e.g. NY AM took
# London high"). All already exist on the day table (nylab/days.py).
RAID_FLAGS = ["ny_takes_lon_high", "ny_takes_lon_low", "ny_takes_pdh", "ny_takes_pdl",
              "ny_takes_asia_high", "ny_takes_asia_low", "ny_forms_day_high", "ny_forms_day_low"]


def _outcome_columns() -> set[str]:
    """Columns that describe how the day's later sessions actually went -- exactly what
    REPLAY_TRAINER.md S3's 'hide outcome columns' toggle exists to hide. Built from
    nylab.sessions.SESSION_IDS rather than hand-listed so a new session id is covered
    automatically. The per-session news COUNT/max-|z| columns (build_day_flags' `{prefix}_
    {ccy}_cnt`/`_maxz`) are outcome too -- they measure what actually happened in the window,
    unlike the schedule flags in NEWS_SCHEDULE_FLAGS above, which are known in advance."""
    cols = {f"{sid}_character" for sid in sessions_mod.SESSION_IDS}
    cols |= {"day_type", "day_range", "ny_range", "lon_range", "asia_range", "cbdr_range",
             "ny_drive", "ny_forms_day_high", "ny_forms_day_low",
             "ny_close_back_below_lon_high", "ny_close_back_above_lon_low"}
    cols |= set(RAID_FLAGS)
    for prefix in calendar_features.SESSION_PREFIXES:
        for ccy in ("usd", "eur"):
            cols.add(f"{prefix}_{ccy}_cnt")
            cols.add(f"{prefix}_{ccy}_maxz")
    return cols


OUTCOME_COLUMNS = _outcome_columns()


class Store:
    """Holds the cached bars/days (+ optional calendar events) in memory, loaded once at server
    startup (REPLAY_TRAINER S1)."""

    def __init__(self, bars: pd.DataFrame, days: pd.DataFrame, cal: pd.DataFrame | None = None):
        self.bars = bars.sort_values("ny").reset_index(drop=True)
        self.days = days
        self.bars_by_td = {td: g for td, g in self.bars.groupby("td")}
        self.cal = None
        if cal is not None and len(cal):
            cal = calendar_features.compute_surprise(cal) if "surprise_z" not in cal.columns else cal
            td, h = calendar_features._assign_td_h(cal["time_ny"])
            self.cal = cal.assign(td=td, h=h).sort_values("time_ny").reset_index(drop=True)


def _parse_until(until: str) -> pd.Timestamp:
    return pd.Timestamp(until)


class DayFilterError(ValueError):
    """A filter the caller asked for can't be applied to this cache (unknown column, bad DSL,
    etc.) -- distinct from a plain bug so server.py can turn it into a clean 400."""


def list_days(store: Store, date_from=None, date_to=None, weekdays=None,
              exclude_thin=True, thin_flags: pd.DataFrame | None = None,
              session_character: dict[str, list[str]] | None = None,
              news_flags: list[str] | None = None, raid_flags: list[str] | None = None,
              adr_min: float | None = None, adr_max: float | None = None,
              dsl: str | None = None, hide_outcome: bool = True) -> dict:
    """Day list for the navigator table (REPLAY_TRAINER.md S3). Returns
    {"days": [...], "count": n, "spoiler_filter_used": bool, "total_before_filters": n}.

    `hide_outcome=True` (the default while practising) blanks every OUTCOME_COLUMNS value in
    each returned row to None -- but a filter is still free to USE those columns (raids, session
    character, the DSL); when one does, `spoiler_filter_used` comes back True so the frontend can
    show REPLAY_TRAINER.md S3's spoiler warning icon ("filters on those columns still work but
    show a spoiler warning icon") instead of silently un-hiding data."""
    d = store.days
    idx = d.index
    if date_from:
        idx = idx[idx >= pd.Timestamp(date_from)]
    if date_to:
        idx = idx[idx <= pd.Timestamp(date_to)]
    d = d.loc[idx]
    total_before = len(d)
    if weekdays:
        d = d[d["dow"].isin(weekdays)]

    spoiler_filter_used = False
    mask = pd.Series(True, index=d.index)

    if session_character:
        for sid, chars in session_character.items():
            col = f"{sid}_character"
            if col not in d.columns:
                raise DayFilterError(f"no '{col}' column in this cache -- was this session run "
                                      f"through the Phase 5 session-table pipeline?")
            if chars:
                mask &= d[col].isin(chars)
                spoiler_filter_used = True

    if news_flags:
        for col in news_flags:
            if col not in d.columns:
                raise DayFilterError(f"no '{col}' news column in this cache -- was a calendar "
                                      f"attached when `nylab run` built it (--calendar)?")
            mask &= d[col].fillna(False).astype(bool)
            if col not in NEWS_SCHEDULE_FLAGS:
                spoiler_filter_used = True  # a realized count/surprise column, not a schedule flag

    if raid_flags:
        for col in raid_flags:
            if col not in d.columns:
                raise DayFilterError(f"no '{col}' column in this cache")
            mask &= d[col].fillna(False).astype(bool)
            spoiler_filter_used = True

    if adr_min is not None or adr_max is not None:
        if "adr_used_0930" not in d.columns:
            raise DayFilterError("no 'adr_used_0930' column in this cache")
        if adr_min is not None:
            mask &= d["adr_used_0930"] >= adr_min
        if adr_max is not None:
            mask &= d["adr_used_0930"] <= adr_max

    if dsl:
        try:
            tree = hyp_dsl.parse(dsl)
            hyp_dsl.validate(tree)
            referenced = hyp_dsl.referenced_columns(tree)
        except hyp_dsl.DSLError as e:
            raise DayFilterError(f"filter expression: {e}") from e
        missing = [c for c in referenced if c not in d.columns]
        if missing:
            raise DayFilterError(f"filter expression uses unknown column(s): {sorted(missing)}")
        ns = {c: d[c] for c in d.columns}
        try:
            dsl_mask = hyp_dsl.evaluate(dsl, ns)
        except hyp_dsl.DSLError as e:
            raise DayFilterError(f"filter expression: {e}") from e
        dsl_mask = pd.Series(dsl_mask, index=d.index).reindex(d.index).fillna(False).astype(bool)
        mask &= dsl_mask
        if referenced & OUTCOME_COLUMNS:
            spoiler_filter_used = True

    d = d[mask]

    rows = []
    thin_lookup = thin_flags["thin_day"].to_dict() if thin_flags is not None else {}
    gappy_lookup = thin_flags["gappy"].to_dict() if thin_flags is not None else {}
    for td, r in d.iterrows():
        thin = bool(thin_lookup.get(td, False))
        if exclude_thin and thin:
            continue
        row = dict(
            date=td.strftime("%Y-%m-%d"), weekday=int(r["dow"]),
            thin_day=thin, gappy=bool(gappy_lookup.get(td, False)),
        )
        outcome_vals = dict(
            day_range_pips=None if pd.isna(r.get("day_range")) else round(float(r["day_range"]), 1),
            ny_range_pips=None if pd.isna(r.get("ny_range")) else round(float(r["ny_range"]), 1),
            lon_range_pips=None if pd.isna(r.get("lon_range")) else round(float(r["lon_range"]), 1),
            ny_takes_lon_high=bool(r.get("ny_takes_lon_high", False)),
            ny_takes_lon_low=bool(r.get("ny_takes_lon_low", False)),
            day_type=r.get("day_type") if "day_type" in d.columns else None,
        )
        for sid in sessions_mod.SESSION_IDS:
            col = f"{sid}_character"
            if col in d.columns:
                val = r.get(col)
                outcome_vals[col] = None if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val)
        if hide_outcome:
            row["outcome"] = None
            row["has_outcome_data"] = True
        else:
            row["outcome"] = outcome_vals
        rows.append(row)

    return {
        "days": rows, "count": len(rows), "total_before_filters": total_before,
        "spoiler_filter_used": spoiler_filter_used,
    }


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
    """Only levels whose available_at_h <= the NY hour of `until` on this td (REPLAY_TRAINER S7).
    ROADMAP 6.4: this already returns every column once `until` reaches day-close (h=17) -- the
    review-mode overlay is just this same call made with an end-of-day `until`, not a separate
    code path (one no-leak rule, not two)."""
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
            elif isinstance(val, str):
                out[col] = val
            elif pd.isna(val):
                out[col] = None
            else:
                out[col] = float(val)
    return {"levels": out, "h": round(h, 3)}


def get_news(store: Store, td: str, until: str) -> dict:
    """Economic-calendar events for trading day `td` (ROADMAP 6.5). A scheduled event's time/
    name/currency/importance/forecast/previous show as soon as the day is loaded (the calendar
    is known in advance -- available_at_h -7, same as PDH/PDL); `actual`/`surprise`/`surprise_z`
    are withheld (null) until the event's own release time has actually been reached by `until`,
    same no-leak rule as everything else in this module. If no calendar was attached when this
    cache was built, returns an empty list with a note rather than pretending news exists."""
    if store.cal is None:
        return {"news": [], "note": "no calendar attached to this cache -- see docs/ROADMAP.md Phase 4"}
    td_ts = pd.Timestamp(td)
    until_ts = _parse_until(until)
    until_h = (until_ts - (td_ts - pd.Timedelta(hours=7))).total_seconds() / 3600.0 - 7

    day_events = store.cal[store.cal["td"] == td_ts]
    out = []
    for _, r in day_events.iterrows():
        released = r["h"] <= until_h
        out.append(dict(
            time=int(r["time_ny"].timestamp()), h=round(float(r["h"]), 3), currency=r["currency"],
            event_name=r["event_name"], family=r.get("family"),
            importance=int(r["importance"]), forecast=_num_or_none(r.get("forecast")),
            previous=_num_or_none(r.get("previous")),
            actual=_num_or_none(r.get("actual")) if released else None,
            surprise=_num_or_none(r.get("surprise")) if released else None,
            surprise_z=_num_or_none(r.get("surprise_z")) if released else None,
            released=bool(released),
        ))
    return {"news": out}


def _num_or_none(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return float(v)
