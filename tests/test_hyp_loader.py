"""nylab.hyp_loader -- YAML loading + look-ahead rejection (RESEARCH_PROTOCOL.md S3, ROADMAP 3.3).
"""
import textwrap

import pytest

from nylab.hyp_loader import HypothesisLoadError, load_all, load_one


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_load_all_loads_the_15_ported_hypotheses_plus_H016():
    """H001-H015 are v0's ported hypotheses; H016 (ROADMAP 5.4) is the first NEW one, a
    cross-session matrix-family promotion (nylab.cross_session) -- see its own YAML notes."""
    hyps = load_all("config/hypotheses")
    assert len(hyps) == 16
    assert {h.id for h in hyps} == {f"H{i:03d}" for i in range(1, 17)}
    assert all(h.version for h in hyps)
    h016 = next(h for h in hyps if h.id == "H016")
    assert h016.matrix_shape == (6, 6)


def test_matrix_shape_must_be_two_positive_ints(tmp_path):
    path = _write(tmp_path, "bad_matrix.yaml", """
        id: HBADMATRIX
        version: "1.0"
        title: "bad matrix_shape"
        decision_time_h: 5.0
        condition: "lon_character == 'chop'"
        outcome: "ny_drive > 0"
        baseline: "ny_drive > 0"
        matrix_shape: [6, 0]
    """)
    with pytest.raises(HypothesisLoadError, match="matrix_shape"):
        load_one(path)


def test_matrix_shape_accepted_and_stored_as_tuple(tmp_path):
    path = _write(tmp_path, "good_matrix.yaml", """
        id: HGOODMATRIX
        version: "1.0"
        title: "good matrix_shape"
        decision_time_h: 5.0
        condition: "lon_character == 'chop'"
        outcome: "ny_drive > 0"
        baseline: "ny_drive > 0"
        matrix_shape: [6, 6]
    """)
    h = load_one(path)
    assert h.matrix_shape == (6, 6)


def test_ordinary_hypothesis_has_no_matrix_shape(tmp_path):
    path = _write(tmp_path, "ordinary.yaml", """
        id: HORDINARY
        version: "1.0"
        title: "no matrix"
        decision_time_h: 5.0
        condition: "lon_dir > 0"
        outcome: "ny_drive > 0"
        baseline: "ny_drive > 0"
    """)
    h = load_one(path)
    assert h.matrix_shape is None


def test_condition_using_a_too_late_column_is_rejected(tmp_path):
    """ny_close is only available at h=16 -- a condition using it with decision_time_h=9.5
    must be refused at LOAD time, before it can ever produce a number."""
    path = _write(tmp_path, "bad.yaml", """
        id: HBAD
        version: "1.0"
        title: "leaks the future"
        decision_time_h: 9.5
        condition: "ny_close > lon_high"
        outcome: "ny_drive > 0"
        baseline: "ny_drive > 0"
    """)
    with pytest.raises(HypothesisLoadError, match="ny_close"):
        load_one(path)


def test_condition_using_an_available_column_is_accepted(tmp_path):
    path = _write(tmp_path, "ok.yaml", """
        id: HOK
        version: "1.0"
        title: "fine"
        decision_time_h: 9.5
        condition: "pre_takes_lon_high"
        outcome: "ny_drive < 0"
        baseline: "ny_drive < 0"
    """)
    hyp = load_one(path)
    assert hyp.id == "HOK"
    assert hyp.decision_time_h == 9.5


def test_dotted_condition_is_also_lookahead_checked(tmp_path):
    """The dotted form (`day.ny_close`) must resolve to the SAME column for the look-ahead
    check as the flat form (`ny_close`) -- otherwise dotted syntax would be a way to sneak a
    too-late column past the loader."""
    path = _write(tmp_path, "bad_dotted.yaml", """
        id: HBADDOT
        version: "1.0"
        title: "leaks the future via dotted syntax"
        decision_time_h: 9.5
        condition: "ny.close > 1.1"
        outcome: "ny_drive > 0"
        baseline: "ny_drive > 0"
    """)
    with pytest.raises(HypothesisLoadError, match="ny_close"):
        load_one(path)


