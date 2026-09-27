"""AT-05 (docs/ROADMAP.md 5.7.6): the artifact-catching fixtures -- the mistake-proofing
tests, run through the real pipeline, that prove the 5.7.1/5.7.2 loader rules actually catch
the two specific artifacts that motivated them, not just that they reject a narrow synthetic
YAML snippet in isolation.

AT-05 has two parts:

1. A synthetic 5-year series with two volatility eras and NO real day-to-day edge (
   tests/fixtures/make_synth.py's `twoera` variant, ROADMAP 5.7.6) -- a full-sample-threshold
   hypothesis referencing it must be REJECTED by the loader (already proven, data-independently,
   by tests/test_hyp_loader.py::test_condition_calling_full_sample_quantile_is_rejected -- that
   rejection is purely syntactic, so it holds for ANY data, this fixture included). The NEW
   check this file adds: the same condition's prior-only twin, actually EVALUATED against this
   adversarial two-era data, must come out `noise` -- proving quantile_prior() genuinely fixes
   the H014-style artifact (RESEARCH_PROTOCOL.md S3: "selecting calm years, not calm days"),
   not just that it passes a load-time syntax check.

2. A fixture where the outcome window overlaps the condition -- already covered by
   tests/test_hyp_loader.py::test_outcome_window_overlap_is_rejected (the H013-style artifact,
   ROADMAP 5.7.2). Re-asserted here under the AT-05 name for ROADMAP/acceptance-test
   traceability, rather than duplicating the fixture.
"""
from pathlib import Path

import pandas as pd
import pytest

from nylab import config as cfg
from nylab import days as days_mod
from nylab import hyp_engine
from nylab.data import loader, timezones
from nylab.hyp_loader import HypothesisLoadError, load_one

ROOT = Path(__file__).parent.parent


def _write(tmp_path, name, text):
    import textwrap
    p = tmp_path / name
    p.write_text(textwrap.dedent(text))
    return str(p)


def _build_twoera_days() -> pd.DataFrame:
    """Same minimal day-table build as test_hyp_engine_at.py's _build_days, but session-table
    attach is skipped here -- this test only needs the legacy DAY columns (asia_range, ny_range)
    the twoera hypothesis's condition/outcome reference, not the session-character columns."""
    raw = loader.load_bars(str(ROOT / "tests" / "fixtures" / "EURUSD_M5_synth_twoera_5y.csv"))
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    return days_mod.build_days(raw, cfg.legacy_windows())


def test_at05_full_sample_threshold_on_twoera_data_is_rejected_by_loader(tmp_path):
    """The rejection is purely syntactic (it fires on the DSL function name in `condition`, not
    on any property of the data), so this is really the same check as
    test_hyp_loader.py::test_condition_calling_full_sample_quantile_is_rejected -- restated here,
    against the actual twoera fixture path, as AT-05's own record that the check applies to
    exactly the adversarial case it was built for."""
    path = _write(tmp_path, "twoera_full_sample.yaml", """
        id: HAT05FULL
        version: "1.0"
        title: "full-sample threshold -- must be rejected regardless of data"
        decision_time_h: 0
        condition: "asia_range < quantile(asia_range, 0.2)"
        outcome: "ny_range > median(ny_range)"
        baseline: "ny_range > median(ny_range)"
    """)
    with pytest.raises(HypothesisLoadError, match="quantile_prior"):
        load_one(path)


def test_at05_prior_only_twin_is_noise_on_the_twoera_regime_shift(tmp_path):
    """The substantive AT-05 check: on data engineered to fool a full-sample threshold (see this
    module's docstring -- flagging asia_range's global bottom 20% flags 100% era-1 days, and
    those days' ny_range hit rate vs. the global median differs by ~57pp, a huge but entirely
    artifactual "effect"), the prior-only twin must come out genuinely `noise` when actually run
    through the pipeline."""
    path = _write(tmp_path, "twoera_prior_only.yaml", """
        id: HAT05PRIOR
        version: "1.0"
        title: "prior-only threshold -- must be immune to a volatility regime shift"
        decision_time_h: 0
        condition: "asia_range < quantile_prior(asia_range, 0.2, 60)"
        outcome: "ny_range > median(ny_range)"
        baseline: "ny_range > median(ny_range)"
    """)
    hyp = load_one(path)
    d = _build_twoera_days()
    split_date = d.index[int(len(d) * 0.7)]
    rows, _, _, _ = hyp_engine.evaluate(
        d, [hyp], split_date, run_id="at05", ledger_path=str(tmp_path / "ledger.csv"),
    )
    r = rows.iloc[0]
    assert r["verdict"] == "noise", (
        f"AT-05 FAILED: prior-only threshold reported {r['verdict']!r} (p={r['p']:.4g}) on a "
        f"fixture with NO real edge, only a volatility regime shift -- quantile_prior() should "
        f"be immune to this, not just syntactically distinct from quantile()."
    )


def test_at05_outcome_window_overlap_is_rejected_by_loader(tmp_path):
    """The second half of AT-05 (ROADMAP 5.7.6): a fixture where the outcome window overlaps the
    condition must be rejected by the loader. Same fixture/assertion as
    test_hyp_loader.py::test_outcome_window_overlap_is_rejected (the H013-style artifact,
    ROADMAP 5.7.2) -- restated here under the AT-05 name so the ROADMAP's acceptance-test list
    (AT-01..AT-05) has one place per test, matching test_hyp_engine_at.py's AT-01/AT-02 pattern."""
    path = _write(tmp_path, "overlap.yaml", """
        id: HAT05OVERLAP
        version: "1.0"
        title: "outcome window overlaps the decision -- must be rejected"
        decision_time_h: 9.5
        condition: "adr_used_0930 > 0.8"
        outcome: "ny_range < median(ny_range)"
        baseline: "ny_range < median(ny_range)"
    """)
    with pytest.raises(HypothesisLoadError, match="ny_range"):
        load_one(path)
