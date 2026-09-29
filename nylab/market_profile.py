"""nylab.market_profile -- Akash's "help me understand EURUSD itself" request (2026-09-28/29):
a DESCRIPTIVE map of how the market has behaved over the loaded history, built entirely from
data the lab already computes (nylab.sessions' SESSION table, nylab.days' day table, the M5
bars themselves). No new price-action detection, no new statistical claims of "this is a real
edge" -- see the distinction below before trusting any number this module produces.

IMPORTANT -- how this differs from nylab.hyp_engine (read before trusting a table here):
nylab.hyp_engine tests a small, PRE-REGISTERED list of ideas (config/hypotheses/*.yaml), one at
a time, with a Bonferroni penalty for how many were tried and an out-of-sample holdout -- that
discipline is what lets a hyp_engine "yes" be trusted as a real, tradeable edge.
This module instead slices the same years of history dozens of ways AT ONCE -- every
session-pair combination, every hour of the day, every weekday, every quarter... With that many
slices shown side by side, some WILL look like a striking pattern purely by chance, the same
trap hyp_engine's whole design exists to avoid. Every table below reports its sample size (n)
honestly and flags any row with n < LOW_N as low-confidence (`low_n=True`), but it deliberately
does NOT apply a multiple-testing correction on top -- that would be false precision for
something meant to build intuition, not to greenlight a trade. If a slice here looks
interesting enough to trade, the right next step is to write it up as its own hypothesis in
config/hypotheses/ and let it earn a real verdict the way H001-H016 did -- not to act on it
straight from this report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOW_N = 20  # below this many trading days, a row is flagged low-confidence rather than hidden


def _pct_counts(s: pd.Series) -> dict:
    """{value: pct} for a small categorical/discrete series, ignoring NaNs. Used throughout for
    'what fraction of days were up/down/flat' or 'what fraction were each character label'."""
    s = s.dropna()
    if not len(s):
        return {}
    return (s.value_counts(normalize=True)).to_dict()


def _dir_label(x) -> str:
    if pd.isna(x):
        return "n/a"
    if x > 0:
        return "up"
    if x < 0:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# 1. Session relationship map: "if predecessor session(s) looked like X, what did
#    the outcome session usually do?"
# ---------------------------------------------------------------------------

def session_relationship_table(d: pd.DataFrame, predecessor_cols: list[str], outcome_col: str,
                                outcome_kind: str = "dir") -> pd.DataFrame:
    """For every combination of values seen in `predecessor_cols` (e.g.
    ["asia_character", "lon_character"]), summarize what `outcome_col` (e.g. "nyam_full_dir")
    usually did. `outcome_kind`: "dir" (numeric sign column -> up/down/flat percentages) or
    "character" (categorical -> percentage of each label).

    Returns one row per predecessor combination actually observed, sorted by n descending:
    columns = predecessor_cols + ['n', 'low_n', <outcome label columns...>, 'dominant',
    'dominant_pct']. A combination seen on fewer than LOW_N days is kept (not hidden -- rare
    combinations are still informative) but flagged `low_n=True`."""
    cols = list(predecessor_cols) + [outcome_col]
    sub = d[cols].dropna(subset=predecessor_cols).copy()
    if outcome_kind == "dir":
        sub["_outcome"] = sub[outcome_col].map(_dir_label)
    else:
        sub["_outcome"] = sub[outcome_col]

    rows = []
    for key, grp in sub.groupby(predecessor_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        counts = _pct_counts(grp["_outcome"])
        n = int(grp["_outcome"].notna().sum())
        if not counts:
            continue
        dominant = max(counts, key=counts.get)
        row = dict(zip(predecessor_cols, key))
        row["n"] = n
        row["low_n"] = n < LOW_N
        row.update({f"pct_{k}": v for k, v in counts.items()})
        row["dominant"] = dominant
        row["dominant_pct"] = counts[dominant]
        rows.append(row)

    out = pd.DataFrame(rows)
    return out.sort_values("n", ascending=False).reset_index(drop=True) if len(out) else out


# ---------------------------------------------------------------------------
# 2. In-session timing: does an EARLY sweep of the predecessor session's level lead
#    to a different outcome than a late or missing one? What does a quiet start lead to?
# ---------------------------------------------------------------------------

def early_raid_outcome_table(d: pd.DataFrame, sid: str, session_start_h: float,
                              outcome_col: str, outcome_kind: str = "character",
                              early_minutes: float = 60.0) -> pd.DataFrame:
    """Buckets each day into 'early sweep' (the session's first raid of a prior level happened
    within `early_minutes` of the session's own open), 'late sweep' (happened, but later), or
    'no sweep', using the SESSION table's own `<sid>_first_raid_t` column (already computed by
    nylab.sessions -- no new detection here). Reports how `outcome_col` (e.g. `<sid>_character`
    or `<sid>_dir`) played out in each bucket."""
    t_col, out_col = f"{sid}_first_raid_t", outcome_col
    sub = d[[t_col, out_col]].copy()
    elapsed = sub[t_col] - session_start_h
    bucket = pd.Series("no sweep", index=sub.index, dtype=object)
    bucket[sub[t_col].notna() & (elapsed <= early_minutes / 60.0)] = "early sweep"
    bucket[sub[t_col].notna() & (elapsed > early_minutes / 60.0)] = "late sweep"
    sub["_bucket"] = bucket
    sub["_outcome"] = sub[out_col].map(_dir_label) if outcome_kind == "dir" else sub[out_col]

    rows = []
    for bkt, grp in sub.groupby("_bucket"):
        counts = _pct_counts(grp["_outcome"])
        n = int(grp["_outcome"].notna().sum())
        if not counts:
            continue
        dominant = max(counts, key=counts.get)
        rows.append({"bucket": bkt, "n": n, "low_n": n < LOW_N,
                      **{f"pct_{k}": v for k, v in counts.items()},
                      "dominant": dominant, "dominant_pct": counts[dominant]})
    order = {"early sweep": 0, "late sweep": 1, "no sweep": 2}
    out = pd.DataFrame(rows)
    return out.sort_values("bucket", key=lambda s: s.map(order)).reset_index(drop=True) if len(out) else out


def quiet_start_outcome_table(d: pd.DataFrame, sid: str, outcome_col: str = None) -> pd.DataFrame:
    """'Sessions that opened quiet -- what did they usually turn into?' Reuses the SESSION
    table's own `<sid>_range_rel` (this session's range vs its trailing 20-day median) as the
    'quiet so far' signal and `<sid>_character` (already labelled by nylab.sessions) as the
    outcome -- both pre-existing columns, no new thresholds invented here."""
    outcome_col = outcome_col or f"{sid}_character"
    rr = d[f"{sid}_range_rel"]
    sub = pd.DataFrame({"_outcome": d[outcome_col]})
    sub["_bucket"] = np.where(rr < 0.6, "quiet so far (range_rel<0.6)",
                       np.where(rr > 1.4, "already active (range_rel>1.4)", "typical"))
    sub.loc[rr.isna(), "_bucket"] = None

    rows = []
    for bkt, grp in sub.dropna(subset=["_bucket"]).groupby("_bucket"):
        counts = _pct_counts(grp["_outcome"])
        n = int(grp["_outcome"].notna().sum())
        if not counts:
            continue
        dominant = max(counts, key=counts.get)
        rows.append({"bucket": bkt, "n": n, "low_n": n < LOW_N,
                      **{f"pct_{k}": v for k, v in counts.items()},
                      "dominant": dominant, "dominant_pct": counts[dominant]})
    return pd.DataFrame(rows).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Hour-of-day profile (bar-level): which hour tends to move the most / least,
#    and which way, across the whole loaded history.
# ---------------------------------------------------------------------------

def hour_of_day_profile(df: pd.DataFrame, pip: float) -> pd.DataFrame:
    """df: canonical bars with an `ny` (New York local) timestamp column and open/high/low/close.
    For each NY clock hour (0-23), across every calendar day in the data: the median pip range
    covered in that hour, and what fraction of those hourly candles closed above their open.
    Purely descriptive -- this is 'what usually happens', not a claim any hour is tradeable on
    its own."""
    x = df.copy()
    x["_date"] = x["ny"].dt.date
    x["_hour"] = x["ny"].dt.hour
    g = x.groupby(["_date", "_hour"])
    hourly = g.agg(hi=("high", "max"), lo=("low", "min"), op=("open", "first"), cl=("close", "last")).reset_index()
    hourly["range_pips"] = (hourly["hi"] - hourly["lo"]) / pip
    hourly["up"] = hourly["cl"] > hourly["op"]

    out = hourly.groupby("_hour").agg(
        n_days=("range_pips", "count"),
        median_range_pips=("range_pips", "median"),
        mean_range_pips=("range_pips", "mean"),
        pct_up=("up", "mean"),
    ).reset_index().rename(columns={"_hour": "ny_hour"})
    out["low_n"] = out["n_days"] < LOW_N
    return out.sort_values("ny_hour").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. News reaction: does a session with high-importance news behave differently
#    than one without, on the SESSION table's own news columns?
# ---------------------------------------------------------------------------

def news_reaction_table(d: pd.DataFrame, sid: str, currency: str = "usd") -> pd.DataFrame:
    """Compares `<sid>_range_rel` and `<sid>_dir` on days with vs without at least one
    high-importance {currency} release inside that session window (`<sid>_news_high_{currency}`,
    already computed by nylab.sessions/nylab.calendar_features -- no new news logic here)."""
    news_col, rr_col, dir_col = f"{sid}_news_high_{currency}", f"{sid}_range_rel", f"{sid}_dir"
    if news_col not in d.columns:
        return pd.DataFrame()
    sub = d[[news_col, rr_col, dir_col]].copy()
    sub["_group"] = np.where(sub[news_col].fillna(0) > 0,
                              f"{currency.upper()} high-impact news in window",
                              "no high-impact news in window")
    sub["_dirlabel"] = sub[dir_col].map(_dir_label)

    rows = []
    for grp_name, grp in sub.groupby("_group"):
        counts = _pct_counts(grp["_dirlabel"])
        n = int(grp[rr_col].notna().sum())
        rows.append({"group": grp_name, "n": n, "low_n": n < LOW_N,
                      "median_range_rel": grp[rr_col].median(),
                      **{f"pct_{k}": v for k, v in counts.items()}})
    return pd.DataFrame(rows).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5. Seasonality: weekday / month / quarter profiles.
# ---------------------------------------------------------------------------

_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_QUARTER_NAMES = {1: "Q1 (Jan-Mar)", 2: "Q2 (Apr-Jun)", 3: "Q3 (Jul-Sep)", 4: "Q4 (Oct-Dec)"}


def weekday_profile(d: pd.DataFrame) -> pd.DataFrame:
    """Per calendar weekday (Mon-Fri): typical day range, and how often that day's direction
    was up/down/flat. Uses `d['dow']` and `d['day_range']`/`d['day_dir']`, both already
    computed by nylab.days -- no new logic."""
    sub = d[["dow", "day_range", "day_dir"]].dropna(subset=["dow"]).copy()
    sub["_dirlabel"] = sub["day_dir"].map(_dir_label)
    rows = []
    for dow, grp in sub.groupby("dow"):
        if dow not in range(5):
            continue
        counts = _pct_counts(grp["_dirlabel"])
        n = int(grp["day_range"].notna().sum())
        rows.append({"weekday": _WEEKDAY_NAMES[int(dow)], "dow": int(dow), "n": n, "low_n": n < LOW_N,
                      "median_range_pips": grp["day_range"].median(),
                      **{f"pct_{k}": v for k, v in counts.items()}})
    return pd.DataFrame(rows).sort_values("dow").reset_index(drop=True)


def weekday_extremes_table(d: pd.DataFrame) -> pd.DataFrame:
    """'Which weekday most often sets the WEEK's high or low?' For each ISO week, compares
    every day's day_high/day_low against that week's max/min (computed only from days already
    in that week -- no look-ahead) and records which weekday it landed on."""
    sub = d[["dow", "day_high", "day_low"]].dropna().copy()
    sub["_week"] = sub.index.to_period("W-SUN")
    wk_hi = sub.groupby("_week")["day_high"].transform("max")
    wk_lo = sub.groupby("_week")["day_low"].transform("min")
    sub["_is_week_high"] = sub["day_high"] >= wk_hi
    sub["_is_week_low"] = sub["day_low"] <= wk_lo

    n_weeks = sub["_week"].nunique()
    rows = []
    for dow, grp in sub.groupby("dow"):
        if dow not in range(5):
            continue
        rows.append({"weekday": _WEEKDAY_NAMES[int(dow)], "dow": int(dow),
                      "n_weeks": n_weeks, "low_n": n_weeks < LOW_N,
                      "pct_sets_week_high": grp["_is_week_high"].mean(),
                      "pct_sets_week_low": grp["_is_week_low"].mean()})
    return pd.DataFrame(rows).sort_values("dow").reset_index(drop=True)


def monthly_profile(d: pd.DataFrame) -> pd.DataFrame:
    """Per calendar month (Jan-Dec, pooled across every year in the data): typical day range
    and the fraction of days labelled 'quiet'/'chop' by the day-type column nylab.sessions
    already computes (`day_type`), as a rough consolidation-vs-active read."""
    sub = d[["day_range", "day_type"]].copy()
    sub["_month"] = d.index.month
    rows = []
    for m, grp in sub.groupby("_month"):
        n = int(grp["day_range"].notna().sum())
        quiet_pct = grp["day_type"].isin(["range_day", "normal_day"]).mean() if "day_type" in grp else np.nan
        rows.append({"month": _MONTH_NAMES[int(m) - 1], "month_num": int(m), "n": n, "low_n": n < LOW_N,
                      "median_range_pips": grp["day_range"].median(),
                      "pct_range_or_normal_day": quiet_pct})
    return pd.DataFrame(rows).sort_values("month_num").reset_index(drop=True)


def quarterly_profile(d: pd.DataFrame) -> pd.DataFrame:
    """Same idea as monthly_profile, pooled by quarter instead."""
    sub = d[["day_range", "day_type"]].copy()
    sub["_q"] = d.index.quarter
    rows = []
    for q, grp in sub.groupby("_q"):
        n = int(grp["day_range"].notna().sum())
        quiet_pct = grp["day_type"].isin(["range_day", "normal_day"]).mean() if "day_type" in grp else np.nan
        rows.append({"quarter": _QUARTER_NAMES[int(q)], "quarter_num": int(q), "n": n, "low_n": n < LOW_N,
                      "median_range_pips": grp["day_range"].median(),
                      "pct_range_or_normal_day": quiet_pct})
    return pd.DataFrame(rows).sort_values("quarter_num").reset_index(drop=True)
