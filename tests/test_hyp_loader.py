"""nylab.hyp_loader -- YAML loading + look-ahead rejection (RESEARCH_PROTOCOL.md S3, ROADMAP 3.3).
"""
import textwrap

import pytest

from nylab.hyp_loader import HypothesisLoadError, load_all, load_one


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_load_all_loads_the_15_ported_hypotheses():
    hyps = load_all("config/hypotheses")
    assert len(hyps) == 15
    assert {h.id for h in hyps} == {f"H{i:03d}" for i in range(1, 16)}
    assert all(h.version for h in hyps)


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
