"""nylab.calendar_features -- surprise z-scores, event families, and per-day / per-session
news features attached to the DAY table (ROADMAP 4.3, SESSIONS_AND_CONTEXT.md S4).

Look-ahead rule (SESSIONS_AND_CONTEXT.md S4, enforced the same way as every other DAY column via
nylab.days.COLUMN_DOCS): a "such-and-such is SCHEDULED today" flag is known at the trading day's
open (available_at_h = -7, same status as PDH/PDL) because MT5's calendar knows the schedule
days in advance. A count/max-|z| of events *inside* a session window depends on that window's
actual releases, so it is only available once the window closes -- same available_at_h as that
session's own _high/_low columns (asia_high=0, lon_high=5, preny_high=9.5, nyam_high=10, ny_high=16).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# Ordered so a more specific family (e.g. FOMC) is matched before a catch-all (e.g. speech).
FAMILY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("NFP", re.compile(r"nonfarm payrolls|non-farm payrolls|\bnfp\b", re.I)),
    ("CPI", re.compile(r"\bcpi\b|consumer price index", re.I)),
    ("FOMC", re.compile(r"fomc|federal funds rate|fed interest rate|federal open market committee", re.I)),
    ("ECB", re.compile(r"\becb\b|main refinancing rate|deposit facility rate|european central bank", re.I)),
    ("PMI", re.compile(r"\bpmi\b|purchasing managers", re.I)),
    ("GDP", re.compile(r"\bgdp\b|gross domestic product", re.I)),
    ("retail_sales", re.compile(r"retail sales", re.I)),
    ("claims", re.compile(r"jobless claims|unemployment claims|initial claims|continuing claims", re.I)),
    ("speech", re.compile(r"speaks|speech|testimony|press conference", re.I)),
]

MIN_PRIOR_FOR_Z = 8  # RESEARCH_PROTOCOL-style honesty: don't compute a z-score off a thin history.


def classify_family(event_name: str) -> str | None:
    for family, pattern in FAMILY_PATTERNS:
        if pattern.search(event_name):
            return family
    return None


def compute_surprise(cal: pd.DataFrame) -> pd.DataFrame:
    """Adds `family`, `surprise` (actual-forecast) and `surprise_z` (surprise / stdev of that
    SAME event's PRIOR surprises only -- never including itself or future releases, and NaN
    until at least MIN_PRIOR_FOR_Z prior releases exist)."""
    cal = cal.sort_values("time_ny").reset_index(drop=True).copy()
    cal["family"] = cal["event_name"].apply(classify_family)
    cal["surprise"] = cal["actual"] - cal["forecast"]

    z = pd.Series(np.nan, index=cal.index, dtype=float)
    for _, grp in cal.groupby(["currency", "event_name"], sort=False):
        s = grp["surprise"]
        prior_std = s.shift(1).expanding().std()
        prior_n = s.shift(1).expanding().count()
        gz = s / prior_std
        gz[prior_n < MIN_PRIOR_FOR_Z] = np.nan
        gz[prior_std == 0] = np.nan
        z.loc[grp.index] = gz
    cal["surprise_z"] = z
    return cal


def _assign_td_h(time_ny: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Same td/h convention as nylab.__main__._prepare_bars and nylab.days.build_days: td is the
    trading day's label (midnight NY, trading day runs 17:00 previous calendar day -> 17:00 td),
    h is hours since that td's midnight."""
    td = (time_ny + pd.Timedelta(hours=7)).dt.normalize()
    h = (time_ny - td).dt.total_seconds() / 3600.0
    return td, h


# prefix -> (session window name in config/windows.yaml, available_at_h == that session's _high col)
SESSION_PREFIXES = {
    "asia": ("asia", 0.0),
    "lon": ("lon", 5.0),
    "preny": ("preny", 9.5),
    "nyam": ("nyam_kz", 10.0),
    "ny": ("ny", 16.0),
}

HIGH_IMPORTANCE = 3


