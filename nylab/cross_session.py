"""nylab.cross_session -- ROADMAP 5.3, SESSIONS_AND_CONTEXT.md S5.1: the DESCRIPTIVE
cross-session layer. Everything in this module is deliberately NOT significance-tested --
S5.1 is explicit that looking at a matrix is free, and it's only once a cell gets PROMOTED
(picked because it looked extreme) that S5.2's matrix-family multiple-testing rule applies
(ROADMAP 5.4, not yet built). Every function here returns a `DESCRIPTIVE_BANNER`-tagged
result; nylab.report.html (ROADMAP 5.5) is what will render these with the banner visible.

Operates on the SESSION tables nylab.sessions.build_all_sessions() returns (the dict keyed by
session id), NOT the wide day-table -- so none of this module needs to know about the
`nyam`/`nyam_full` naming-collision rename (see nylab/sessions.py's docstring): a table is
always the session's OWN table, `character`/`dir`/`high`/`low` mean exactly what that session
computed, full stop.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab.days import first_cross
from nylab.stats import wilson_ci

DESCRIPTIVE_BANNER = "DESCRIPTIVE -- not tested for significance (S5.1). Promote a cell to a hypothesis (S5.2) before treating it as a finding."

MIN_N = 25  # SESSIONS_AND_CONTEXT S5.1: grey out cells with fewer than this many days

# S1's default pairs (S5.1) for the character/dir transition matrices.
DEFAULT_PAIRS = [("asia", "lon"), ("lon", "nyam"), ("nyam", "nypm"), ("lon", "nypm")]
SB_IDS = ("lon_sb", "nyam_sb", "nypm_sb")


def combined_label(*series: pd.Series) -> pd.Series:
    """Joins categorical Series into one 'a|b|...' label per row (NaN in ANY input -> NaN
    overall) -- S5.1's example "(asia+lon combined label) -> nyam" default pair."""
    aligned = pd.concat(series, axis=1)
    out = aligned.iloc[:, 0].astype(object)
    any_na = aligned.isna().any(axis=1)
    joined = aligned.astype(str).agg("|".join, axis=1)
    out = joined.where(~any_na, np.nan)
    out.name = "|".join(s.name or "x" for s in series)
    return out


def character_transition_matrix(a: pd.Series, b: pd.Series, min_n: int = MIN_N) -> pd.DataFrame:
    """P(b_label | a_label) -- long-form rows (a_label, b_label, n, k, cond_pct, uncond_pct,
    ci_lo, ci_hi, greyed). `n`/greying is per A-ROW (S5.1: "cells with n < 25" -- too few days
    ever saw that A condition, so its WHOLE row of conditional percentages is unreliable, not
    just one cell of it). Works for `character` OR `dir` OR any other categorical pair, and for
    a `combined_label()` result -- it's purely generic over whatever labels show up."""
    df = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(df) == 0:
        return pd.DataFrame(columns=["a_label", "b_label", "n", "k", "cond_pct", "uncond_pct",
                                      "ci_lo", "ci_hi", "greyed"])
    uncond = df["b"].value_counts(normalize=True)
    a_labels = sorted(df["a"].unique())
    b_labels = sorted(df["b"].unique())
    rows = []
    for al in a_labels:
        sub = df[df["a"] == al]
        n_a = len(sub)
        for bl in b_labels:
            k = int((sub["b"] == bl).sum())
            lo, hi = wilson_ci(k, n_a)
            rows.append(dict(a_label=al, b_label=bl, n=n_a, k=k,
                              cond_pct=(k / n_a if n_a else np.nan),
                              uncond_pct=float(uncond.get(bl, 0.0)),
                              ci_lo=lo, ci_hi=hi, greyed=n_a < min_n))
    return pd.DataFrame(rows)


