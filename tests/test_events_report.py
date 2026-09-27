"""tests/test_events_report.py -- ROADMAP 7.3: events.parquet build + descriptive stats.
Runs through a short synthetic pipeline (same _synth_bars/_build_day_and_bars pattern as
tests/test_sessions.py) -- exact numbers aren't asserted (this is a descriptive report over
essentially random synthetic data), only shape/sanity/no-crash and the specific no-look-ahead
and consistency properties that MUST hold regardless of the input."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import config as cfg
from nylab import days as days_mod
from nylab import events_report
from nylab.data import timezones


def _synth_bars(n_days: int = 40, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01 00:00", periods=n_days * 288, freq="5min")
    walk = rng.normal(0, 0.00015, len(idx)).cumsum() + 1.10000
    high = walk + rng.uniform(0, 0.00012, len(idx))
    low = walk - rng.uniform(0, 0.00012, len(idx))
    close = walk + rng.normal(0, 0.00003, len(idx))
    return pd.DataFrame({"server": idx, "open": walk, "high": high, "low": low, "close": close})


def _build_day_and_bars(n_days=40, seed=7):
    raw = _synth_bars(n_days, seed)
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    windows = cfg.legacy_windows()
    d = days_mod.build_days(raw, windows)
    return raw, d


def test_build_events_table_runs_and_returns_all_four_kinds():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    pip = cfg.legacy_windows()["pip"]
    tables = events_report.build_events_table(df, d, sessions_cfg, pip)
    assert set(tables.keys()) == {"fvg", "raids", "mss", "order_blocks"}
    assert isinstance(tables["fvg"], pd.DataFrame)
    # Random-walk synthetic data over 40 days should produce at least SOME FVGs and raids --
    # an empty table here would mean the pipeline silently found nothing, worth flagging.
    assert len(tables["fvg"]) > 0
    assert len(tables["raids"]) > 0


def test_raids_never_reference_a_session_outside_the_configured_windows():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    pip = cfg.legacy_windows()["pip"]
    tables = events_report.build_events_table(df, d, sessions_cfg, pip)
    raids = tables["raids"]
    if len(raids):
        assert raids["session"].isin(sessions_cfg.keys()).all()


def test_mss_extreme_always_precedes_its_own_mss_bar():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    pip = cfg.legacy_windows()["pip"]
    tables = events_report.build_events_table(df, d, sessions_cfg, pip)
    mss = tables["mss"]
    if len(mss):
        assert (mss["mss_idx"] > mss["extreme_idx"]).all()
        assert (mss["bars_from_sweep"] == mss["mss_idx"] - mss["extreme_idx"]).all()


def test_descriptive_stats_are_json_safe_and_rates_in_0_1():
    df, d = _build_day_and_bars()
    sessions_cfg = cfg.sessions()
    pip = cfg.legacy_windows()["pip"]
    tables = events_report.build_events_table(df, d, sessions_cfg, pip)
    stats = events_report.descriptive_stats(tables)
    assert "fvg" in stats and "raids" in stats and "sweep_to_mss_conversion" in stats
    if stats["fvg"].get("n"):
        for key in ("first_touch_rate", "ce_touch_rate", "full_fill_rate", "invalidated_rate"):
            rate = stats["fvg"][key]
            assert 0.0 <= rate <= 1.0
    conv = stats["sweep_to_mss_conversion"]["rate"]
    assert np.isnan(conv) or (0.0 <= conv <= 1.0)


def test_save_writes_four_parquet_files(tmp_path):
    df, d = _build_day_and_bars(n_days=15, seed=11)
    sessions_cfg = cfg.sessions()
    pip = cfg.legacy_windows()["pip"]
    tables = events_report.build_events_table(df, d, sessions_cfg, pip)
    events_report.save(tables, str(tmp_path))
    for name in ("fvg", "raids", "mss", "order_blocks"):
        p = tmp_path / f"events_{name}.parquet"
        assert p.exists()
        reloaded = pd.read_parquet(p)
        assert len(reloaded) == len(tables[name])
