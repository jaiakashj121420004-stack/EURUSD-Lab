"""nylab.stats -- proportion tests, Wilson CIs, R-multiple stats (RESEARCH_PROTOCOL.md S2).

Ported verbatim from ny_session_lab.py (functions ztest/ci/r_stats) -- same formulas, same
numbers, just moved out of the monolith so other modules can reuse them.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def ztest(k: int, n: int, p0: float):
    """One-proportion z-test of k/n against a LITERAL fixed rate p0 (e.g. H015's 50% coin-flip
    null). Left completely unchanged -- nylab.hypotheses (frozen v0) calls this verbatim, and
    ROADMAP 5.7.3's two-proportion condition-vs-complement test (two_proportion_ztest below) is
    a NEW, separate function precisely so this one's behavior never has to move. nylab.hyp_engine
    still uses this too, but now only for a hypothesis with an explicit `baseline_p0` (a
    deliberately literal theoretical null, not an empirical one) -- see its own docstring."""
    if n == 0 or p0 in (0, 1):
        return np.nan, np.nan
    p = k / n
    z = (p - p0) / math.sqrt(p0 * (1 - p0) / n)
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def two_proportion_ztest(k1: int, n1: int, k2: int, n2: int):
    """ROADMAP 5.7.3: condition vs its own COMPLEMENT (RESEARCH_PROTOCOL.md S2, 2026-09-26
    clarification) -- "test condition vs COMPLEMENT with a two-proportion z-test (not vs an
    all-days baseline that includes the condition days)". group 1 = days where the condition is
    TRUE (k1 outcomes out of n1), group 2 = the complement, days where it's FALSE (k2 out of n2).
    Pooled-proportion two-sample z-test (the standard test for "does this subgroup's rate differ
    from everyone else's"), NOT nylab.hypotheses'/ztest()'s one-proportion test against an
    external fixed p0 -- that test stays reserved for a hypothesis with an explicit, deliberately
    literal `baseline_p0` (H015's 50% coin-flip, not an empirically-measured rate)."""
    if n1 == 0 or n2 == 0:
        return np.nan, np.nan
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    if p_pool in (0, 1):
        return np.nan, np.nan
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return np.nan, np.nan
    z = (p1 - p2) / se
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def wilson_ci(k: int, n: int, z: float = 1.96):
    """The TRUE Wilson score interval (ROADMAP 5.7.3 -- this function was previously a Wald
    interval, p +/- z*sqrt(p(1-p)/n), mislabeled as Wilson; that formula under-covers for small n
    or p near 0/1, which is exactly where a hypothesis's IS-only condition-true count tends to
    sit. No caller anywhere in the codebase pinned the OLD formula's exact numbers in a golden
    test (checked 2026-09-27: the v0 golden hypotheses.csv has ci_lo/ci_hi columns, but
    tests/test_nylab_phase1.py's parity check deliberately does not compare them -- see that
    test's own column list), so this is a pure bugfix, not a behavior version bump."""
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo, hi = (center - margin) / denom, (center + margin) / denom
    return (max(0.0, lo), min(1.0, hi))


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
