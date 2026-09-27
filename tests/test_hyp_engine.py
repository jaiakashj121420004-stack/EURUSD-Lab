"""nylab.hyp_engine -- unit-level tests for ROADMAP 5.7.3's engine rewrite (the embargo, the
direction field, and effect-in-pips detection), separate from tests/test_hyp_engine_at.py's
full-pipeline AT-01/AT-02 acceptance tests. Builds a small synthetic day table directly rather
than going through nylab.days.build_days, so each piece can be checked in isolation.
"""
import pandas as pd
import pytest

from nylab import hyp_engine
from nylab.hyp_loader import Hypothesis


def _mkindex(n):
    return pd.bdate_range("2024-01-01", periods=n)


def test_split_masks_excludes_embargo_days_from_both_sides():
    idx = _mkindex(20)
    split_date = idx[10]
    is_mask, oos_mask = hyp_engine._split_masks(idx, split_date)
    # IS boundary is unchanged: strictly before split_date.
    assert list(is_mask[is_mask].index) == list(idx[:10])
    # OOS starts EMBARGO_TD (5) trading days after split_date, not AT split_date.
    assert list(oos_mask[oos_mask].index) == list(idx[15:])
    # The 5 days in between (idx[10:15]) belong to neither mask.
    embargoed = idx[10:15]
    for d in embargoed:
        assert not is_mask[d] and not oos_mask[d]


def test_split_masks_falls_back_when_not_enough_days_for_a_full_embargo():
    idx = _mkindex(12)
    split_date = idx[10]  # only 2 days at/after split -- fewer than EMBARGO_TD (5)
    is_mask, oos_mask = hyp_engine._split_masks(idx, split_date)
    assert list(oos_mask[oos_mask].index) == list(idx[10:])  # falls back to split_date itself


def test_effect_col_detects_a_pip_denominated_outcome_column():
    assert hyp_engine._effect_col("r0930_1600 < median(r0930_1600)") == "r0930_1600"
    assert hyp_engine._effect_col("ny_range > median(ny_range)") == "ny_range"


def test_effect_col_is_none_for_non_pip_outcomes():
    assert hyp_engine._effect_col("ny_drive > 0") is None
    assert hyp_engine._effect_col("ny_close < lon_high") is None
    assert hyp_engine._effect_col("nyam_kz_character == 'reversal'") is None


def _hyp(id_, condition, outcome, baseline=None, baseline_p0=None, decision_time_h=0.0):
    return Hypothesis(
        id=id_, version="1.0", title=id_, decision_time_h=decision_time_h,
        condition=condition, outcome=outcome, baseline=baseline, baseline_p0=baseline_p0,
    )


@pytest.fixture
def toy_days():
    """40 trading days: `flag` is True on even-indexed days (20 of them), `hit` is True whenever
    `flag` is True (a deliberately PERFECT, obvious effect so the two-proportion test's direction
    and significance are unambiguous), and `pip_range` (a PIP_UNIT_COLUMNS name) is bigger on
    flag=True days so effect-in-pips has something real to report."""
    idx = _mkindex(40)
    flag = pd.Series([i % 2 == 0 for i in range(40)], index=idx)
    hit = flag.copy()  # hit rate is 100% when flag, 0% when not -- an obvious, unmissable effect
    pip_range = pd.Series([50.0 if f else 10.0 for f in flag], index=idx)
    return pd.DataFrame({"flag": flag, "hit": hit, "day_range": pip_range})


def test_evaluate_reports_complement_baseline_and_as_claimed_direction(toy_days, tmp_path):
    hyps = [_hyp("HTOY", "flag", "hit", baseline="hit")]
    split_date = toy_days.index[30]  # IS = first 30 rows, well past the embargo needs
    rows, _, _, _ = hyp_engine.evaluate(
        toy_days, hyps, split_date, run_id="toy", ledger_path=str(tmp_path / "ledger.csv"),
    )
    r = rows.iloc[0]
    assert r["is_hit"] == pytest.approx(1.0)      # every IS flag=True day hits
    assert r["baseline"] == pytest.approx(0.0)     # every IS flag=False day (the complement) misses
    assert r["direction"] == "as_claimed"          # is_hit (1.0) >= baseline (0.0)
    assert r["p"] < 0.01                           # an obvious, perfect effect must be significant


def test_evaluate_reports_effect_in_pips_for_a_pip_denominated_outcome(toy_days, tmp_path):
    hyps = [_hyp("HTOY2", "flag", "day_range > median(day_range)", baseline="day_range > median(day_range)")]
    split_date = toy_days.index[30]
    rows, _, _, _ = hyp_engine.evaluate(
        toy_days, hyps, split_date, run_id="toy2", ledger_path=str(tmp_path / "ledger.csv"),
    )
    r = rows.iloc[0]
    assert r["effect_col"] == "day_range"
    assert r["effect_is_cond_pips"] == pytest.approx(50.0)
    assert r["effect_is_complement_pips"] == pytest.approx(10.0)


def test_evaluate_uses_literal_baseline_p0_when_set(toy_days, tmp_path):
    """H015-style hypotheses: baseline_p0 is a deliberately literal theoretical null, not the
    empirical complement rate -- confirms it's still respected as an override."""
    hyps = [_hyp("HTOY3", "flag", "hit", baseline_p0=0.5)]
    split_date = toy_days.index[30]
    rows, _, _, _ = hyp_engine.evaluate(
        toy_days, hyps, split_date, run_id="toy3", ledger_path=str(tmp_path / "ledger.csv"),
    )
    r = rows.iloc[0]
    assert r["baseline"] == 0.5
    assert r["direction"] == "as_claimed"  # is_hit (1.0) >= baseline_p0 (0.5)
