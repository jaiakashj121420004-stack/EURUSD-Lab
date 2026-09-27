"""tests/test_models_london_sweep_reversal.py -- ROADMAP 7.5: proves the new Model-plugin form
of london_sweep_reversal (run through nylab.backtest's generic engine) produces the SAME trades
as the original ad hoc backtest() function `nylab run` still calls for the Phase 1 report. This
IS the "look-ahead test proving equivalence" ARCHITECTURE.md S4 asks for before letting a model
compute anything other than the engine's own safe bar-by-bar walk -- here it's the other
direction (an existing verbatim implementation being ported ONTO the safe engine), but the bar
is the same: identical numbers, not just "close enough"."""
from __future__ import annotations

import pandas as pd
import pytest

from nylab import backtest, config as cfg, days as days_mod
from nylab.data import loader, timezones
from nylab.models import london_sweep_reversal as lsr


def _real_bars_and_days(csv_path="tests/fixtures/EURUSD_M5_synth_clean_2y.csv"):
    raw = loader.load_bars(csv_path)
    raw["ny"] = timezones.to_new_york(raw["server"], "ny+7")
    raw["td"] = (raw["ny"] + pd.Timedelta(hours=7)).dt.normalize()
    raw["h"] = (raw["ny"] - (raw["td"] - pd.Timedelta(hours=7))).dt.total_seconds() / 3600.0 - 7
    raw = raw[raw["td"].dt.dayofweek < 5].reset_index(drop=True)
    windows = cfg.legacy_windows()
    d = days_mod.build_days(raw, windows)
    return raw, d, windows["pip"]


@pytest.fixture(scope="module")
def real_data():
    return _real_bars_and_days()


def test_model_plugin_matches_ad_hoc_backtest_trade_for_trade(real_data):
    df, d, pip = real_data
    model_cfg = cfg.load_model("london_sweep_reversal")
    costs = cfg.load_costs()
    params = dict(model_cfg.params)
    params["default_cost_pips"] = costs.default_cost_pips

    old_trades = lsr.backtest(df, d, pip, params)

    engine_params = dict(params)
    engine_params["pip"] = pip
    model = lsr.LondonSweepReversalModel(engine_params)
    new_trades = backtest.run_backtest(model, df, d, pip, costs.default_cost_pips)

    assert len(old_trades) > 50, "sanity: the fixture should produce a meaningful number of trades"
    assert len(old_trades) == len(new_trades)

    old_sorted = old_trades.sort_values("td").reset_index(drop=True)
    new_sorted = new_trades.sort_values("td").reset_index(drop=True)

    pd.testing.assert_series_equal(old_sorted["td"], new_sorted["td"], check_names=False)
    pd.testing.assert_series_equal(old_sorted["side"], new_sorted["side"], check_names=False)
    for col in ("entry", "stop", "target", "exit", "risk_pips"):
        pd.testing.assert_series_equal(old_sorted[col].astype(float), new_sorted[col].astype(float),
                                        check_names=False, atol=1e-9, rtol=0)
    for col in ("R_gross", "R_net"):
        pd.testing.assert_series_equal(old_sorted[col].astype(float), new_sorted[col].astype(float),
                                        check_names=False, atol=1e-6, rtol=0)