def test_baseline_p0_literal_is_accepted_without_a_baseline_expression(tmp_path):
    path = _write(tmp_path, "h015like.yaml", """
        id: HP0
        version: "1.0"
        title: "literal null rate"
        decision_time_h: 16
        condition: "ny_takes_lon_high"
        outcome: "ny_close < lon_high"
        baseline_p0: 0.5
    """)
    hyp = load_one(path)
    assert hyp.baseline is None
    assert hyp.baseline_p0 == 0.5


def test_missing_baseline_and_baseline_p0_is_rejected(tmp_path):
    path = _write(tmp_path, "noBaseline.yaml", """
        id: HNB
        version: "1.0"
        title: "no baseline at all"
        decision_time_h: 9.5
        condition: "pre_takes_lon_high"
        outcome: "ny_drive < 0"
    """)
    with pytest.raises(HypothesisLoadError, match="baseline"):
        load_one(path)


def test_unsafe_expression_is_rejected_at_load_time(tmp_path):
    path = _write(tmp_path, "unsafe.yaml", """
        id: HUNSAFE
        version: "1.0"
        title: "tries to escape the DSL"
        decision_time_h: 9.5
        condition: "__import__('os').system('echo hi')"
        outcome: "ny_drive < 0"
        baseline: "ny_drive < 0"
    """)
    with pytest.raises(Exception):
        load_one(path)


def test_load_all_on_empty_directory_raises(tmp_path):
    with pytest.raises(HypothesisLoadError, match="no hypothesis"):
        load_all(str(tmp_path))


def test_condition_calling_full_sample_quantile_is_rejected(tmp_path):
    """ROADMAP 5.7.1: exactly the bug verified in H014 on 2026-09-26 -- a condition's threshold
    must come from prior days only, not the whole (past+future) cached history."""
    path = _write(tmp_path, "bad_quantile.yaml", """
        id: HBADQ
        version: "1.0"
        title: "full-sample threshold in condition"
        decision_time_h: 0
        condition: "asia_range < quantile(asia_range, 0.2)"
        outcome: "ny_range > median(ny_range)"
        baseline: "ny_range > median(ny_range)"
    """)
    with pytest.raises(HypothesisLoadError, match="quantile_prior"):
        load_one(path)


def test_condition_calling_full_sample_median_is_rejected(tmp_path):
    path = _write(tmp_path, "bad_median.yaml", """
        id: HBADM
        version: "1.0"
        title: "full-sample threshold in condition"
        decision_time_h: 9.5
        condition: "adr_used_0930 > median(adr_used_0930)"
        outcome: "ny_drive > 0"
        baseline: "ny_drive > 0"
    """)
    with pytest.raises(HypothesisLoadError, match="median_prior"):
        load_one(path)


def test_condition_calling_quantile_prior_is_accepted(tmp_path):
    path = _write(tmp_path, "good_prior.yaml", """
        id: HGOODPRIOR
        version: "1.0"
        title: "prior-only threshold in condition"
        decision_time_h: 0
        condition: "asia_range < quantile_prior(asia_range, 0.2, 60)"
        outcome: "ny_range > median(ny_range)"
        baseline: "ny_range > median(ny_range)"
    """)
    hyp = load_one(path)
    assert hyp.id == "HGOODPRIOR"


