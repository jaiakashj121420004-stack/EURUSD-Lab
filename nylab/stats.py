"""nylab.stats -- proportion tests, Wilson CIs, R-multiple stats (RESEARCH_PROTOCOL.md S2).

Ported verbatim from ny_session_lab.py (functions ztest/ci/r_stats) -- same formulas, same
numbers, just moved out of the monolith so other modules can reuse them.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def ztest(k: int, n: int, p0: float):
    if n == 0 or p0 in (0, 1):
        return np.nan, np.nan
    p = k / n
    z = (p - p0) / math.sqrt(p0 * (1 - p0) / n)
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def wilson_ci(k: int, n: int):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    h = 1.96 * math.sqrt(p * (1 - p) / n)
    return (max(0, p - h), min(1, p + h))


def r_stats(r) -> dict:
    r = pd.Series(r).dropna()
    n = len(r)
    if n == 0:
        return dict(n=0)
    wins, losses = r[r > 0], r[r <= 0]
    sd = r.std(ddof=1) if n > 1 else np.nan
    eq = r.cumsum()
    dd = (eq.cummax() - eq).max()
    streak = best = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    se = sd / math.sqrt(n) if n > 1 else np.nan
    return dict(
        n=n, win_rate=len(wins) / n, expectancy=r.mean(),
        ci_lo=r.mean() - 1.96 * se, ci_hi=r.mean() + 1.96 * se,
        t=r.mean() / se if se else np.nan,
        profit_factor=wins.sum() / abs(losses.sum()) if losses.sum() != 0 else np.inf,
        sqn=math.sqrt(min(n, 100)) * r.mean() / sd if sd else np.nan,
        total_R=r.sum(), max_dd_R=dd, longest_losing_streak=best,
    )
