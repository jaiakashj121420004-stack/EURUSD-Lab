"""nylab.stats -- ROADMAP 5.7.3's true Wilson CI and two-proportion z-test (RESEARCH_PROTOCOL.md
S2). ztest()/r_stats() are untouched by 5.7.3 (nylab.hypotheses, frozen v0, still calls ztest()
verbatim) so they aren't re-tested here beyond a basic sanity check.
"""
import math

import numpy as np
import pytest

from nylab.stats import model_verdict, two_proportion_ztest, wilson_ci, ztest


def test_wilson_ci_is_the_true_wilson_score_interval_not_wald():
    """ROADMAP 5.7.3: the old (Wald) formula was p +/- 1.96*sqrt(p(1-p)/n). For k=1, n=10 that
    would give a NEGATIVE lower bound clamped to 0 and a much narrower interval than the true
    Wilson score interval -- the textbook case where Wald badly under-covers."""
    lo, hi = wilson_ci(1, 10)
    # True Wilson score interval for k=1, n=10, z=1.96 is approximately (0.0179, 0.4042).
    assert lo == pytest.approx(0.0179, abs=0.001)
    assert hi == pytest.approx(0.4042, abs=0.001)
    # The old Wald formula would have given lo=0 exactly (clamped) -- confirm Wilson doesn't.
    wald_lo = max(0.0, 0.1 - 1.96 * math.sqrt(0.1 * 0.9 / 10))
    assert lo != pytest.approx(wald_lo, abs=1e-6)


def test_wilson_ci_symmetric_case_matches_known_value():
    lo, hi = wilson_ci(50, 100)
    assert lo == pytest.approx(0.4038, abs=0.001)
    assert hi == pytest.approx(0.5962, abs=0.001)


def test_wilson_ci_zero_n_returns_nan():
    lo, hi = wilson_ci(0, 0)
    assert np.isnan(lo) and np.isnan(hi)


def test_wilson_ci_bounds_stay_within_0_and_1():
    lo, hi = wilson_ci(10, 10)
    assert 0.0 <= lo <= hi <= 1.0


def test_two_proportion_ztest_no_difference_gives_p_near_1():
    z, p = two_proportion_ztest(50, 100, 50, 100)
    assert z == pytest.approx(0.0, abs=1e-9)
    assert p == pytest.approx(1.0, abs=1e-9)


def test_two_proportion_ztest_large_difference_is_significant():
    z, p = two_proportion_ztest(80, 100, 20, 100)
    assert abs(z) > 8  # a huge, obvious gap
    assert p < 1e-10


def test_two_proportion_ztest_zero_n_returns_nan():
    z, p = two_proportion_ztest(5, 0, 5, 10)
    assert np.isnan(z) and np.isnan(p)
    z, p = two_proportion_ztest(5, 10, 5, 0)
    assert np.isnan(z) and np.isnan(p)


def test_two_proportion_ztest_matches_ztest_when_groups_are_symmetric_around_p0():
    """Sanity cross-check: if group 2's rate happens to equal some p0, the two-proportion test's
    z-statistic should be in the same direction (though not numerically identical -- ztest() uses
    p0's own variance, two_proportion_ztest() uses the pooled variance) as the one-proportion test
    of group 1 against that same p0."""
    z_two, _ = two_proportion_ztest(70, 100, 50, 100)
    z_one, _ = ztest(70, 100, 0.5)
    assert (z_two > 0) == (z_one > 0)


def test_model_verdict_negative_needs_both_n_and_a_fully_negative_ci():
    """ROADMAP 5.7.5 / docs/JEV_INTEGRATION.md S6.2: a large, confidently-losing OOS sample must
    not be called "not proven" -- that word is for genuinely inconclusive/small-sample cases."""
    # Large n, CI entirely below zero -> negative (the exact london_sweep_reversal v1.0 case).
    assert model_verdict({"n": 183, "ci_lo": -0.4165, "ci_hi": -0.0371}) == "negative"
    # Large n, but CI straddles zero -> not proven (inconclusive, not confidently negative).
    assert model_verdict({"n": 183, "ci_lo": -0.1, "ci_hi": 0.05}) == "not proven"
    # CI entirely below zero, but n < 100 -> not proven (sample too small to trust the sign).
    assert model_verdict({"n": 40, "ci_lo": -0.4, "ci_hi": -0.05}) == "not proven"
    # No trades at all -> not proven.
    assert model_verdict({"n": 0}) == "not proven"


def test_model_verdict_promising_when_ci_lo_positive():
    assert model_verdict({"n": 50, "ci_lo": 0.02, "ci_hi": 0.3}) == "promising"
    assert model_verdict({"n": 500, "ci_lo": 0.001, "ci_hi": 0.4}) == "promising"


def test_ztest_unchanged_for_frozen_v0_callers():
    """nylab.hypotheses (frozen v0) calls ztest() verbatim -- confirms its literal formula
    (p-p0)/sqrt(p0(1-p0)/n) is untouched by the 5.7.3 rewrite."""
    z, p = ztest(60, 100, 0.5)
    expected_z = (0.6 - 0.5) / math.sqrt(0.5 * 0.5 / 100)
    assert z == pytest.approx(expected_z)
