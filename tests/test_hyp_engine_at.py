"""Global acceptance tests AT-01 and AT-02 (docs/ROADMAP.md's "Global acceptance tests"
section), now run through the real Phase 3 pipeline (YAML hypotheses + safe DSL + ledger +
Bonferroni/BH) instead of v0's hardcoded significance check.

AT-01 No false edges: on the clean synthetic fixture, zero hypotheses reach `survives-oos`.
AT-02 Planted edge found: on the planted-edge fixture, the planted hypothesis (H005 --
tests/fixtures/make_synth.py's plant_edge() forces exactly H005's condition to predict a down
day) reaches `survives-oos` with hit >= 0.58.

Both use the 5-year fixtures: AT-01 for consistency with the Phase 0/1 golden baseline (also
5y), AT-02 because the 2-year fixture doesn't give H005 enough samples to clear the strict
Bonferroni bar even though its raw hit rate already clears 0.58 -- see docs/PROGRESS.md's
Phase 3 section for the full writeup of that finding and the "Bonferroni-only for
survives-oos" fix it led to (Akash's call, 2026-09).
"""
from pathlib import Path

import pandas as pd
import pytest

from nylab import config as cfg
from nylab import days as days_mod
from nylab import hyp_engine, hyp_loader
from nylab import sessions as sessions_mod
from nylab.data import loader, timezones

ROOT = Path(__file__).parent.parent


def _build_days(csv_name: str) -> pd.DataFrame:
    """Mirrors nylab.__main__.cmd_run's real pipeline through the Phase 5 session-table attach
    step (no calendar -- these fixtures have none, and none of the ported hypotheses need
    news columns), since `hyp_loader.load_all()` now includes H016 (ROADMAP 5.4), whose
    condition references `lon.character` -- a SESSION-table column, not a legacy DAY one."""
    raw = loader.load_bars(str(ROOT / "tests" / "fixtures" / csv_name))
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    d = days_mod.build_days(raw, cfg.legacy_windows())
    sessions_cfg = cfg.sessions()
    tables = sessions_mod.build_all_sessions(raw, d, None, sessions_cfg, cfg.legacy_windows()["pip"])
    d = sessions_mod.attach_session_features(d, tables)
    return d.join(sessions_mod.build_day_types(d))


@pytest.fixture(scope="module")
def hyps():
    return hyp_loader.load_all()


def test_at01_no_false_edges_on_clean_fixture(hyps, tmp_path):
    d = _build_days("EURUSD_M5_synth_clean_5y.csv")
    split_date = d.index[int(len(d) * 0.7)]
    rows, _, m, alpha = hyp_engine.evaluate(d, hyps, split_date, run_id="at01",
                                             ledger_path=str(tmp_path / "ledger.csv"))
    survives = rows[rows["verdict"] == "survives-oos"]
    assert len(survives) == 0, (
        f"AT-01 FAILED: {list(survives['id'])} reached survives-oos on data with NO real edge:\n"
        f"{survives[['id', 'hypothesis', 'n', 'p', 'oos_hit']].to_string()}"
    )


def test_at02_planted_edge_is_found(hyps, tmp_path):
    d = _build_days("EURUSD_M5_synth_planted_5y.csv")
    split_date = d.index[int(len(d) * 0.7)]
    rows, _, m, alpha = hyp_engine.evaluate(d, hyps, split_date, run_id="at02",
                                             ledger_path=str(tmp_path / "ledger.csv"))
    h005 = rows[rows["id"] == "H005"].iloc[0]
    assert h005["hit"] >= 0.58, f"AT-02 FAILED: H005 hit={h005['hit']:.3f}, want >= 0.58"
    assert h005["verdict"] == "survives-oos", (
        f"AT-02 FAILED: H005 verdict={h005['verdict']!r}, want 'survives-oos' "
        f"(p={h005['p']:.6f}, oos_hit={h005['oos_hit']:.3f}, oos_n={h005['oos_n']})"
    )


def test_at01_and_at02_together_on_same_ledger(hyps, tmp_path):
    """The ledger is shared across runs in real use (ROADMAP 3.4) -- running AT-01 then AT-02
    against the SAME ledger file must not change either result: m only grows by genuinely new
    (id, version) pairs, and since both runs use the identical 16 hypotheses at version 1.0
    (15 ordinary + H016, a 6x6=36-cell matrix promotion, ROADMAP 5.4), m should stay
    15 + 36 = 51 throughout, not 102."""
    ledger_path = str(tmp_path / "shared_ledger.csv")
    d_clean = _build_days("EURUSD_M5_synth_clean_5y.csv")
    split_clean = d_clean.index[int(len(d_clean) * 0.7)]
    _, ledger_rows_1, m1, _ = hyp_engine.evaluate(d_clean, hyps, split_clean, run_id="run1", ledger_path=ledger_path)
    from nylab import ledger as ledger_mod
    ledger_mod.append(ledger_rows_1, path=ledger_path)

    d_planted = _build_days("EURUSD_M5_synth_planted_5y.csv")
    split_planted = d_planted.index[int(len(d_planted) * 0.7)]
    rows2, ledger_rows_2, m2, _ = hyp_engine.evaluate(d_planted, hyps, split_planted, run_id="run2", ledger_path=ledger_path)

    assert m1 == 51
    assert m2 == 51, "re-running the same 16 (id, version) pairs must not inflate m"
    h005 = rows2[rows2["id"] == "H005"].iloc[0]
    assert h005["verdict"] == "survives-oos"