def takes_rate(bars: pd.DataFrame, a_high: pd.Series, a_low: pd.Series,
               b_lo: float, b_hi: float, min_n: int = MIN_N) -> dict:
    """"B takes A's high / A's low" (S5.1) -- does session B's window [b_lo, b_hi) trade beyond
    A's own high/low. `a_high`/`a_low` are A's per-td raw levels (e.g. tables['lon']['high']).
    Reuses nylab.days.first_cross -- the exact same conservative "any trade-through" rule the
    DAY table's own `ny_takes_lon_high`-style columns already use, just generalized to any B
    window/A level pair instead of the handful ROADMAP Phase 1/2 hardcoded."""
    n = int(a_high.notna().sum())
    t_hi = first_cross(bars, b_lo, b_hi, a_high, above=True)
    t_lo = first_cross(bars, b_lo, b_hi, a_low, above=False)
    took_high = a_high.index.isin(t_hi.index)
    took_low = a_low.index.isin(t_lo.index)
    k_hi, k_lo, k_both = int(took_high.sum()), int(took_low.sum()), int((took_high & took_low).sum())
    return dict(
        n=n, greyed=n < min_n,
        takes_high_rate=k_hi / n if n else np.nan, takes_high_ci=wilson_ci(k_hi, n),
        takes_low_rate=k_lo / n if n else np.nan, takes_low_ci=wilson_ci(k_lo, n),
        takes_both_rate=k_both / n if n else np.nan,
    )


def run_default_takes(bars: pd.DataFrame, sessions_cfg: dict, tables: dict) -> dict[str, dict]:
    """takes_rate() for every S5.1 DEFAULT_PAIRS entry, keyed 'A_to_B'."""
    out = {}
    for a_sid, b_sid in DEFAULT_PAIRS:
        b_lo, b_hi = sessions_cfg[b_sid]
        out[f"{a_sid}_to_{b_sid}"] = takes_rate(bars, tables[a_sid]["high"], tables[a_sid]["low"], b_lo, b_hi)
    return out


def run_default_character_matrices(tables: dict, min_n: int = MIN_N) -> dict[str, pd.DataFrame]:
    """character_transition_matrix() for every S5.1 DEFAULT_PAIRS entry, plus the combined
    (asia+lon) -> nyam pair, keyed 'A_to_B_character' / 'asia_lon_to_nyam_character'."""
    out = {}
    for a_sid, b_sid in DEFAULT_PAIRS:
        out[f"{a_sid}_to_{b_sid}_character"] = character_transition_matrix(
            tables[a_sid]["character"], tables[b_sid]["character"], min_n)
    combined = combined_label(tables["asia"]["character"].rename("asia"), tables["lon"]["character"].rename("lon"))
    out["asia_lon_to_nyam_character"] = character_transition_matrix(combined, tables["nyam"]["character"], min_n)
    return out


def run_default_dir_matrices(tables: dict, min_n: int = MIN_N) -> dict[str, pd.DataFrame]:
    """Same as run_default_character_matrices() but for `dir` (-1/0/1)."""
    return {f"{a_sid}_to_{b_sid}_dir": character_transition_matrix(tables[a_sid]["dir"], tables[b_sid]["dir"], min_n)
            for a_sid, b_sid in DEFAULT_PAIRS}


def news_conditioned_rate(a_news_usd: pd.Series, a_news_eur: pd.Series, outcome: pd.Series,
                           min_n: int = MIN_N) -> pd.DataFrame:
    """S5.1: "conditioning on news: rows = A had high-impact news (none / USD / EUR / both)".
    `outcome` is any boolean Series aligned by td (e.g. B's character == 'reversal')."""
    df = pd.DataFrame({"usd": a_news_usd > 0, "eur": a_news_eur > 0, "out": outcome}).dropna()
    bucket = np.select(
        [df["usd"] & df["eur"], df["usd"] & ~df["eur"], ~df["usd"] & df["eur"]],
        ["both", "USD", "EUR"], default="none",
    )
    df = df.assign(bucket=bucket)
    rows = []
    for b in ("none", "USD", "EUR", "both"):
        sub = df[df["bucket"] == b]
        n = len(sub)
        k = int(sub["out"].sum())
        lo, hi = wilson_ci(k, n)
        rows.append(dict(bucket=b, n=n, k=k, rate=(k / n if n else np.nan), ci_lo=lo, ci_hi=hi, greyed=n < min_n))
    return pd.DataFrame(rows)


