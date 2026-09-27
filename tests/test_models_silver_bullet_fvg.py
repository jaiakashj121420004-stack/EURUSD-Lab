"""tests/test_models_silver_bullet_fvg.py -- ROADMAP 7.5. Unit-tests the model's OWN retracement/
entry logic against a hand-built mss/fvg events dict (bypassing full event detection, the same
way tests/test_backtest.py unit-tests the engine against a fake model) -- isolates "does this
model correctly turn an MSS+FVG into a signal" from "does the whole detection pipeline agree".
A separate real-data smoke test proves the full pipeline (detect_mss -> fvg_lifecycle -> this
model -> the generic engine) runs end to end without crashing on real-shaped data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import backtest, config as cfg, days as days_mod, events as events_mod, events_report
from nylab.data import loader, timezones
from nylab.models.silver_bullet_fvg import SilverBulletFVGModel

PIP = 0.0001


def _mk_day_bars(td, start_h, rows):
    n = len(rows)
    idx = pd.RangeIndex(100, 100 + n)  # nonzero global offset, exercises index-based lookups
    return pd.DataFrame({
        "td": [td] * n, "h": [start_h + i * (5 / 60) for i in range(n)],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    }, index=idx)


def test_fires_short_on_retracement_into_bearish_leg_fvg_after_bearish_mss():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.0010, 1.0012, 1.0008, 1.0009)] * 10  # bars 100-109, h=3.0..3.75
    day_bars = _mk_day_bars(td, 3.0, rows)
    mss = pd.DataFrame([dict(td=td, direction="bearish", extreme_idx=100, extreme_h=3.0,
                              mss_idx=103, mss_level=1.0000, leg_fvgs=[104])])
    fvg = pd.DataFrame([dict(bar_idx=104, direction="bear", top=1.0010, bottom=1.0005, ce=1.00075)])
    params = dict(window=(3.0, 4.0), entry_max_bars_after_mss=12, stop_buffer_pips=1.0, rr=2.0,
                  time_exit=4.0, pip=PIP)
    model = SilverBulletFVGModel("silver_bullet_fvg_lonsb", params)

    day = pd.Series({}, name=td)
    # Simulate the engine calling signals() progressively; only the bar whose high finally
    # reaches ce (1.00075) should produce a signal.
    for i in range(4, 10):  # positions AFTER the mss_idx (103 -> local index 3)
        partial = day_bars.iloc[: i + 1]
        sigs = model.signals(partial, day, {"mss": mss, "fvg": fvg})
        if partial["high"].iloc[-1] >= 1.00075:
            assert len(sigs) == 1
            row = sigs[0]
            assert row.side == "short"
            assert row.entry_price == pytest.approx(1.00075)
            assert row.stop_price == pytest.approx(1.0010 + 0.0001)  # top + 1 pip buffer
            break
        else:
            assert sigs == []
    else:
        pytest.fail("no bar in the fixture ever reached ce -- fixture bug")


def test_no_signal_when_mss_has_no_leg_fvg():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.0010, 1.0012, 1.0008, 1.0009)] * 10
    day_bars = _mk_day_bars(td, 3.0, rows)
    mss = pd.DataFrame([dict(td=td, direction="bearish", extreme_idx=100, extreme_h=3.0,
                              mss_idx=103, mss_level=1.0000, leg_fvgs=[])])
    params = dict(window=(3.0, 4.0), entry_max_bars_after_mss=12, stop_buffer_pips=1.0, rr=2.0,
                  time_exit=4.0, pip=PIP)
    model = SilverBulletFVGModel("silver_bullet_fvg_lonsb", params)
    day = pd.Series({}, name=td)
    for i in range(4, 10):
        sigs = model.signals(day_bars.iloc[: i + 1], day, {"mss": mss, "fvg": pd.DataFrame()})
        assert sigs == []


def test_no_signal_when_retracement_window_expires():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.0010, 1.0012, 1.0008, 1.0009)] * 20  # never touches ce
    day_bars = _mk_day_bars(td, 3.0, rows)
    mss = pd.DataFrame([dict(td=td, direction="bearish", extreme_idx=100, extreme_h=3.0,
                              mss_idx=103, mss_level=1.0000, leg_fvgs=[104])])
    fvg = pd.DataFrame([dict(bar_idx=104, direction="bear", top=1.0030, bottom=1.0025, ce=1.00275)])
    params = dict(window=(3.0, 4.0), entry_max_bars_after_mss=3, stop_buffer_pips=1.0, rr=2.0,
                  time_exit=4.0, pip=PIP)
    model = SilverBulletFVGModel("silver_bullet_fvg_lonsb", params)
    day = pd.Series({}, name=td)
    for i in range(4, 20):
        sigs = model.signals(day_bars.iloc[: i + 1], day, {"mss": mss, "fvg": fvg})
        assert sigs == []


def test_no_signal_when_no_mss_at_all():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.0010, 1.0012, 1.0008, 1.0009)] * 10
    day_bars = _mk_day_bars(td, 3.0, rows)
    params = dict(window=(3.0, 4.0), entry_max_bars_after_mss=12, stop_buffer_pips=1.0, rr=2.0,
                  time_exit=4.0, pip=PIP)
    model = SilverBulletFVGModel("silver_bullet_fvg_lonsb", params)
    day = pd.Series({}, name=td)
    sigs = model.signals(day_bars, day, {"mss": pd.DataFrame(), "fvg": pd.DataFrame()})
    assert sigs == []


@pytest.mark.parametrize("model_name", [
    "silver_bullet_fvg_lonsb", "silver_bullet_fvg_nyamsb", "silver_bullet_fvg_nypmsb",
])
def test_full_pipeline_runs_end_to_end_on_real_fixture_without_crashing(model_name):
    raw = loader.load_bars("tests/fixtures/EURUSD_M5_synth_clean_2y.csv")
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    windows_cfg = cfg.legacy_windows()
    d = days_mod.build_days(raw, windows_cfg)
    sessions_cfg = cfg.sessions()
    pip = windows_cfg["pip"]

    tables = events_report.build_events_table(raw, d, sessions_cfg, pip)
    model_cfg = cfg.load_model(model_name)
    params = dict(model_cfg.params)
    params["pip"] = pip
    model = SilverBulletFVGModel(model_name, params)
    trades = backtest.run_backtest(model, raw, d, pip, cost_pips_default=1.0,
                                    events={"mss": tables["mss"], "fvg": tables["fvg"]})
    # Not asserting an exact count (real-shaped synthetic data, not a golden fixture) -- just
    # that the whole chain runs, and any trades it DOES find have sane risk/R numbers.
    assert isinstance(trades, pd.DataFrame)
    if len(trades):
        assert (trades["risk_pips"] > 0).all()
        assert trades["R_net"].abs().max() < 50  # sanity bound, not a tuned threshold
