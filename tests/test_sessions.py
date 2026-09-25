"""ROADMAP Phase 5.1/5.2 unit + structural tests: the SESSION table (nylab/sessions.py),
character labels, day types, the naming-collision handling found while wiring this up against
Akash's real data, and the look-ahead registration. Uses small hand-built fixtures for the
pure-logic pieces (character rules, raid classification) and a short run through the real
pipeline (loader -> timezones -> days.build_days) for the structural/shape checks -- exact
character-label THRESHOLD tuning is explicitly ROADMAP ticket 5.6's job (replay + Akash's own
eye on 30 real days), not something a synthetic fixture should try to pre-judge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import config as cfg
from nylab import days as days_mod
from nylab import sessions as sess_mod
from nylab.data import timezones


def _synth_bars(n_days: int = 6, seed: int = 3) -> pd.DataFrame:
    """Cheap continuous M5 server-time bars (ny+7 convention), `n_days` calendar days, random
    walk -- just enough for build_days()/build_one_session() to run over real trading-day
    plumbing (td/h columns, weekend filtering) without pulling in the full 5-year fixture."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01 00:00", periods=n_days * 288, freq="5min")  # server time
    walk = rng.normal(0, 0.00015, len(idx)).cumsum() + 1.10000
    high = walk + rng.uniform(0, 0.00012, len(idx))
    low = walk - rng.uniform(0, 0.00012, len(idx))
    close = walk + rng.normal(0, 0.00003, len(idx))
    df = pd.DataFrame({"server": idx, "open": walk, "high": high, "low": low, "close": close})
    return df


def _build_day_and_bars():
    raw = _synth_bars()
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    windows = cfg.legacy_windows()
    d = days_mod.build_days(raw, windows)
    return raw, d


def test_build_one_session_shape_and_columns():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    pip = cfg.legacy_windows()["pip"]
    tbl = sess_mod.build_one_session(df, d, None, sessions_cfg, "lon", pip)
    assert tbl.index.equals(d.index)
    for col in ("open", "high", "low", "close", "range_pips", "net_pips", "dir", "close_loc",
                "er", "swing_count", "disp_count", "fvg_count_bull", "fvg_count_bear",
                "took_prev_high", "took_prev_low", "both_sides", "raids_count", "character"):
        assert col in tbl.columns, col
    assert (tbl["close_loc"].dropna() >= -1e-9).all() and (tbl["close_loc"].dropna() <= 1 + 1e-9).all()


def test_build_all_sessions_covers_every_id_except_cbdr():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    tables = sess_mod.build_all_sessions(df, d, None, sessions_cfg, cfg.legacy_windows()["pip"])
    assert set(tables) == set(sess_mod.SESSION_IDS)
    assert "cbdr" not in tables


def test_attach_session_features_skips_lon_dir_collision_and_keeps_legacy_value():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    tables = sess_mod.build_all_sessions(df, d, None, sessions_cfg, cfg.legacy_windows()["pip"])
    legacy_lon_dir = d["lon_dir"].copy()
    d2 = sess_mod.attach_session_features(d, tables)
    assert "lon_dir" in d2.attrs["sessions_skipped_columns"]
    assert d2["lon_dir"].reset_index(drop=True).equals(legacy_lon_dir.reset_index(drop=True))


def test_attach_session_features_renames_nyam_to_avoid_collision():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    tables = sess_mod.build_all_sessions(df, d, None, sessions_cfg, cfg.legacy_windows()["pip"])
    d2 = sess_mod.attach_session_features(d, tables)
    # the new, broader NY AM session's raw price columns live under nyam_full_*, NEVER nyam_*
    # (that stays the legacy 07:00-10:00 killzone) -- this is the whole point of the rename.
    assert "nyam_full_high" in d2.columns
    assert "nyam_high" in d2.columns  # the pre-existing LEGACY column, untouched
    legacy_nyam_high = d["nyam_high"].reset_index(drop=True)
    assert d2["nyam_high"].reset_index(drop=True).equals(legacy_nyam_high)  # nyam_full didn't overwrite it
    # nyam_kz gets its own NEW columns (character etc.) under nyam_kz_*, distinct from legacy nyam_*
    assert "nyam_kz_character" in d2.columns
    assert "nyam_full_character" in d2.columns


def test_day_types_are_mutually_exclusive_and_cover_every_day():
    df, d = _build_day_and_bars()
    dt = sess_mod.build_day_types(d)
    assert set(dt["day_type"].dropna().unique()) <= set(sess_mod.DAY_TYPE_ORDER)
    assert dt["day_type"].notna().all()


def test_column_docs_registers_available_at_h_matching_S1_ends_and_covers_nyam_full():
    sessions_cfg = cfg.sessions()
    docs = sess_mod.column_docs(sessions_cfg)
    assert docs["lon_character"] == sessions_cfg["lon"][1] == 5.0
    assert docs["nyam_kz_character"] == sessions_cfg["nyam_kz"][1] == 10.0
    # nyam's own S1 "Ends" (12.0) is what nyam_full_* is registered at, NOT nyam's legacy 10.0.
    assert docs["nyam_full_character"] == sessions_cfg["nyam"][1] == 12.0
    assert "nyam_character" not in docs  # never registered -- "nyam.character" must fail loudly
    assert docs["day_inside_prev_range"] == 17.0


