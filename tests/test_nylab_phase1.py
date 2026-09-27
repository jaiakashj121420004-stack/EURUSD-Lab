"""Phase 1 acceptance: nylab's `run` must reproduce v0's golden numbers exactly (ROADMAP Phase 1
acceptance: "NY numbers equal v0 golden, tolerance 1e-9"), plus AT-03 (no look-ahead) and a
parquet-cache round trip.
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
GOLDEN = ROOT / "tests" / "golden" / "v0" / "clean_5y_report"
FIXTURE = ROOT / "tests" / "fixtures" / "EURUSD_M5_synth_clean_5y.csv"

sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def nylab_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("nylab_phase1_run")
    subprocess.run(
        [sys.executable, "-m", "nylab", "run", str(FIXTURE), "--tz", "ny+7",
         "--out", str(out), "--run-id", "phase1_test", "--no-cache",
         "--ledger-path", str(out / "ledger.csv")],  # isolated -- never touch the repo's real ledger
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return out


def _numeric_cols_match(gold: pd.DataFrame, new: pd.DataFrame, tol=1e-9):
    mismatches = []
    for col in gold.columns:
        g, n = gold[col], new[col]
        if g.dtype == bool or n.dtype == bool or g.dtype == object or n.dtype == object:
            if not (g.astype(str) == n.astype(str)).all():
                mismatches.append(col)
        else:
            g2, n2 = g.astype(float), n.astype(float)
            diff = (g2 - n2).abs()
            ok = (diff <= tol) | (g2.isna() & n2.isna())
            if not ok.all():
                mismatches.append(col)
    return mismatches


def test_days_csv_matches_golden(nylab_run):
    """v0 parity: every column v0 golden had must still exist with the same numbers. Phase 2
    added pwh/pwl (weekly high/low) -- a genuinely new column v0 never computed -- so this no
    longer requires an exact column-set match, only that nothing v0 had was dropped or changed."""
    gold = pd.read_csv(GOLDEN / "days.csv", index_col=0, parse_dates=True)
    new = pd.read_csv(nylab_run / "days.csv", index_col=0, parse_dates=True)
    assert len(gold) == len(new)
    missing = set(gold.columns) - set(new.columns)
    assert not missing, f"columns present in v0 golden but dropped: {missing}"
    mismatches = _numeric_cols_match(gold, new[list(gold.columns)])
    assert mismatches == [], f"columns diverged from v0 golden: {mismatches}"


def test_trades_csv_matches_golden(nylab_run):
    gold = pd.read_csv(GOLDEN / "trades.csv")
    new = pd.read_csv(nylab_run / "trades.csv")
    assert gold.shape == new.shape
    for col in ("entry", "stop", "target", "exit", "risk_pips", "R_gross", "R_net", "cost_R"):
        assert (gold[col] - new[col]).abs().max() < 1e-9, col
    for col in ("td", "side", "reason", "entry_time_ny"):
        assert (gold[col].astype(str) == new[col].astype(str)).all(), col


def test_hypotheses_csv_matches_golden(nylab_run):
    """v0 parity for the SUBSTANTIVE numbers (Phase 3 replaced v0's hardcoded significance/
    verdict logic with the real YAML+DSL+ledger+Bonferroni/BH engine -- see
    docs/PROGRESS.md's Phase 3 section -- so the columns and verdict methodology are new by
    design; only the underlying per-hypothesis sample counts and hit rates must still match
    v0 exactly, since those come from the SAME 15 conditions evaluated on the SAME data).
    ROADMAP 5.4 added a 16th hypothesis, H016 (a matrix-family promotion, not one v0 ever
    had) -- config/hypotheses/*.yaml loads in sorted glob order, so it sorts AFTER H001-H015
    and doesn't disturb their alignment with the v0 golden file, which only ever had 15 rows.

    ROADMAP 5.7.1 (2026-09-27): H014 is EXPECTED to diverge from the v0 golden numbers now --
    it was bumped to v1.1 with a prior-only `quantile_prior()` condition (v0's plain
    full-sample `quantile()` was found to leak the future, RESEARCH_PROTOCOL.md S3), which by
    design flags a different, smaller set of days than v0's condition did. H014 (row index 13,
    the 14th of the 15 ported hypotheses) is excluded from the strict parity check for that
    reason; every other v0-ported hypothesis (unchanged condition/outcome) must still match
    exactly."""
    gold = pd.read_csv(GOLDEN / "hypotheses.csv")
    new = pd.read_csv(nylab_run / "hypotheses.csv")
    assert len(gold) == 15
    assert len(new) == 16
    assert list(new["id"])[:15] == [f"H{i:03d}" for i in range(1, 16)]
    assert new["id"].iloc[15] == "H016"
    ported = new.iloc[:15]
    h014_row = ported.index[ported["id"] == "H014"][0]
    # ROADMAP 5.7.2 (2026-09-27): H013 is ALSO expected to diverge now -- v1.1 swaps its outcome
    # from `ny_range` to the new post-decision `r0930_1600` column (v0's outcome window started
    # before its own decision_time_h=9.5, RESEARCH_PROTOCOL.md S3). H013's condition is
    # unchanged, so its `n`/`oos_n` (which depend only on condition) still match v0 exactly --
    # only the outcome-dependent columns (hit, baseline, is_hit, oos_hit) actually move; excluded
    # wholesale here anyway for the same reason as H014, rather than tracking that distinction.
    h013_row = ported.index[ported["id"] == "H013"][0]
    for col in ("n", "hit", "baseline", "is_hit", "oos_hit", "oos_n"):
        diff = (gold[col].astype(float) - ported[col].astype(float)).abs()
        ok = (diff <= 1e-9) | (gold[col].isna() & ported[col].isna())
        ok.loc[h014_row] = True  # H014 v1.1's prior-only condition intentionally changes n/hit
        ok.loc[h013_row] = True  # H013 v1.1's post-decision outcome intentionally changes hit
        assert ok.all(), f"{col} diverged from v0 golden at row(s) {list(diff[~ok].index)}"


def test_r0930_1600_matches_a_manual_09_30_16_00_range_and_has_no_lookahead():
    """ROADMAP 5.7.2's new outcome column: verifies its VALUE against a hand-computed range from
    the raw bars (not just that it runs), and that it doesn't need bars past 16:00 (AT-03-style
    truncation check, same pattern as test_window_helper_has_no_lookahead)."""
    from nylab import config as cfg
    from nylab import days as days_mod
    from nylab.data import loader, timezones

    raw = loader.load_bars(str(FIXTURE))
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)

    pip = cfg.legacy_windows()["pip"]
    d = days_mod.build_days(raw, cfg.legacy_windows())
    assert "r0930_1600" in d.columns and "r0930_1600_rel" in d.columns

    sample_td = d.index[len(d) // 2]
    window_bars = raw[(raw.td == sample_td) & (raw.h >= 9.5) & (raw.h < 16)]
    assert len(window_bars) > 0
    manual_range = (window_bars.high.max() - window_bars.low.min()) / pip
    assert d.at[sample_td, "r0930_1600"] == pytest.approx(manual_range, abs=1e-9)

    # AT-03: truncating the bar stream right after 16:00 must not change the value for that day.
    cutoff = raw[(raw.td == sample_td) & (raw.h >= 16)].index.min()
    assert pd.notna(cutoff), "fixture doesn't have bars at/after h=16 on the sampled day"
    truncated = raw.loc[: cutoff - 1]
    d_trunc = days_mod.build_days(truncated, cfg.legacy_windows())
    assert d_trunc.at[sample_td, "r0930_1600"] == pytest.approx(d.at[sample_td, "r0930_1600"], abs=1e-9)


def test_column_starts_at_h_registers_the_new_outcome_column_and_the_h013_trap_column():
    from nylab.days import COLUMN_DOCS, COLUMN_STARTS_AT_H

    # r0930_1600 must start exactly at 9.5 (not before) -- that's the whole point of adding it.
    assert COLUMN_STARTS_AT_H["r0930_1600"] == 9.5
    assert COLUMN_DOCS["r0930_1600"] == 16
    # ny_range is still registered as starting at 7 -- it wasn't changed, just avoided for H013.
    assert COLUMN_STARTS_AT_H["ny_range"] == 7
    # A point-in-time column (never listed in COLUMN_STARTS_AT_H) has no overlap risk at all --
    # confirmed by its ABSENCE, which nylab.hyp_loader's `.get(col, avail)` relies on.
    assert "ny_close" not in COLUMN_STARTS_AT_H
    assert "ny_drive" not in COLUMN_STARTS_AT_H


def test_summary_json_written(nylab_run):
    import json
    summ = json.loads((nylab_run / "summary.json").read_text())
    # ROADMAP 5.4: 15 ordinary hypotheses + H016 (a 6x6=36-cell matrix promotion) = 51.
    assert summ["ledger_total_tests"] == 51
    assert summ["data"]["days"] == 1305
    assert summ["data"]["tz_sanity"] == "ok"
    assert len(summ["hypotheses"]) == 16
    assert summ["models"][0]["name"] == "london_sweep_reversal"


def test_cache_round_trip(tmp_path):
    from nylab import cache as cache_mod
    from nylab import config as cfg
    from nylab import days as days_mod
    from nylab.data import loader, timezones

    raw = loader.load_bars(str(FIXTURE))
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    d = days_mod.build_days(raw, cfg.legacy_windows())

    cache_mod.save(raw, d, cache_dir=str(tmp_path))
    bars2, days2 = cache_mod.load(cache_dir=str(tmp_path))
    assert len(bars2) == len(raw)
    assert len(days2) == len(d)


def test_window_helper_has_no_lookahead():
    """AT-03: a window's value for a day must not depend on bars that arrive after the window
    closes. Truncate the bar stream right after the London KZ closes (h=5) and confirm the
    London window's columns for that day are unchanged."""
    from nylab.data import loader, timezones
    from nylab.days import window as day_window

    raw = loader.load_bars(str(FIXTURE))
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)

    full = day_window(raw, 2, 5, "lon")
    mid_td = full.index[len(full) // 2]

    cutoff = raw[(raw.td == mid_td) & (raw.h >= 5)].index.min()
    assert pd.notna(cutoff), "fixture doesn't have bars at/after h=5 on the sampled day"
    truncated = raw.loc[: cutoff - 1]

    trunc = day_window(truncated, 2, 5, "lon")
    assert mid_td in trunc.index, "the London window disappeared entirely after truncation"
    for col in full.columns:
        a, b = full.at[mid_td, col], trunc.at[mid_td, col]
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == b, f"{col} leaked future data: full={a} truncated={b}"
