"""ROADMAP 8.3: nylab.report.robustness_section -- HTML rendering of the robustness battery."""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import backtest, robustness
from nylab.report import robustness_section

PIP = 0.0001


def _mk_day_bars(td, start_h, rows):
    n = len(rows)
    server = [td + pd.Timedelta(hours=start_h + 7 + i * (5 / 60)) for i in range(n)]
    return pd.DataFrame({
        "td": [td] * n, "h": [start_h + i * (5 / 60) for i in range(n)], "server": server,
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    })


class _FixedSignalModel:
    name, version = "fixed", "test"

    def __init__(self, window=(7.0, 7.5)):
        self.params = {"window": window, "time_exit": 11.0}

    def signals(self, day_bars, day, events):
        entry = day_bars["close"].iloc[-1]
        return [backtest.Signal(bar_index=len(day_bars) - 1, side="long", entry_price=entry,
                                 stop_price=entry - 0.0010, target_price=entry + 0.0020, time_exit_h=11.0)]


def _mk_df_and_d(n_days, seed=0):
    rng = np.random.default_rng(seed)
    tds = pd.bdate_range("2023-01-02", periods=n_days)
    frames, day_ranges = [], {}
    for td in tds:
        n = 40
        base = 1.1000 + rng.normal(0, 0.0003)
        closes = base + np.cumsum(rng.normal(0, 0.0004, n))
        highs = closes + rng.uniform(0.0002, 0.0008, n)
        lows = closes - rng.uniform(0.0002, 0.0008, n)
        opens = np.roll(closes, 1); opens[0] = base
        rows = list(zip(opens, highs, lows, closes))
        frames.append(_mk_day_bars(td, 7.0, rows))
        day_ranges[td] = (highs.max() - lows.min()) / PIP
    df = pd.concat(frames, ignore_index=True)
    d = pd.DataFrame(index=pd.DatetimeIndex(tds, name="td"))
    d["day_range"] = pd.Series(day_ranges)
    return df, d


def test_build_renders_all_six_sections_without_crashing():
    df, d = _mk_df_and_d(40)
    result = robustness.run_robustness_battery(lambda: _FixedSignalModel(), df, d, PIP,
                                                cost_pips_default=1.0, n_shuffles=100, seed=1)
    html = robustness_section.build(result)
    for heading in ("Robustness battery", "Cost stress and entry-delay", "Per-year contribution",
                    "Remove best 5% of trades", "Monte Carlo", "Thin/gappy days"):
        assert heading in html


def test_build_handles_zero_trades_without_crashing():
    df, d = _mk_df_and_d(10)

    class _NeverFires(_FixedSignalModel):
        def signals(self, day_bars, day, events):
            return []

    result = robustness.run_robustness_battery(lambda: _NeverFires(), df, d, PIP,
                                                cost_pips_default=1.0, n_shuffles=50, seed=1)
    html = robustness_section.build(result)
    assert "No trades" in html
