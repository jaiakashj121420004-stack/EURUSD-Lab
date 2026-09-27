"""tests/test_backtest.py -- ROADMAP 7.4: the generic bar-by-bar backtest engine. Uses a tiny
fake Model (not a real ICT model -- those are tested in test_models_*.py) so the engine's own
mechanics (candidate-window restriction, one-trade-per-day, conservative same-bar fill via
nylab.replay.sim, time exit, cost handling) can be verified in isolation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import backtest


PIP = 0.0001


def _mk_day_bars(td, start_h, rows):
    n = len(rows)
    return pd.DataFrame({
        "td": [td] * n,
        "h": [start_h + i * (5 / 60) for i in range(n)],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    })


class _FixedSignalModel:
    """Fires exactly one long signal at the first candidate bar inside its window, every day."""
    name = "fixed_signal"
    version = "test"

    def __init__(self, window=(8.0, 10.0), time_exit=11.0, stop_offset=0.0010, target_offset=0.0020):
        self.params = {"window": window, "time_exit": time_exit}
        self.stop_offset = stop_offset
        self.target_offset = target_offset
        self.calls = []

    def signals(self, day_bars, day, events):
        self.calls.append(len(day_bars))
        entry = day_bars["close"].iloc[-1]
        return [backtest.Signal(
            bar_index=len(day_bars) - 1, side="long", entry_price=entry,
            stop_price=entry - self.stop_offset, target_price=entry + self.target_offset,
            time_exit_h=self.params["time_exit"],
        )]


def _mk_days_frame(tds):
    return pd.DataFrame(index=pd.DatetimeIndex(tds, name="td"))


def test_engine_only_calls_signals_inside_the_declared_window():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1001)] * 40  # 40 bars spanning h=7.0..10.25
    day_bars = _mk_day_bars(td, 7.0, rows)
    model = _FixedSignalModel(window=(8.0, 8.5))
    d = _mk_days_frame([td])
    trades = backtest.run_backtest(model, day_bars, d, PIP, cost_pips_default=1.0, one_trade_per_day=True)
    # window (8.0, 8.5) at 5-min bars starting h=7.0 covers positions 12..17 (6 candidate bars),
    # but one_trade_per_day means the engine stops asking once the first signal fires.
    assert len(model.calls) == 1
    assert len(trades) == 1


def test_engine_applies_conservative_stop_wins_rule_when_both_touched_same_bar():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 5
    # bar AFTER the signal bar touches both stop (entry-0.0010) and target (entry+0.0020) --
    # nylab.replay.sim.check_bar must resolve this as a STOP (conservative: stop wins).
    rows.append((1.1000, 1.1025, 1.0985, 1.1005))
    rows += [(1.1000, 1.1002, 1.0998, 1.1000)] * 3
    day_bars = _mk_day_bars(td, 8.0, rows)
    model = _FixedSignalModel(window=(8.0, 8.1), time_exit=11.0)
    d = _mk_days_frame([td])
    trades = backtest.run_backtest(model, day_bars, d, PIP, cost_pips_default=1.0)
    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["reason"] == "stop"
    assert row["exit"] == pytest.approx(row["stop"])


def test_engine_exits_at_close_on_time_exit_when_neither_stop_nor_target_hit():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 20  # never touches +-0.0010/0.0020 from entry
    day_bars = _mk_day_bars(td, 8.0, rows)
    model = _FixedSignalModel(window=(8.0, 8.1), time_exit=9.0)  # forces an early flat
    d = _mk_days_frame([td])
    trades = backtest.run_backtest(model, day_bars, d, PIP, cost_pips_default=1.0)
    assert len(trades) == 1
    assert trades.iloc[0]["reason"] == "time"


def test_engine_produces_one_trade_per_day_across_multiple_days():
    tds = [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 10
    frames = [_mk_day_bars(td, 8.0, rows) for td in tds]
    df = pd.concat(frames, ignore_index=True)
    model = _FixedSignalModel(window=(8.0, 8.5))
    d = _mk_days_frame(tds)
    trades = backtest.run_backtest(model, df, d, PIP, cost_pips_default=1.0)
    assert len(trades) == 2
    assert sorted(trades["td"].tolist()) == sorted(tds)


def test_cost_pips_uses_spread_column_when_present_and_higher_than_default():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 10
    day_bars = _mk_day_bars(td, 8.0, rows)
    day_bars["spread_pts"] = 30.0  # 3.0 pips (divide by 10) -- much bigger than default_cost=1.0
    model = _FixedSignalModel(window=(8.0, 8.1), time_exit=9.0)
    d = _mk_days_frame([td])
    trades = backtest.run_backtest(model, day_bars, d, PIP, cost_pips_default=1.0)
    assert len(trades) == 1
    assert trades.iloc[0]["cost_R"] > 0


def test_run_backtest_with_context_filter_splits_trades_filtered_vs_complement():
    tds = [pd.Timestamp("2024-01-0%d" % i) for i in (2, 3, 4, 5)]
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 10
    frames = [_mk_day_bars(td, 8.0, rows) for td in tds]
    df = pd.concat(frames, ignore_index=True)
    model = _FixedSignalModel(window=(8.0, 8.5))
    d = _mk_days_frame(tds)
    # dow: 2024-01-02=Tue(1), 03=Wed(2), 04=Thu(3), 05=Fri(4) -- filter picks out Tue/Wed.
    d["dow"] = d.index.dayofweek
    result = backtest.run_backtest_with_context_filter(
        model, df, d, PIP, cost_pips_default=1.0, context_filter="dow <= 2")
    assert set(result.keys()) == {"unfiltered", "filtered", "complement"}
    unf_trades, unf_stats = result["unfiltered"]
    filt_trades, filt_stats = result["filtered"]
    comp_trades, comp_stats = result["complement"]
    assert len(unf_trades) == 4
    assert unf_stats["n"] == 4
    assert set(filt_trades["td"]) == {tds[0], tds[1]}
    assert set(comp_trades["td"]) == {tds[2], tds[3]}
    assert filt_stats["n"] == 2 and comp_stats["n"] == 2
    # filtered + complement must partition unfiltered exactly, no trade dropped or duplicated.
    assert len(filt_trades) + len(comp_trades) == len(unf_trades)


def test_run_backtest_with_context_filter_none_returns_same_trades_in_all_three_buckets():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 10
    day_bars = _mk_day_bars(td, 8.0, rows)
    model = _FixedSignalModel(window=(8.0, 8.5))
    d = _mk_days_frame([td])
    result = backtest.run_backtest_with_context_filter(model, day_bars, d, PIP, cost_pips_default=1.0,
                                                         context_filter=None)
    pd.testing.assert_frame_equal(result["unfiltered"][0], result["filtered"][0])
    pd.testing.assert_frame_equal(result["unfiltered"][0], result["complement"][0])


def test_run_backtest_with_context_filter_handles_zero_trades_gracefully():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 10
    day_bars = _mk_day_bars(td, 8.0, rows)
    model = _FixedSignalModel(window=(20.0, 21.0))  # window never hit -- zero trades
    d = _mk_days_frame([td])
    d["dow"] = d.index.dayofweek
    result = backtest.run_backtest_with_context_filter(model, day_bars, d, PIP, cost_pips_default=1.0,
                                                         context_filter="dow <= 2")
    for key in ("unfiltered", "filtered", "complement"):
        trades, r_stats = result[key]
        assert len(trades) == 0
        assert r_stats["n"] == 0
