"""nylab.days -- build the DAY table (one row per trading day) from canonical NY-time bars.

Ported from ny_session_lab.py's window()/open_at()/first_cross()/build_days() -- same column
semantics, same numbers. C is now the dict produced by nylab.config.legacy_windows() (YAML)
instead of a hardcoded CONFIG dict (ROADMAP 1.2). window()/open_at()/first_cross() are kept
public (not _prefixed) so tests can exercise them directly for look-ahead (AT-03).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import calendar_features

# ROADMAP 1.6: the latest NY hour (relative to td midnight) at which each DAY column's value is
# known. Starting Phase 3, a hypothesis/model may only condition on a column whose
# available_at_h <= its own decision_time_h (RESEARCH_PROTOCOL.md S3) -- this is how look-ahead
# gets prevented structurally, not just by convention.
COLUMN_DOCS = {
    "day_open": -7, "day_high": 17, "day_low": 17, "day_close": 17, "day_hi_t": 17, "day_lo_t": 17,
    "asia_open": -4, "asia_high": 0, "asia_low": 0, "asia_close": 0, "asia_hi_t": 0, "asia_lo_t": 0,
    "lon_open": 2, "lon_high": 5, "lon_low": 5, "lon_close": 5, "lon_hi_t": 5, "lon_lo_t": 5,
    "preny_open": 7, "preny_high": 9.5, "preny_low": 9.5, "preny_close": 9.5, "preny_hi_t": 9.5, "preny_lo_t": 9.5,
    "ny_open": 7, "ny_high": 16, "ny_low": 16, "ny_close": 16, "ny_hi_t": 16, "ny_lo_t": 16,
    "nyam_open": 7, "nyam_high": 10, "nyam_low": 10, "nyam_close": 10, "nyam_hi_t": 10, "nyam_lo_t": 10,
    "mid_open": 0, "o0830": 8.5, "o0930": 9.5,
    "cbdr_high": -4, "cbdr_low": -4,
    "pdh": -7, "pdl": -7,
    "day_range": 17, "adr5": -7, "adr20": -7,
    "pwh": -7, "pwl": -7,
    "asia_range": 0, "lon_range": 5, "ny_range": 16, "cbdr_range": -4,
    "tilopen_high": 9.5, "tilopen_low": 9.5, "adr_used_0930": 9.5,
    "ny_takes_lon_high": 16, "ny_takes_lon_high_t": 16, "ny_takes_lon_low": 16, "ny_takes_lon_low_t": 16,
    "ny_takes_pdh": 16, "ny_takes_pdh_t": 16, "ny_takes_pdl": 16, "ny_takes_pdl_t": 16,
    "ny_takes_asia_high": 16, "ny_takes_asia_high_t": 16, "ny_takes_asia_low": 16, "ny_takes_asia_low_t": 16,
    "pre_takes_lon_high": 9.5, "pre_takes_lon_low": 9.5, "pre_takes_pdh": 9.5, "pre_takes_pdl": 9.5,
    "lon_dir": 5, "preny_dir": 9.5, "ny_drive": 16, "newshr_dir": 9.5, "day_dir": 17, "prev_day_dir": -7,
    "ny_close_back_below_lon_high": 16, "ny_close_back_above_lon_low": 16,
    "ny_hits_asia_+1sd": 16, "ny_hits_asia_-1sd": 16, "ny_hits_asia_+2sd": 16, "ny_hits_asia_-2sd": 16,
    "ny_hits_asia_+2.5sd": 16, "ny_hits_asia_-2.5sd": 16,
    "dow": -7, "ny_forms_day_high": 17, "ny_forms_day_low": 17,
}
COLUMN_DOCS.update(calendar_features.column_docs())  # ROADMAP 4.3: news columns join the
# same look-ahead registry as everything else -- nylab.hyp_loader checks this dict, not two.


def window(df: pd.DataFrame, lo: float, hi: float, name: str) -> pd.DataFrame:
    sub = df[(df.h >= lo) & (df.h < hi)]
    g = sub.groupby("td")
    return pd.DataFrame({
        f"{name}_open": g["open"].first(), f"{name}_high": g["high"].max(),
        f"{name}_low": g["low"].min(), f"{name}_close": g["close"].last(),
        f"{name}_hi_t": sub.loc[g["high"].idxmax(), ["td", "h"]].set_index("td")["h"],
        f"{name}_lo_t": sub.loc[g["low"].idxmin(), ["td", "h"]].set_index("td")["h"],
    })


def open_at(df: pd.DataFrame, hour: float, name: str) -> pd.Series:
    sub = df[(df.h >= hour) & (df.h < hour + 0.5)]
    return sub.groupby("td")["open"].first().rename(name)


def first_cross(df: pd.DataFrame, lo: float, hi: float, level_series: pd.Series, above: bool = True) -> pd.Series:
    """First NY-clock hour inside [lo,hi) when price trades beyond a per-day level."""
    sub = df[(df.h >= lo) & (df.h < hi)].join(level_series.rename("lvl"), on="td")
    hit = sub[sub.high > sub.lvl] if above else sub[sub.low < sub.lvl]
    return hit.groupby("td")["h"].first()


def build_days(df: pd.DataFrame, C: dict) -> pd.DataFrame:
    """df: canonical bars with columns ny, td, h, open, high, low, close (+ optional spread_pts).
    C: dict from nylab.config.legacy_windows() -- {pip, asia, london_kz, pre_ny, ny, ny_am_kz}."""
    pip = C["pip"]
    ny = df.set_index("ny")
    day = window(df, -7, 17, "day")
    parts = [
        day,
        window(df, *C["asia"], "asia"),  # windows.yaml already stores this h-relative (SESSIONS_AND_CONTEXT S1), no extra -24 shift needed
        window(df, *C["london_kz"], "lon"),
        window(df, *C["pre_ny"], "preny"),
        window(df, *C["ny"], "ny"),
        window(df, *C["ny_am_kz"], "nyam"),
        open_at(df, 0, "mid_open"), open_at(df, 8.5, "o0830"), open_at(df, 9.5, "o0930"),
    ]
    d = pd.concat(parts, axis=1).sort_index()

    # CBDR spans the td boundary (14:00-20:00 NY, ending inside this td's evening) -- computed
    # from absolute NY timestamps, not the h-relative window() helper.
    cb = []
    for td in d.index:
        t0 = td - pd.Timedelta(hours=7)  # 17:00 NY of the previous calendar day
        s = ny.loc[t0 - pd.Timedelta(hours=3): t0 + pd.Timedelta(hours=3) - pd.Timedelta(seconds=1)]
        cb.append((s.high.max(), s.low.min()) if len(s) else (np.nan, np.nan))
    d["cbdr_high"], d["cbdr_low"] = zip(*cb)

    d["pdh"], d["pdl"] = d["day_high"].shift(1), d["day_low"].shift(1)
    d["day_range"] = (d.day_high - d.day_low) / pip
    d["adr5"] = d["day_range"].shift(1).rolling(5).mean()
    d["adr20"] = d["day_range"].shift(1).rolling(20).mean()
    d["asia_range"] = (d.asia_high - d.asia_low) / pip
    d["lon_range"] = (d.lon_high - d.lon_low) / pip
    d["ny_range"] = (d.ny_high - d.ny_low) / pip
    d["cbdr_range"] = (d.cbdr_high - d.cbdr_low) / pip

    pre = window(df, -7, 9.5, "tilopen")
    d = d.join(pre[["tilopen_high", "tilopen_low"]])
    d["adr_used_0930"] = (d.tilopen_high - d.tilopen_low) / pip / d.adr5

    for lvl, col, above in [("lon_high", "ny_takes_lon_high", True), ("lon_low", "ny_takes_lon_low", False),
                            ("pdh", "ny_takes_pdh", True), ("pdl", "ny_takes_pdl", False),
                            ("asia_high", "ny_takes_asia_high", True), ("asia_low", "ny_takes_asia_low", False)]:
        t = first_cross(df, *C["ny"], d[lvl], above)
        d[col] = d.index.isin(t.index)
        d[col + "_t"] = t

    for lvl, col, above in [("lon_high", "pre_takes_lon_high", True), ("lon_low", "pre_takes_lon_low", False),
                            ("pdh", "pre_takes_pdh", True), ("pdl", "pre_takes_pdl", False)]:
        t = first_cross(df, *C["pre_ny"], d[lvl], above)
        d[col] = d.index.isin(t.index)

    d["lon_dir"] = np.sign(d.lon_close - d.lon_open)
    d["preny_dir"] = np.sign(d.preny_close - d.preny_open)
    d["ny_drive"] = np.sign(d.ny_close - d.o0930)
    d["newshr_dir"] = np.sign(d.o0930 - d.o0830)
    d["day_dir"] = np.sign(d.day_close - d.day_open)
    d["prev_day_dir"] = d["day_dir"].shift(1)

    d["ny_close_back_below_lon_high"] = d.ny_takes_lon_high & (d.ny_close < d.lon_high)
    d["ny_close_back_above_lon_low"] = d.ny_takes_lon_low & (d.ny_close > d.lon_low)

    ar = d.asia_high - d.asia_low
    for k in (1, 2, 2.5):
        d[f"ny_hits_asia_+{k}sd"] = d.ny_high >= d.asia_high + k * ar
        d[f"ny_hits_asia_-{k}sd"] = d.ny_low <= d.asia_low - k * ar

    d["dow"] = d.index.dayofweek
    d["ny_forms_day_high"] = d.ny_high >= d.day_high
    d["ny_forms_day_low"] = d.ny_low <= d.day_low

    # PWH/PWL (Phase 2 gap-close): previous COMPLETED calendar week's high/low, mapped onto
    # every day of the following week. Known the instant that week starts trading (same
    # available_at_h as PDH/PDL, -7) since it is entirely historical by then. Trading weeks
    # never contain a Sat/Sun td (already filtered upstream), so grouping by ISO (year, week)
    # cleanly buckets Mon-Fri without a manual Sun-Fri boundary.
    iso = d.index.isocalendar()
    week_key = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    wk = pd.DataFrame({"h": d["day_high"], "l": d["day_low"], "wk": week_key}).groupby("wk").agg(
        wk_high=("h", "max"), wk_low=("l", "min")
    ).shift(1)
    d["pwh"] = week_key.map(wk["wk_high"])
    d["pwl"] = week_key.map(wk["wk_low"])

    return d.dropna(subset=["ny_open", "lon_open", "o0930", "ny_close"])


def attach_calendar_features(d: pd.DataFrame, calendar: pd.DataFrame, sessions_cfg: dict) -> pd.DataFrame:
    """ROADMAP 4.3: join the news day-flags (has_nfp/has_cpi/has_fomc/has_ecb, red_usd_0830,
    red_eur_london) and per-session high-importance USD/EUR event counts + max|surprise_z| onto
    the DAY table `d`. `calendar` is nylab.calendar_io's canonical schema (time_ny/currency/
    event_name/importance/actual/forecast/previous); `sessions_cfg` is nylab.config.sessions().
    Purely additive -- every column it adds is already registered in COLUMN_DOCS above, so a
    hypothesis referencing one is look-ahead-checked exactly like any other DAY column."""
    flags = calendar_features.build_day_flags(calendar, d.index, sessions_cfg)
    # SESSIONS_AND_CONTEXT.md S5.2's own example hypothesis writes `day.has_fomc` -- the
    # dotted DSL rewrite (nylab.hyp_dsl) turns that into `day_has_fomc`, but these particular
    # flags were joined onto `d` bare (has_fomc, not day_has_fomc) back in Phase 4, before any
    # dotted "day.x" convention existed. Add `day_`-prefixed ALIASES (same Series, not copies)
    # for exactly the day-level scheduling/news flags so `day.has_fomc` resolves, without
    # renaming or removing the original bare names anything Phase 4 already depends on.
    aliased = flags.rename(columns={c: f"day_{c}" for c in flags.columns})
    return d.join(flags).join(aliased)
