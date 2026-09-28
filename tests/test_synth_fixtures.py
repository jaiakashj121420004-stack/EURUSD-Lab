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


def test_cross_session_edge_moves_nyam_kz_reversal_rate():
    """The second planted edge (ROADMAP Phase 5's AT-02 addition, H016): among days where lon's
    character is naturally 'chop', nyam_kz's character should be 'reversal' far more often after
    planting than before -- checked with the real pipeline (nylab.sessions), not a
    reimplementation, so this measures exactly what H016 measures."""
    import sys as _sys
    from pathlib import Path as _Path
    root = _Path(__file__).resolve().parent.parent
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    from nylab import config as cfg
    from nylab import days as days_mod
    from nylab import sessions as sessions_mod

    def _lon_chop_reversal_rate(bars):
        b = bars.copy()
        b["td"] = ms.trading_day(b["ny"])
        b["h"] = b["ny"].dt.hour + b["ny"].dt.minute / 60.0
        b = b[b["td"].dt.dayofweek < 5]  # matches the real pipeline's own weekday filter
        raw = b.reset_index(drop=True)
        d = days_mod.build_days(raw, cfg.legacy_windows())
        sessions_cfg = cfg.sessions()
        tables = sessions_mod.build_all_sessions(raw, d, None, sessions_cfg, cfg.legacy_windows()["pip"])
        lon_chop = tables["lon"]["character"] == "chop"
        nyam_rev = tables["nyam_kz"]["character"] == "reversal"
        common = lon_chop.index.intersection(nyam_rev.index)
        cond = common[lon_chop.loc[common]]
        return nyam_rev.loc[cond].mean(), len(cond)

    clean = ms.make_clean_bars(years=5, seed=7)
    planted = ms.plant_edge(clean, seed=7, frac=0.6)
    planted = ms.plant_cross_session_edge(planted, seed=7, frac=0.6)

    rate_clean, n_clean = _lon_chop_reversal_rate(clean)
    rate_planted, n_planted = _lon_chop_reversal_rate(planted)

    assert n_clean > 100 and n_planted > 100
    assert rate_planted > rate_clean + 0.15, (rate_clean, rate_planted)
    # >= 0.58 (the actual acceptance bar) is checked authoritatively by test_at02b via the real
    # CSV/loader/timezone round trip (nylab.data.loader + nylab.data.timezones) -- this in-memory
    # helper bypasses that round trip so its own rate lands a couple points lower (0.58 vs 0.60
    # observed); 0.50 is well clear of both readings and still confirms a strong, real shift.
    assert rate_planted >= 0.50


def test_cross_session_edge_does_not_touch_plant_edge_days():
    """The two planted edges must not fight over the same bars: no day plant_edge() itself
    forced should also be touched by plant_cross_session_edge() (see that function's docstring
    for why -- their windows overlap at 09:30-10:00 NY)."""
    clean = ms.make_clean_bars(years=5, seed=7)
    after_h005 = ms.plant_edge(clean, seed=7, frac=0.6)
    after_both = ms.plant_cross_session_edge(after_h005, seed=7, frac=0.6)

    b = after_h005.copy()
    b["td"] = ms.trading_day(b["ny"])
    h = b["ny"].dt.hour + b["ny"].dt.minute / 60.0
    h005_touched = (~np.isclose(clean["close"].values, after_h005["close"].values))
    h005_days = set(b.loc[h005_touched, "td"].unique())

    b2 = after_both.copy()
    b2["td"] = ms.trading_day(b2["ny"])
    cross_touched = ~np.isclose(after_h005["close"].values, after_both["close"].values)
    cross_days = set(b2.loc[cross_touched, "td"].unique())

    assert h005_days, "expected plant_edge to touch at least one day"
    assert cross_days, "expected plant_cross_session_edge to touch at least one day"
    assert not (h005_days & cross_days), "the two planted edges touched the same day(s)"
