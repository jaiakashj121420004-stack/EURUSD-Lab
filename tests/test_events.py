"""tests/test_events.py -- ROADMAP 7.2/7.3: FVG lifecycle, full raid/sweep detail, MSS, order
blocks. Small hand-built fixtures (same style as tests/test_sessions.py's raid-classification
unit tests) so expected behavior can be worked out by eye."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import events, ict_features, structure

PIP = 0.0001


def _mk_bars(rows, start="2024-01-02 08:00", freq="5min"):
    """rows: list of (open, high, low, close) tuples. Adds td (single trading day) / h columns
    the way nylab.days/_prepare_bars would, so events.detect_raids's groupby('td') works. Uses a
    plain 0..n-1 RangeIndex -- the SAME convention every real `df` in this codebase uses
    (nylab.__main__._prepare_bars does `raw.reset_index(drop=True)`), since detect_raids/
    detect_mss's `groups.items()` -> `.to_numpy()` treats index values as bar POSITIONS."""
    ts = pd.date_range(start, periods=len(rows), freq=freq)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["ny"] = ts
    df["td"] = pd.Timestamp(start.split(" ")[0])
    start_h = float(start.split(" ")[1].split(":")[0]) + float(start.split(" ")[1].split(":")[1]) / 60
    df["h"] = start_h + np.arange(len(rows)) * (5 / 60)
    return df


def test_fvg_lifecycle_bullish_gap_touched_and_filled():
    # 16 flat warm-up bars so ATR(14) is non-NaN by the time the real pattern starts (bars
    # 0.15-pip true ranges -- tiny, so they don't affect the min_atr_mult=0 threshold used below
    # anyway; they exist only to get ATR out of its NaN warm-up window).
    warm = [(1.0000, 1.0002, 0.9999, 1.0000)] * 16
    rows = warm + [
        (1.0000, 1.0000, 0.9995, 0.9998),   # bar16: high=1.0000
        (1.0005, 1.0015, 1.0000, 1.0012),   # bar17: middle bar
        (1.0012, 1.0020, 1.0010, 1.0018),   # bar18: low=1.0010 > bar16 high (1.0000) -> gap
        (1.0018, 1.0018, 1.0010, 1.0011),   # bar19: dips to 1.0010 -> first_touch/full_fill (ce=1.0005)
        (1.0011, 1.0011, 0.9990, 0.9999),   # bar20: closes below bottom (1.0000) -> invalidated
    ]
    bars = _mk_bars(rows)
    atr = ict_features.atr(bars, n=14)
    out = events.fvg_lifecycle(bars, atr, PIP, min_pips=0.1, min_atr_mult=0.0, horizon_bars=10)
    bull = out[(out["direction"] == "bull") & (out["bar_idx"] == 18)]
    assert len(bull) == 1
    row = bull.iloc[0]
    assert row["bottom"] == pytest.approx(1.0000)
    assert row["top"] == pytest.approx(1.0010)
    assert row["first_touch_idx"] == 19  # bar19's low (1.0010) touches the top exactly
    assert row["full_fill_idx"] == 20     # bar20's low (0.9990) is the first to reach the bottom
    assert row["invalidated_idx"] == 20   # bar20 also closes at 0.9999 < bottom, same bar


def test_detect_raids_finds_sweep_then_a_second_raid_after_close_back():
    # Level = 1.0000 (an 'above' level, e.g. a session high). First poke above, closes back
    # (sweep). Then a SECOND poke above later in the same window, closes back again.
    rows = [
        (0.9995, 0.9998, 0.9990, 0.9996),  # 0: below level
        (0.9997, 1.0005, 0.9995, 0.9998),  # 1: raid 1 (high=1.0005 > level), closes back same bar
        (0.9998, 0.9999, 0.9990, 0.9993),  # 2: quiet
        (0.9994, 1.0008, 0.9992, 0.9995),  # 3: raid 2, closes back same bar
        (0.9995, 0.9996, 0.9985, 0.9988),  # 4: quiet
    ]
    bars = _mk_bars(rows)
    level_series = pd.Series({bars["td"].iloc[0]: 1.0000})
    raids = events.detect_raids(bars, {"lon_high": ("above", level_series)}, lo_h=bars["h"].iloc[0],
                                 hi_h=bars["h"].iloc[-1] + 1, pip=PIP)
    assert len(raids) == 2
    assert (raids["raid_type"] == "sweep").all()
    assert raids["raid_idx"].tolist() == [1, 3]
    assert raids.iloc[0]["sweep_extreme"] == pytest.approx(1.0005)
    assert raids.iloc[1]["sweep_extreme"] == pytest.approx(1.0008)
    assert raids.iloc[0]["penetration_pips"] == pytest.approx(5.0, abs=0.01)


