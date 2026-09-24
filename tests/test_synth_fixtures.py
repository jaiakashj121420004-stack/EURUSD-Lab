"""Sanity tests for tests/fixtures/make_synth.py (Phase 0.2)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_synth as ms  # noqa: E402


def test_clean_bars_are_deterministic():
    a = ms.make_clean_bars(years=0.2, seed=7)
    b = ms.make_clean_bars(years=0.2, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_clean_bars_ohlc_integrity():
    b = ms.make_clean_bars(years=0.5, seed=7)
    assert (b["low"] <= b[["open", "close"]].min(axis=1) + 1e-12).all()
    assert (b["high"] >= b[["open", "close"]].max(axis=1) - 1e-12).all()
    assert (b["low"] <= b["high"]).all()


def test_no_weekend_bars():
    b = ms.make_clean_bars(years=0.5, seed=7)
    dow, hour = b["ny"].dt.dayofweek, b["ny"].dt.hour
    closed = ((dow == 4) & (hour >= 17)) | (dow == 5) | ((dow == 6) & (hour < 17))
    assert not closed.any()


def test_planted_edge_moves_the_hit_rate():
    """The planted variant must make 'pre-NY raids London high -> NY drives down' more
    common than in the clean variant (this is what AT-02 will check via the pipeline)."""
    clean = ms.make_clean_bars(years=5, seed=7)
    planted = ms.plant_edge(clean, seed=7, frac=0.6)

    for bars, label in ((clean, "clean"), (planted, "planted")):
        b = bars.copy()
        b["td"] = ms.trading_day(b["ny"])
        h = b["ny"].dt.hour + b["ny"].dt.minute / 60.0
        lon_high = b.loc[(h >= 2) & (h < 5)].groupby("td")["high"].max()
        pre_high = b.loc[(h >= 7) & (h < 9.5)].groupby("td")["high"].max()
        o930 = b.loc[(h >= 9.5) & (h < 10)].groupby("td")["open"].first()
        close16 = b.loc[(h >= 15.75) & (h < 16)].groupby("td")["close"].last()

        common = lon_high.index.intersection(pre_high.index).intersection(o930.index).intersection(close16.index)
        cond = common[pre_high.loc[common].values > lon_high.loc[common].values]
        drive_down = (close16.loc[cond] < o930.loc[cond]).mean()
        if label == "clean":
            hit_clean = drive_down
        else:
            hit_planted = drive_down

    assert hit_planted > hit_clean + 0.10, (hit_clean, hit_planted)
    assert hit_planted >= 0.58


def test_variant_frac_is_respected_within_noise():
    clean = ms.make_clean_bars(years=5, seed=7)
    planted = ms.plant_edge(clean, seed=7, frac=0.6)
    # planted bars differ from clean bars only in the afternoon window on affected days
    diff = ~np.isclose(clean["close"].values, planted["close"].values)
    assert diff.sum() > 0