@pytest.mark.parametrize("row,expected", [
    # quiet wins even though it would also match "normal" (first-match-wins, quiet applied last
    # in _label_character's overwrite order == highest priority per CHARACTER_ORDER)
    (dict(range_rel=0.3, er=0.9, close_loc=0.5, took_prev_high=False, took_prev_low=False, both_sides=False), "quiet"),
    (dict(range_rel=1.0, er=0.9, close_loc=0.1, took_prev_high=True, took_prev_low=False, both_sides=False), "reversal"),
    (dict(range_rel=1.0, er=0.9, close_loc=0.9, took_prev_high=False, took_prev_low=True, both_sides=False), "reversal"),
    (dict(range_rel=1.0, er=0.9, close_loc=0.9, took_prev_high=False, took_prev_low=False, both_sides=False), "trend"),
    (dict(range_rel=1.0, er=0.9, close_loc=0.5, took_prev_high=True, took_prev_low=True, both_sides=True), "range_both"),
    (dict(range_rel=1.0, er=0.1, close_loc=0.5, took_prev_high=False, took_prev_low=False, both_sides=False), "chop"),
    (dict(range_rel=1.0, er=0.35, close_loc=0.5, took_prev_high=False, took_prev_low=False, both_sides=False), "normal"),
    # trend v2's alternate path (confirmed with Akash 2026-09-25): a session with an unusually
    # large range and a strongly extreme close is `trend` even at moderate er (< 0.45), because
    # a low er alone shouldn't override an obviously decisive, wide session.
    (dict(range_rel=1.48, er=0.18, close_loc=0.94, took_prev_high=False, took_prev_low=False, both_sides=False), "trend"),
    (dict(range_rel=2.28, er=0.34, close_loc=0.05, took_prev_high=False, took_prev_low=False, both_sides=False), "trend"),
    # a large range with only a mildly extreme close (inside the 0.20/0.80 band) must NOT
    # qualify via the alternate path -- range alone isn't enough, the close must be decisive too.
    (dict(range_rel=2.0, er=0.3, close_loc=0.5, took_prev_high=False, took_prev_low=False, both_sides=False), "normal"),
    # a strongly extreme close with only a normal-sized range must NOT qualify either -- both
    # conditions of the alternate path are required together.
    (dict(range_rel=1.0, er=0.3, close_loc=0.95, took_prev_high=False, took_prev_low=False, both_sides=False), "normal"),
])
def test_label_character_ordered_rules(row, expected):
    s = pd.DataFrame([row])
    out = sess_mod._label_character(s)
    assert out.iloc[0] == expected


def test_label_character_nan_when_inputs_missing():
    s = pd.DataFrame([dict(range_rel=np.nan, er=0.9, close_loc=0.5,
                            took_prev_high=False, took_prev_low=False, both_sides=False)])
    out = sess_mod._label_character(s)
    assert pd.isna(out.iloc[0])


def test_classify_raid_side_sweep_vs_break_vs_none():
    # bars: level=1.0000. Case A: raids above then closes back within K_BACK -> sweep.
    highs = np.array([0.9995, 1.0002, 1.0001, 0.9998, 0.9997, 0.9996, 0.9995, 0.9994])
    lows = np.array([0.9990, 0.9999, 0.9998, 0.9994, 0.9993, 0.9992, 0.9991, 0.9990])
    closes = np.array([0.9993, 1.0001, 0.9999, 0.9996, 0.9995, 0.9994, 0.9993, 0.9992])
    pip = 0.0001
    found = sess_mod._classify_raid_side(highs, lows, closes, 0, len(highs), 1.0000, "above", pip)
    assert found is not None and found[1] == "sweep"

    # Case B: raids above and closes well beyond by > BREAK_CLOSE_PIPS -> break.
    highs2 = np.array([0.9995, 1.0010, 1.0012, 1.0013])
    lows2 = np.array([0.9990, 1.0004, 1.0006, 1.0007])
    closes2 = np.array([0.9993, 1.0008, 1.0010, 1.0011])  # +8 pips beyond level immediately
    found2 = sess_mod._classify_raid_side(highs2, lows2, closes2, 0, len(highs2), 1.0000, "above", pip)
    assert found2 is not None and found2[1] == "break"

    # Case C: never trades through the level -> no raid at all.
    highs3 = np.array([0.9990, 0.9991, 0.9992])
    lows3 = np.array([0.9980, 0.9981, 0.9982])
    closes3 = np.array([0.9985, 0.9986, 0.9987])
    assert sess_mod._classify_raid_side(highs3, lows3, closes3, 0, len(highs3), 1.0000, "above", pip) is None


def test_efficiency_ratio_straight_line_vs_chop():
    idx = pd.date_range("2024-01-02 07:00", periods=6, freq="5min")
    straight = pd.DataFrame({"td": pd.Timestamp("2024-01-02"), "h": [7.0, 7.083, 7.166, 7.25, 7.33, 7.416],
                              "close": [1.000, 1.001, 1.002, 1.003, 1.004, 1.005]})
    chop = pd.DataFrame({"td": pd.Timestamp("2024-01-02"), "h": [7.0, 7.083, 7.166, 7.25, 7.33, 7.416],
                         "close": [1.000, 1.002, 1.000, 1.002, 1.000, 1.000]})
    er_straight = sess_mod._efficiency_ratio(straight, 7.0, 8.0)
    er_chop = sess_mod._efficiency_ratio(chop, 7.0, 8.0)
    assert er_straight.iloc[0] == pytest.approx(1.0, abs=1e-9)
    assert er_chop.iloc[0] < 0.3