def test_outcome_and_baseline_may_still_use_full_sample_quantile_and_median(tmp_path):
    """The 5.7.1 ban on plain quantile()/median() is on `condition` only -- `outcome`/`baseline`
    describe the measured result against a fixed yardstick, which is not a look-ahead leak.
    Uses decision_time_h=0 here (not 9.5) specifically so this test exercises ONLY the 5.7.1
    prior-only-functions rule, not the separate 5.7.2 outcome-window rule -- ny_range's window
    starts at h=7, which is fine for a decision made at h=0 (see
    test_outcome_window_overlap_is_rejected below for the 5.7.2 case where it isn't)."""
    path = _write(tmp_path, "outcome_full_sample.yaml", """
        id: HOUTFS
        version: "1.0"
        title: "full-sample median is fine in outcome/baseline"
        decision_time_h: 0
        condition: "asia_range > 0"
        outcome: "ny_range > median(ny_range)"
        baseline: "ny_range > median(ny_range)"
    """)
    hyp = load_one(path)
    assert hyp.id == "HOUTFS"


def test_outcome_window_overlap_is_rejected(tmp_path):
    """ROADMAP 5.7.2 -- exactly the bug verified in H013 on 2026-09-26: `ny_range` spans
    07:00-16:00, so for a decision made at 09:30 the outcome's window dips back before the
    decision, baking in the same 07:00-09:30 move a same-window condition might already read."""
    path = _write(tmp_path, "bad_outcome_window.yaml", """
        id: HBADWIN
        version: "1.0"
        title: "outcome window overlaps the decision"
        decision_time_h: 9.5
        condition: "adr_used_0930 > 0.8"
        outcome: "ny_range < median(ny_range)"
        baseline: "ny_range < median(ny_range)"
    """)
    with pytest.raises(HypothesisLoadError, match="ny_range"):
        load_one(path)


def test_outcome_window_starting_at_decision_time_is_accepted(tmp_path):
    """ROADMAP 5.7.2's own fix for the H013 case: r0930_1600 starts exactly at decision_time_h
    (9.5) -- 'at or after decision time' (RESEARCH_PROTOCOL.md S3) is fine, only strictly BEFORE
    is rejected."""
    path = _write(tmp_path, "good_outcome_window.yaml", """
        id: HGOODWIN
        version: "1.0"
        title: "outcome window starts exactly at decision time"
        decision_time_h: 9.5
        condition: "adr_used_0930 > 0.8"
        outcome: "r0930_1600 < median(r0930_1600)"
        baseline: "r0930_1600 < median(r0930_1600)"
    """)
    hyp = load_one(path)
    assert hyp.id == "HGOODWIN"


def test_outcome_referencing_an_already_resolved_column_is_not_flagged(tmp_path):
    """ROADMAP 5.7.2's other half: a column that's fully resolved LONG before decision_time_h
    (lon_high, available_at_h=5) isn't a leak just because SOME of its own window predates the
    decision -- it's not a genuine future measurement at all by the time this decision is made.
    Mirrors the real H015 (decision_time_h=16, outcome 'ny_close < lon_high')."""
    path = _write(tmp_path, "resolved_ref.yaml", """
        id: HRESOLVED
        version: "1.0"
        title: "already-resolved column referenced in outcome"
        decision_time_h: 16
        condition: "ny_takes_lon_high"
        outcome: "ny_close < lon_high"
        baseline_p0: 0.5
    """)
    hyp = load_one(path)
    assert hyp.id == "HRESOLVED"


def test_h013_v1_1_loads_with_the_post_decision_outcome_column():
    """Confirms the actual config/hypotheses/H013.yaml file on disk was fixed to v1.1."""
    hyps = load_all("config/hypotheses")
    h013 = next(h for h in hyps if h.id == "H013")
    assert h013.version == "1.1"
    assert h013.outcome == "r0930_1600 < median(r0930_1600)"


def test_h014_v1_1_loads_with_a_prior_only_condition():
    """H014 was the real hypothesis this bug was found in (2026-09-26) -- confirms the actual
    config/hypotheses/H014.yaml file on disk was fixed to v1.1, not just covered by a synthetic
    test fixture."""
    hyps = load_all("config/hypotheses")
    h014 = next(h for h in hyps if h.id == "H014")
    assert h014.version == "1.1"
    assert h014.condition == "asia_range < quantile_prior(asia_range, 0.2)"
