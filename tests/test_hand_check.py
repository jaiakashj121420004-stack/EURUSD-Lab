"""tests/test_hand_check.py -- HANDOFF.md S4 Step 3: nylab.report.hand_check's sampling
(stratified, deterministic) and HTML rendering (a replay link per row)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab.report import hand_check


def _mk_fvg(n_bull, n_bear, start_bar=100):
    rows = []
    idx = start_bar
    for _ in range(n_bull):
        rows.append(dict(bar_idx=idx, t=pd.Timestamp("2024-01-02 08:00") + pd.Timedelta(minutes=5 * idx),
                          direction="bull", top=1.001, bottom=1.000, ce=1.0005, gap_pips=10.0,
                          is_displacement_leg=True, first_touch_idx=idx + 5, ce_touch_idx=-1,
                          full_fill_idx=-1, invalidated_idx=-1))
        idx += 10
    for _ in range(n_bear):
        rows.append(dict(bar_idx=idx, t=pd.Timestamp("2024-01-02 08:00") + pd.Timedelta(minutes=5 * idx),
                          direction="bear", top=1.002, bottom=1.001, ce=1.0015, gap_pips=10.0,
                          is_displacement_leg=False, first_touch_idx=-1, ce_touch_idx=-1,
                          full_fill_idx=-1, invalidated_idx=-1))
        idx += 10
    return pd.DataFrame(rows)


def _mk_df(n_bars=2000):
    """Minimal bars frame with td/h so sample_fvgs can look up each FVG's own day/hour."""
    ts = pd.date_range("2024-01-02 00:00", periods=n_bars, freq="5min")
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=range(n_bars))
    df["ny"] = ts
    df["td"] = ts.normalize()
    df["h"] = (ts - ts.normalize()).total_seconds() / 3600.0
    return df


def _mk_raids(n_sweep_per_session, n_break=0, sessions=("asia", "lon", "nyam_kz")):
    rows = []
    i = 0
    for sid in sessions:
        for _ in range(n_sweep_per_session):
            rows.append(dict(td=pd.Timestamp("2024-01-02") + pd.Timedelta(days=i), level_name="prev_high",
                              side="above", level_price=1.1, raid_idx=100 + i, t_raid=pd.Timestamp("2024-01-02 08:00"),
                              t_raid_h=8.0 + i * 0.01, raid_type="sweep", close_back_idx=105 + i,
                              t_close_back=pd.Timestamp("2024-01-02 08:30"), bars_to_close_back=5,
                              extreme_idx=102 + i, sweep_extreme=1.101, penetration_pips=3.0, session=sid))
            i += 1
    for _ in range(n_break):
        rows.append(dict(td=pd.Timestamp("2024-01-02") + pd.Timedelta(days=i), level_name="prev_low",
                          side="below", level_price=1.09, raid_idx=200 + i, t_raid=pd.Timestamp("2024-01-02 09:00"),
                          t_raid_h=9.0, raid_type="break", close_back_idx=None, t_close_back=pd.NaT,
                          bars_to_close_back=None, extreme_idx=201 + i, sweep_extreme=1.089,
                          penetration_pips=5.0, session="lon"))
        i += 1
    return pd.DataFrame(rows)


def test_sample_fvgs_is_deterministic_for_a_fixed_seed():
    fvg = _mk_fvg(8, 8)
    df = _mk_df()
    a = hand_check.sample_fvgs(fvg, df, n=10, seed=5)
    b = hand_check.sample_fvgs(fvg, df, n=10, seed=5)
    pd.testing.assert_frame_equal(a, b)


def test_sample_fvgs_stratifies_bull_and_bear():
    fvg = _mk_fvg(20, 2)  # heavily lopsided pool
    df = _mk_df()
    out = hand_check.sample_fvgs(fvg, df, n=10, seed=1)
    counts = out["direction"].value_counts()
    assert counts.get("bear", 0) >= 1, "a lopsided pool should still pull in the minority direction"


def test_sample_fvgs_adds_td_and_h_columns():
    fvg = _mk_fvg(5, 5)
    df = _mk_df()
    out = hand_check.sample_fvgs(fvg, df, n=6, seed=2)
    assert "td" in out.columns and "h" in out.columns
    for _, row in out.iterrows():
        expected_td, expected_h = df.iloc[int(row["bar_idx"])][["td", "h"]]
        assert row["td"] == expected_td
        assert row["h"] == pytest.approx(expected_h)


def test_sample_fvgs_never_exceeds_the_pool():
    fvg = _mk_fvg(2, 1)
    df = _mk_df()
    out = hand_check.sample_fvgs(fvg, df, n=100, seed=3)
    assert len(out) == 3


def test_sample_sweeps_only_picks_sweep_type_not_break():
    raids = _mk_raids(n_sweep_per_session=2, n_break=4)
    out = hand_check.sample_sweeps(raids, n=6, seed=5)
    assert (out["raid_type"] == "sweep").all()


def test_sample_sweeps_stratifies_across_sessions():
    raids = _mk_raids(n_sweep_per_session=1, sessions=("asia", "lon", "nyam_kz", "nypm"))
    out = hand_check.sample_sweeps(raids, n=4, seed=9)
    assert out["session"].nunique() == 4


def test_sample_sweeps_deterministic_for_a_fixed_seed():
    raids = _mk_raids(n_sweep_per_session=5)
    a = hand_check.sample_sweeps(raids, n=5, seed=7)
    b = hand_check.sample_sweeps(raids, n=5, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_build_renders_a_replay_link_per_row():
    fvg = _mk_fvg(2, 2)
    df = _mk_df()
    fvg_sample = hand_check.sample_fvgs(fvg, df, n=4, seed=1)
    raids = _mk_raids(n_sweep_per_session=2)
    sweep_sample = hand_check.sample_sweeps(raids, n=4, seed=1)
    html = hand_check.build(fvg_sample, sweep_sample)
    # +1: the intro box also mentions "Open in replay" once in its instructions to Akash.
    assert html.count("Open in replay") == len(fvg_sample) + len(sweep_sample) + 1
    assert html.count("target='_blank'") == len(fvg_sample) + len(sweep_sample)
    assert "127.0.0.1:8765" in html
    assert "<html>" in html and "</html>" in html


def test_build_handles_empty_samples():
    empty_fvg = pd.DataFrame(columns=["td", "h", "direction", "gap_pips", "top", "ce", "bottom",
                                       "is_displacement_leg", "first_touch_idx"])
    empty_sweep = pd.DataFrame(columns=["td", "t_raid_h", "session", "level_name", "side",
                                         "penetration_pips", "bars_to_close_back"])
    html = hand_check.build(empty_fvg, empty_sweep)
    assert "0 FVGs" in html and "0 sweeps" in html