def test_detect_raids_classifies_break_when_no_close_back_within_k_back():
    rows = [(0.9995, 0.9998, 0.9990, 0.9996)]
    rows += [(1.0005 + i * 0.0002, 1.0010 + i * 0.0002, 1.0003 + i * 0.0002, 1.0008 + i * 0.0002)
             for i in range(8)]  # keeps trading further above the level, never closes back
    bars = _mk_bars(rows)
    level_series = pd.Series({bars["td"].iloc[0]: 1.0000})
    raids = events.detect_raids(bars, {"lvl": ("above", level_series)}, lo_h=bars["h"].iloc[0],
                                 hi_h=bars["h"].iloc[-1] + 1, pip=PIP, k_back=6)
    assert len(raids) == 1
    assert raids.iloc[0]["raid_type"] == "break"
    assert pd.isna(raids.iloc[0]["t_close_back"])


def test_detect_raids_finds_a_new_raid_after_price_resets_past_a_break():
    # A break (never closes back within k_back=2), price stays extended for a while, THEN
    # actually comes back under the level, THEN pokes above again -- that second poke must be
    # its own new raid event, not folded into the first.
    rows = [
        (0.9995, 0.9998, 0.9990, 0.9996),   # 0: below level
        (0.9997, 1.0005, 0.9996, 1.0003),   # 1: raid 1 -- stays above
        (1.0003, 1.0006, 1.0001, 1.0004),   # 2: still above (k_back=2 window ends here, no close back -> break)
        (1.0004, 1.0006, 1.0001, 1.0002),   # 3: still above
        (1.0002, 1.0002, 0.9990, 0.9993),   # 4: FIRST close back below level -- the reset point
        (0.9993, 0.9994, 0.9985, 0.9988),   # 5: quiet, below level
        (0.9988, 1.0010, 0.9986, 1.0002),   # 6: raid 2 -- a genuinely new poke above (close stays
                                             #    within break_close_pips so it isn't an instant break)
        (1.0002, 1.0002, 0.9990, 0.9991),   # 7: closes back -> sweep
    ]
    bars = _mk_bars(rows)
    level_series = pd.Series({bars["td"].iloc[0]: 1.0000})
    raids = events.detect_raids(bars, {"lvl": ("above", level_series)}, lo_h=bars["h"].iloc[0],
                                 hi_h=bars["h"].iloc[-1] + 1, pip=PIP, k_back=2)
    assert raids["raid_idx"].tolist() == [1, 6]
    assert raids.iloc[0]["raid_type"] == "break"
    assert raids.iloc[1]["raid_type"] == "sweep"


def _mss_fixture():
    # bars 0-4: a clean fractal swing low pivot at position 2 (0.9998), confirmed at position 4
    # (n=2 each side). bars 5-7: rally, sweep a high level at 1.0035, close back, then a big
    # displacement candle down through the prior swing low.
    rows = [
        (1.0022, 1.0025, 1.0020, 1.0023),   # 0
        (1.0017, 1.0020, 1.0015, 1.0018),   # 1
        (1.0002, 1.0015, 0.9998, 1.0005),   # 2: swing low pivot (low=0.9998)
        (1.0018, 1.0020, 1.0015, 1.0019),   # 3
        (1.0023, 1.0025, 1.0020, 1.0024),   # 4: pivot confirmed here (2+2)
        (1.0025, 1.0030, 1.0022, 1.0028),   # 5: rallying toward the level
        (1.0028, 1.0040, 1.0025, 1.0026),   # 6: sweeps level 1.0035, closes back same bar -> sweep, extreme=1.0040
        (1.0026, 1.0026, 0.9950, 0.9955),   # 7: displacement candle down, closes well below 0.9998
    ]
    return _mk_bars(rows)