def build_day_flags(cal: pd.DataFrame, trading_days: pd.DatetimeIndex, sessions_cfg: dict) -> pd.DataFrame:
    """One row per td in `trading_days`. Columns:
      has_nfp, has_cpi, has_fomc, has_ecb        -- bool, that family is SCHEDULED today (any currency)
      red_usd_0830                                -- bool, a high-importance USD event scheduled at h in [8,9)
      red_eur_london                              -- bool, a high-importance EUR event scheduled inside the London KZ window
      {prefix}_usd_cnt / _maxz, {prefix}_eur_cnt / _maxz  -- for prefix in SESSION_PREFIXES:
                                                              count and max(|surprise_z|) of HIGH-importance
                                                              USD/EUR events actually inside that session window
    All boolean/count/scheduling columns default to False/0/NaN for a td with no matching event --
    "nothing happened" is a real, informative value here, not missing data."""
    cal = compute_surprise(cal) if "surprise_z" not in cal.columns else cal
    td, h = _assign_td_h(cal["time_ny"])
    cal = cal.assign(td=td, h=h)
    cal = cal[cal["td"].isin(trading_days)]

    out = pd.DataFrame(index=trading_days)

    def _scheduled(mask) -> pd.Series:
        return out.index.isin(cal.loc[mask, "td"].unique())

    out["has_nfp"] = _scheduled(cal["family"] == "NFP")
    out["has_cpi"] = _scheduled(cal["family"] == "CPI")
    out["has_fomc"] = _scheduled(cal["family"] == "FOMC")
    out["has_ecb"] = _scheduled(cal["family"] == "ECB")

    lon_lo, lon_hi = sessions_cfg["lon"]
    out["red_usd_0830"] = _scheduled((cal["currency"] == "USD") & (cal["importance"] >= HIGH_IMPORTANCE) &
                                      (cal["h"] >= 8) & (cal["h"] < 9))
    out["red_eur_london"] = _scheduled((cal["currency"] == "EUR") & (cal["importance"] >= HIGH_IMPORTANCE) &
                                        (cal["h"] >= lon_lo) & (cal["h"] < lon_hi))

    hi = cal[cal["importance"] >= HIGH_IMPORTANCE]
    for prefix, (session_name, _avail) in SESSION_PREFIXES.items():
        lo, hi_h = sessions_cfg[session_name]
        win = hi[(hi["h"] >= lo) & (hi["h"] < hi_h)]
        for ccy in ("usd", "eur"):
            sub = win[win["currency"] == ccy.upper()]
            cnt = sub.groupby("td").size().reindex(trading_days, fill_value=0)
            maxz = sub.assign(absz=sub["surprise_z"].abs()).groupby("td")["absz"].max().reindex(trading_days)
            out[f"{prefix}_{ccy}_cnt"] = cnt
            out[f"{prefix}_{ccy}_maxz"] = maxz

    return out


def column_docs() -> dict[str, float]:
    """available_at_h for every column build_day_flags() can produce -- merged into
    nylab.days.COLUMN_DOCS so the Phase 3 look-ahead check covers calendar columns too. Also
    registers the `day_`-prefixed ALIASES nylab.days.attach_calendar_features adds for the
    scheduling/news flags (SESSIONS_AND_CONTEXT S5.2's `day.has_fomc` dotted-DSL example) --
    same availability as the bare name, since it's the exact same underlying column."""
    base = {"has_nfp": -7.0, "has_cpi": -7.0, "has_fomc": -7.0, "has_ecb": -7.0,
            "red_usd_0830": -7.0, "red_eur_london": -7.0}
    docs = dict(base)
    docs.update({f"day_{k}": v for k, v in base.items()})
    for prefix, (_session, avail) in SESSION_PREFIXES.items():
        for ccy in ("usd", "eur"):
            docs[f"{prefix}_{ccy}_cnt"] = avail
            docs[f"{prefix}_{ccy}_maxz"] = avail
    return docs


# ROADMAP 5.7.2: each SESSION_PREFIXES session's own lo bound (config/windows.yaml), i.e. the
# hour a `{prefix}_usd_cnt`/`{prefix}_usd_maxz` count actually starts scanning for events -- it
# has to walk the WHOLE session window (any event inside it could be the one counted), same
# "genuinely needs the whole window, not just its own endpoint" status as that session's own
# _high/_low columns. The bare scheduling flags (has_nfp, red_usd_0830, ...) are NOT aggregates
# over a window -- MT5's calendar knows the schedule the instant the day opens -- so they are
# deliberately left out here and fall back to their own available_at_h (a point value, no
# overlap risk) via nylab.hyp_loader's `.get(col, avail)` default.
_SESSION_LO = {"asia": -4.0, "lon": 2.0, "preny": 7.0, "nyam_kz": 7.0, "ny": 7.0}


def column_starts_at_h() -> dict[str, float]:
    """starts_at_h for the session event-count/max-|z| columns (ROADMAP 5.7.2) -- merged into
    nylab.days.COLUMN_STARTS_AT_H the same way column_docs() merges into COLUMN_DOCS."""
    docs: dict[str, float] = {}
    for prefix, (session_name, _avail) in SESSION_PREFIXES.items():
        lo = _SESSION_LO[session_name]
        for ccy in ("usd", "eur"):
            docs[f"{prefix}_{ccy}_cnt"] = lo
            docs[f"{prefix}_{ccy}_maxz"] = lo
    return docs
