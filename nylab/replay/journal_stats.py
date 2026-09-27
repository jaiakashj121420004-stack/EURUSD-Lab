"""nylab.replay.journal_stats -- ROADMAP 6.7: aggregate stats over the replay trainer's own
trade journal (research/replay/trades.csv), using the SAME nylab.stats module the coded
backtests use (REPLAY_TRAINER.md S8: "same stats module as the backtests, so manual and coded
results are directly comparable") rather than a second, JS-side reimplementation of expectancy/
win-rate math.
"""
from __future__ import annotations

import pandas as pd

from nylab import stats as stats_mod


def _group_stats(df: pd.DataFrame, group_col: str) -> list[dict]:
    out = []
    if group_col not in df.columns:
        return out
    # csv round-trip means "no tag" arrives as an empty string, not NaN -- .fillna() alone
    # misses that and would otherwise group blank-tag trades under a blank "" label instead of
    # folding them into "(none)" with the genuinely-missing rows.
    grouping_col = df[group_col].fillna("(none)").replace("", "(none)")
    for key, g in df.groupby(grouping_col):
        s = stats_mod.r_stats(g["R_net"])
        out.append(dict(group=str(key), n=s.get("n", 0),
                         win_rate=s.get("win_rate"), expectancy=s.get("expectancy"),
                         profit_factor=s.get("profit_factor")))
    return sorted(out, key=lambda r: -r["n"])


def build(df: pd.DataFrame) -> dict:
    """`df` is the parsed trades.csv (JOURNAL_COLUMNS). Numeric coercion is done here rather
    than assuming the CSV round-trip kept types -- csv.DictWriter/reader is all strings."""
    if len(df) == 0:
        return dict(overall=stats_mod.r_stats(pd.Series(dtype=float)), by_setup_tag=[],
                     by_weekday=[], by_preset=[], n_trades=0)
    df = df.copy()
    df["R_net"] = pd.to_numeric(df["R_net"], errors="coerce")
    df = df.dropna(subset=["R_net"])
    if "td" in df.columns:
        df["weekday"] = pd.to_datetime(df["td"], errors="coerce").dt.day_name()
    overall = stats_mod.r_stats(df["R_net"])
    return dict(
        overall=overall,
        by_setup_tag=_group_stats(df, "setup_tag"),
        by_weekday=_group_stats(df, "weekday"),
        by_preset=_group_stats(df, "preset"),
        n_trades=len(df),
    )
