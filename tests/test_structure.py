"""tests/test_structure.py -- ROADMAP 7.1: swing labeling (HH/LH/HL/LL) and structure_score.
Small, hand-built synthetic bar series so the expected swings/labels can be worked out by eye,
rather than relying on real data where "is this actually a swing" is itself a judgment call."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import structure


def _bars(highs, lows=None):
    """closes/opens don't matter for swing detection -- only high/low do."""
    highs = np.asarray(highs, dtype=float)
    lows = lows if lows is not None else highs - 0.0005
    lows = np.asarray(lows, dtype=float)
    idx = pd.date_range("2024-01-02 08:00", periods=len(highs), freq="5min")
    return pd.DataFrame({"open": highs, "high": highs, "low": lows, "close": highs}, index=idx)


def test_swing_highs_labeled_hh_lh_by_price_vs_previous_confirmed_swing():
    # A rising zigzag of highs, n=2: pivots (fractal swing highs, each > both neighbors on
    # each side) sit at indices 2 (1.0010), 6 (1.0020), 10 (1.0015 -- LOWER than 1.0020 -> LH).
    highs = [1.0000, 1.0005, 1.0010, 1.0005, 1.0000,
             1.0005, 1.0020, 1.0010, 1.0005, 1.0000,
             1.0015, 1.0005, 1.0000]
    bars = _bars(highs)
    out = structure.label_swings(bars, n=2)
    pivots = out.index[out["swing_high"]]
    assert len(pivots) == 3
    labels = out.loc[pivots, "swing_high_label"].tolist()
    # first pivot has no predecessor -> NaN; second is HH (0.0020 > 0.0010); third is LH.
    assert labels[0] is None or (isinstance(labels[0], float) and np.isnan(labels[0])) or pd.isna(labels[0])
    assert labels[1] == "HH"
    assert labels[2] == "LH"


def test_swing_high_only_available_n_bars_after_its_pivot():
    highs = [1.0000, 1.0005, 1.0010, 1.0005, 1.0000, 1.0005, 1.0020, 1.0010, 1.0005]
    bars = _bars(highs)
    out = structure.label_swings(bars, n=2)
    pivot_pos = 2  # the 1.0010 pivot
    avail = out["swing_high_available_idx"].iloc[pivot_pos]
    assert avail == pivot_pos + 2  # not knowable until 2 bars later


def test_swing_lows_labeled_hl_ll():
    lows = [1.0020, 1.0015, 1.0010, 1.0015, 1.0020,
            1.0015, 1.0000, 1.0010, 1.0015, 1.0020,
            1.0005, 1.0015, 1.0020]
    highs = np.asarray(lows) + 0.0005
    bars = _bars(highs, lows=lows)
    out = structure.label_swings(bars, n=2)
    pivots = out.index[out["swing_low"]]
    assert len(pivots) == 3
    labels = out.loc[pivots, "swing_low_label"].tolist()
    assert pd.isna(labels[0])
    assert labels[1] == "LL"  # 1.0000 < 1.0010
    assert labels[2] == "HL"  # 1.0005 > 1.0000


def test_structure_score_counts_recent_k_confirmed_swings():
    # Build a clean uptrend structure: every new swing high is a HH, every new swing low is a HL
    # -> structure_score should be +1.0 once k confirmed swings of that kind exist.
    highs = [1.0000, 1.0005, 1.0010, 1.0005, 1.0002,
             1.0006, 1.0020, 1.0010, 1.0008,
             1.0012, 1.0030, 1.0020, 1.0018,
             1.0022, 1.0040, 1.0030, 1.0028]
    bars = _bars(highs)
    swings = structure.label_swings(bars, n=2)
    last_idx = len(bars) - 1
    score = structure.structure_score_at(swings, as_of_idx=last_idx, k=2)
    assert score == pytest.approx(1.0)  # last 2 confirmed swing highs are both HH


def test_structure_score_nan_when_not_enough_confirmed_swings_yet():
    highs = [1.0000, 1.0005, 1.0010, 1.0005, 1.0000]
    bars = _bars(highs)
    swings = structure.label_swings(bars, n=2)
    score = structure.structure_score_at(swings, as_of_idx=2, k=5)
    assert np.isnan(score)


def test_structure_score_series_is_piecewise_constant_and_matches_pointwise():
    highs = [1.0000, 1.0005, 1.0010, 1.0005, 1.0002,
             1.0006, 1.0020, 1.0010, 1.0008,
             1.0012, 1.0030, 1.0020, 1.0018]
    bars = _bars(highs)
    swings = structure.label_swings(bars, n=2)
    series = structure.structure_score_series(swings, k=2)
    for i in range(len(bars)):
        expected = structure.structure_score_at(swings, i, k=2)
        got = series.iloc[i]
        if np.isnan(expected):
            assert np.isnan(got)
        else:
            assert got == pytest.approx(expected)
