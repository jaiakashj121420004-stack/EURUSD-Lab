"""ROADMAP Phase 5.3 tests: nylab/cross_session.py's descriptive transition matrices,
news-conditioned rates, continuation/directional-take helpers, and Silver Bullet stats. Pure
hand-built Series for the statistics (so the expected counts are known exactly), plus a short
real-pipeline run for takes_rate() (needs actual bars for nylab.days.first_cross)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import cross_session as cs
from nylab import config as cfg
from nylab import days as days_mod
from nylab.data import timezones


def _idx(n):
    return pd.date_range("2024-01-01", periods=n, freq="D")


def test_combined_label_joins_and_propagates_nan():
    a = pd.Series(["quiet", "trend", np.nan, "chop"], index=_idx(4), name="a")
    b = pd.Series(["reversal", "trend", "chop", np.nan], index=_idx(4), name="b")
    out = cs.combined_label(a, b)
    assert out.iloc[0] == "quiet|reversal"
    assert out.iloc[1] == "trend|trend"
    assert pd.isna(out.iloc[2])
    assert pd.isna(out.iloc[3])


def test_character_transition_matrix_counts_and_greying():
    idx = _idx(30)
    a = pd.Series(["x"] * 20 + ["y"] * 10, index=idx)
    b = pd.Series(["p"] * 10 + ["q"] * 10 + ["p"] * 5 + ["q"] * 5, index=idx)
    m = cs.character_transition_matrix(a, b, min_n=25)
    row_x_p = m[(m.a_label == "x") & (m.b_label == "p")].iloc[0]
    assert row_x_p["n"] == 20 and row_x_p["k"] == 10 and row_x_p["cond_pct"] == pytest.approx(0.5)
    assert row_x_p["greyed"]  # n=20 < min_n=25
    row_y_p = m[(m.a_label == "y") & (m.b_label == "p")].iloc[0]
    assert row_y_p["n"] == 10 and row_y_p["greyed"]
    # unconditional P(b=='p') across all 30 rows = 15/30 = 0.5, same for every a_label
    assert m[m.b_label == "p"]["uncond_pct"].tolist() == pytest.approx([0.5, 0.5])


def test_character_transition_matrix_drops_nan_rows():
    idx = _idx(5)
    a = pd.Series(["x", "x", np.nan, "x", "x"], index=idx)
    b = pd.Series(["p", "p", "p", np.nan, "q"], index=idx)
    m = cs.character_transition_matrix(a, b, min_n=1)
    assert m["n"].iloc[0] == 3  # rows 0,1,4 survive (row2: a NaN, row3: b NaN)


def test_character_transition_matrix_empty_input():
    idx = _idx(3)
    a = pd.Series([np.nan] * 3, index=idx)
    b = pd.Series(["p"] * 3, index=idx)
    m = cs.character_transition_matrix(a, b)
    assert len(m) == 0
    assert list(m.columns) == ["a_label", "b_label", "n", "k", "cond_pct", "uncond_pct", "ci_lo", "ci_hi", "greyed"]


def test_news_conditioned_rate_buckets():
    idx = _idx(40)
    usd = pd.Series([1] * 10 + [0] * 30, index=idx)
    eur = pd.Series([0] * 10 + [1] * 10 + [1] * 10 + [0] * 10, index=idx)
    outcome = pd.Series([True] * 20 + [False] * 20, index=idx)
    out = cs.news_conditioned_rate(usd, eur, outcome, min_n=5)
    # rows 0-9: usd=1,eur=0 -> "USD" bucket, all True
    row_usd = out[out.bucket == "USD"].iloc[0]
    assert row_usd["n"] == 10 and row_usd["rate"] == pytest.approx(1.0)
    # rows 10-29: usd=0,eur=1 -> "EUR" bucket (20 rows: 10-19 outcome True, 20-29 outcome False)
    row_eur = out[out.bucket == "EUR"].iloc[0]
    assert row_eur["n"] == 20 and row_eur["rate"] == pytest.approx(0.5)
    # rows 30-39: usd=0,eur=0 -> "none" bucket, outcome False
    assert out[out.bucket == "none"].iloc[0]["n"] == 10
    assert out["n"].sum() == 40


def test_news_severity_rate_high_z_bucket():
    idx = _idx(6)
    cnt = pd.Series([0, 0, 1, 1, 1, 1], index=idx)
    z = pd.Series([np.nan, np.nan, 0.3, 0.5, 1.5, -2.0], index=idx)
    outcome = pd.Series([False, False, False, True, True, True], index=idx)
    out = cs.news_severity_rate(cnt, z, outcome, z_thresh=1.0, min_n=1)
    assert out.set_index("bucket").loc["no_event", "n"] == 2
    assert out.set_index("bucket").loc["event_low_z", "n"] == 2
    assert out.set_index("bucket").loc["event_high_z", "n"] == 2
    assert out.set_index("bucket").loc["event_high_z", "rate"] == pytest.approx(1.0)


def test_continuation_rate_excludes_flat_a_and_applies_condition():
    idx = _idx(6)
    a_dir = pd.Series([1, -1, 0, 1, 1, -1], index=idx)
    b_dir = pd.Series([1, 1, 1, -1, 1, -1], index=idx)
    out = cs.continuation_rate(a_dir, b_dir, min_n=1)
    assert out["n"] == 5  # the a_dir==0 row is dropped
    # rows: (1,1)cont (-1,1)rev (1,-1)rev (1,1)cont (-1,-1)cont -> 3 cont, 2 rev
    assert out["continues_rate"] == pytest.approx(3 / 5)
    assert out["reverses_rate"] == pytest.approx(2 / 5)

    cond = pd.Series([True, True, True, False, False, False], index=idx)
    out2 = cs.continuation_rate(a_dir, b_dir, a_condition=cond, min_n=1)
    assert out2["n"] == 2  # only rows 0,1 survive (row2 a_dir==0 excluded regardless of cond)


def test_directional_take_rate_matches_direction_only():
    idx = _idx(4)
    cond = pd.Series([True, True, True, False], index=idx)
    a_dir = pd.Series([1, -1, 1, 1], index=idx)
    b_took_high = pd.Series([True, False, False, True], index=idx)
    b_took_low = pd.Series([False, True, False, True], index=idx)
    out = cs.directional_take_rate(cond, a_dir, b_took_high, b_took_low, min_n=1)
    # row0: cond & dir=1 -> checks took_high=True -> match. row1: dir=-1 -> checks took_low=True -> match.
    # row2: dir=1 -> took_high=False -> no match. row3: cond False -> excluded.
    assert out["n"] == 3
    assert out["rate"] == pytest.approx(2 / 3)


def test_silver_bullet_stats_shape_and_bounds():
    idx = _idx(50)
    tables = {}
    for sid in cs.SB_IDS:
        tables[sid] = pd.DataFrame({
            "fvg_count_bull": np.random.default_rng(1).integers(0, 2, 50),
            "fvg_count_bear": 0,
            "character": ["reversal"] * 10 + ["chop"] * 40,
            "range_pips": np.linspace(5, 25, 50),
        }, index=idx)
    out = cs.silver_bullet_stats(tables)
    assert list(out["session_id"]) == list(cs.SB_IDS)
    assert (out["fvg_rate"].between(0, 1)).all()
    assert out["reversal_rate"].tolist() == pytest.approx([0.2, 0.2, 0.2])


def _build_day_and_bars(n_days=8, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-02-01 00:00", periods=n_days * 288, freq="5min")
    walk = rng.normal(0, 0.00015, len(idx)).cumsum() + 1.10000
    raw = pd.DataFrame({
        "server": idx,
        "open": walk, "high": walk + rng.uniform(0, 0.00012, len(idx)),
        "low": walk - rng.uniform(0, 0.00012, len(idx)), "close": walk + rng.normal(0, 0.00003, len(idx)),
    })
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    d = days_mod.build_days(raw, cfg.legacy_windows())
    return raw, d


def test_takes_rate_runs_against_real_first_cross_and_returns_sane_shape():
    bars, d = _build_day_and_bars()
    out = cs.takes_rate(bars, d["asia_high"], d["asia_low"], 2.0, 5.0)  # asia -> lon window
    assert out["n"] == len(d)
    for key in ("takes_high_rate", "takes_low_rate", "takes_both_rate"):
        assert np.isnan(out[key]) or 0.0 <= out[key] <= 1.0