def news_severity_rate(a_news_count: pd.Series, a_surprise_z: pd.Series, outcome: pd.Series,
                        z_thresh: float = 1.0, min_n: int = MIN_N) -> pd.DataFrame:
    """S5.1 example: "London had red EUR news with |z| > 1 -> NY AM reversal rate". Rows:
    no_event / event_low_z (|z| <= z_thresh or NaN) / event_high_z (|z| > z_thresh)."""
    df = pd.DataFrame({"cnt": a_news_count, "z": a_surprise_z, "out": outcome}).dropna(subset=["cnt", "out"])
    has_event = df["cnt"] > 0
    high_z = has_event & (df["z"].abs() > z_thresh)
    bucket = np.select([~has_event, has_event & ~high_z, high_z],
                        ["no_event", "event_low_z", "event_high_z"], default="no_event")
    df = df.assign(bucket=bucket)
    rows = []
    for b in ("no_event", "event_low_z", "event_high_z"):
        sub = df[df["bucket"] == b]
        n = len(sub)
        k = int(sub["out"].sum())
        lo, hi = wilson_ci(k, n)
        rows.append(dict(bucket=b, n=n, k=k, rate=(k / n if n else np.nan), ci_lo=lo, ci_hi=hi, greyed=n < min_n))
    return pd.DataFrame(rows)


def continuation_rate(a_dir: pd.Series, b_dir: pd.Series, a_condition: pd.Series | None = None,
                       min_n: int = MIN_N) -> dict:
    """S5.1 example: "NY AM trend -> NY PM continues (same dir) vs reverses". `a_condition`
    (optional bool Series, e.g. tables['nyam']['character'] == 'trend') restricts to the days
    that matter for the question; omit it to get the unconditional continuation rate."""
    df = pd.DataFrame({"a": a_dir, "b": b_dir}).dropna()
    df = df[df["a"] != 0]  # "continues vs reverses" is meaningless when A itself was flat
    if a_condition is not None:
        df = df[a_condition.reindex(df.index).fillna(False)]
    n = len(df)
    k_cont = int((df["a"] == df["b"]).sum())
    k_rev = int((df["a"] == -df["b"]).sum())
    lo, hi = wilson_ci(k_cont, n)
    return dict(n=n, greyed=n < min_n, continues_rate=(k_cont / n if n else np.nan),
                reverses_rate=(k_rev / n if n else np.nan), continues_ci=(lo, hi))


def directional_take_rate(a_condition: pd.Series, a_dir: pd.Series,
                           b_took_high: pd.Series, b_took_low: pd.Series, min_n: int = MIN_N) -> dict:
    """S5.1 example: "Asia quiet + London trend -> NY AM takes London's extreme in the SAME
    direction?". `a_condition` restricts the days (e.g. asia.character=='quiet' & lon.character
    =='trend'); `a_dir` is the directional session's own dir (e.g. lon.dir); `b_took_high`/
    `b_took_low` are the later session's raid flags (e.g. tables['nyam']['took_prev_high']).
    A day where a_dir == 0 (flat) has no "same direction" to test and is excluded."""
    df = pd.DataFrame({"cond": a_condition, "dir": a_dir, "hi": b_took_high, "lo": b_took_low}).dropna()
    df = df[df["cond"] & (df["dir"] != 0)]
    n = len(df)
    same_dir_take = ((df["dir"] > 0) & df["hi"]) | ((df["dir"] < 0) & df["lo"])
    k = int(same_dir_take.sum())
    lo, hi = wilson_ci(k, n)
    return dict(n=n, greyed=n < min_n, rate=(k / n if n else np.nan), ci=(lo, hi))


def silver_bullet_stats(tables: dict, sb_ids=SB_IDS) -> pd.DataFrame:
    """S5.1/S6 item 5: for each Silver Bullet window, how often an FVG forms inside it, how
    often it's a `reversal`-character session (the closest available proxy in this module for
    "reaches the nearest opposite liquidity within the window" -- see docs/PROGRESS.md), and
    its median range -- context for the SB models, not a claim of significance."""
    rows = []
    for sid in sb_ids:
        t = tables[sid]
        n = len(t)
        fvg = (t["fvg_count_bull"] + t["fvg_count_bear"]) > 0
        rows.append(dict(
            session_id=sid, n=n,
            fvg_rate=float(fvg.mean()) if n else np.nan,
            reversal_rate=float((t["character"] == "reversal").mean()) if n else np.nan,
            median_range_pips=float(t["range_pips"].median()) if n else np.nan,
        ))
    return pd.DataFrame(rows)