def test_detect_mss_after_bearish_sweep_requires_displacement_and_close_below_prior_swing_low():
    bars = _mss_fixture()
    atr = ict_features.atr(bars, n=2)
    swings = structure.label_swings(bars, n=2)
    displacement = ict_features.displacement_candles(bars, atr, k_disp=1.0, body_ratio=0.3)
    bull_fvg, bear_fvg = ict_features.fair_value_gaps(bars, atr, min_pips=0.1, min_atr_mult=0.0, pip=PIP)

    level_series = pd.Series({bars["td"].iloc[0]: 1.0035})
    raids = events.detect_raids(bars, {"hi": ("above", level_series)}, lo_h=bars["h"].iloc[0],
                                 hi_h=bars["h"].iloc[-1] + 1, pip=PIP)
    assert len(raids) == 1 and raids.iloc[0]["raid_type"] == "sweep"

    mss = events.detect_mss(bars, raids, swings, displacement, bull_fvg, bear_fvg, max_bars=10)
    assert len(mss) == 1
    row = mss.iloc[0]
    assert row["direction"] == "bearish"
    assert row["mss_level"] == pytest.approx(0.9998)
    assert row["mss_idx"] == 7


def test_detect_mss_finds_nothing_without_a_prior_confirmed_swing():
    rows = [
        (1.0010, 1.0040, 1.0008, 1.0038),  # sweeps immediately, no prior swing low exists at all
        (1.0038, 1.0038, 1.0010, 1.0011),
        (1.0011, 1.0011, 0.9950, 0.9960),
    ]
    bars = _mk_bars(rows)
    atr = ict_features.atr(bars, n=2)
    swings = structure.label_swings(bars, n=2)
    displacement = ict_features.displacement_candles(bars, atr, k_disp=1.0, body_ratio=0.3)
    bull_fvg, bear_fvg = ict_features.fair_value_gaps(bars, atr, min_pips=0.1, min_atr_mult=0.0, pip=PIP)
    level_series = pd.Series({bars["td"].iloc[0]: 1.0035})
    raids = events.detect_raids(bars, {"hi": ("above", level_series)}, lo_h=bars["h"].iloc[0],
                                 hi_h=bars["h"].iloc[-1] + 1, pip=PIP)
    mss = events.detect_mss(bars, raids, swings, displacement, bull_fvg, bear_fvg, max_bars=10)
    assert len(mss) == 0


def test_detect_order_blocks_finds_last_up_close_before_bearish_displacement_leg():
    bars = _mss_fixture()
    atr = ict_features.atr(bars, n=2)
    swings = structure.label_swings(bars, n=2)
    displacement = ict_features.displacement_candles(bars, atr, k_disp=1.0, body_ratio=0.3)
    bull_fvg, bear_fvg = ict_features.fair_value_gaps(bars, atr, min_pips=0.1, min_atr_mult=0.0, pip=PIP)
    level_series = pd.Series({bars["td"].iloc[0]: 1.0035})
    raids = events.detect_raids(bars, {"hi": ("above", level_series)}, lo_h=bars["h"].iloc[0],
                                 hi_h=bars["h"].iloc[-1] + 1, pip=PIP)
    mss = events.detect_mss(bars, raids, swings, displacement, bull_fvg, bear_fvg, max_bars=10)
    assert len(mss) == 1
    obs = events.detect_order_blocks(bars, mss, displacement)
    assert len(obs) == 1
    row = obs.iloc[0]
    # bar 6 (the sweep bar itself) is the last up-close (close 1.0026 > open 1.0028? -- no,
    # 1.0026 < 1.0028, so bar 6 is actually DOWN-close; the search must walk back further to
    # find the true last up-close bar before the displacement leg at bar 7).
    assert bars.loc[row["ob_idx"], "close"] > bars.loc[row["ob_idx"], "open"]
    assert row["ob_idx"] < 7
