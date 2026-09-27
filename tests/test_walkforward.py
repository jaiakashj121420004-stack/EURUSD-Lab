"""ROADMAP 7.7: nylab.walkforward -- rolling/expanding walk-forward fold splitting + evaluation."""
from __future__ import annotations

import pandas as pd
import pytest

from nylab import backtest, walkforward

PIP = 0.0001


def _mk_day_bars(td, start_h, rows):
    n = len(rows)
    return pd.DataFrame({
        "td": [td] * n,
        "h": [start_h + i * (5 / 60) for i in range(n)],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    })


class _AlwaysFiresModel:
    """Fires one long signal on the first candidate bar every day -- deterministic, state-free
    (aside from a call counter used to verify fresh-instance-per-fold), for exercising the fold
    machinery itself rather than any real ICT logic."""
    name = "always_fires"
    version = "test"

    def __init__(self, window=(8.0, 8.5), time_exit=9.0):
        self.params = {"window": window, "time_exit": time_exit}
        self.instance_signal_count = 0

    def signals(self, day_bars, day, events):
        self.instance_signal_count += 1
        entry = day_bars["close"].iloc[-1]
        return [backtest.Signal(bar_index=len(day_bars) - 1, side="long", entry_price=entry,
                                 stop_price=entry - 0.0010, target_price=entry + 0.0020,
                                 time_exit_h=self.params["time_exit"])]


def _mk_df_and_d(n_days, start=pd.Timestamp("2024-01-01")):
    tds = pd.bdate_range(start, periods=n_days)
    rows = [(1.1000, 1.1002, 1.0998, 1.1000)] * 10
    frames = [_mk_day_bars(td, 8.0, rows) for td in tds]
    df = pd.concat(frames, ignore_index=True)
    d = pd.DataFrame(index=pd.DatetimeIndex(tds, name="td"))
    return df, d


def test_make_folds_rolling_widths_and_non_overlap():
    idx = pd.bdate_range("2024-01-01", periods=50)
    folds = walkforward.make_folds(idx, is_days=10, oos_days=5, mode="rolling")
    assert len(folds) == 8  # (50-10)//5 = 8
    for i, f in enumerate(folds):
        is_span = pd.bdate_range(f["is_start"], f["is_end"])
        assert len(is_span) == 10  # fixed-width IS in rolling mode
        oos_span = pd.bdate_range(f["oos_start"], f["oos_end"])
        assert len(oos_span) == 5
        assert f["oos_start"] > f["is_end"]
        if i > 0:
            # consecutive folds: this fold's OOS starts exactly where the previous one's ended
            # (no gap, no overlap between fold i-1's OOS and fold i's IS).
            assert f["is_end"] == folds[i - 1]["oos_end"]
            prev_is_start_pos = idx.get_loc(folds[i - 1]["is_start"])
            this_is_start_pos = idx.get_loc(f["is_start"])
            assert this_is_start_pos - prev_is_start_pos == 5  # slides forward by oos_days


def test_make_folds_expanding_is_window_grows_and_always_starts_at_day_0():
    idx = pd.bdate_range("2024-01-01", periods=50)
    folds = walkforward.make_folds(idx, is_days=10, oos_days=5, mode="expanding")
    assert len(folds) == 8
    widths = []
    for f in folds:
        assert f["is_start"] == idx[0]
        widths.append(len(pd.bdate_range(f["is_start"], f["is_end"])))
    assert widths == sorted(widths)  # strictly non-decreasing IS width fold over fold
    assert widths[-1] > widths[0]


def test_make_folds_returns_empty_list_when_not_enough_history():
    idx = pd.bdate_range("2024-01-01", periods=10)
    assert walkforward.make_folds(idx, is_days=20, oos_days=5) == []


def test_make_folds_rejects_unknown_mode():
    idx = pd.bdate_range("2024-01-01", periods=50)
    with pytest.raises(ValueError):
        walkforward.make_folds(idx, is_days=10, oos_days=5, mode="bogus")


def test_run_walkforward_produces_one_result_per_fold_with_is_and_oos_stats():
    df, d = _mk_df_and_d(30)
    result = walkforward.run_walkforward(
        lambda: _AlwaysFiresModel(), df, d, PIP, cost_pips_default=1.0,
        is_days=10, oos_days=5, mode="rolling")
    folds = result["folds"]
    assert len(folds) == walkforward.make_folds(d.index, 10, 5, "rolling").__len__()
    for f in folds:
        assert len(f["is_trades"]) == 10  # one trade per IS day, model always fires
        assert len(f["oos_trades"]) == 5
        assert f["is_stats"]["n"] == 10
        assert f["oos_stats"]["n"] == 5


def test_run_walkforward_pools_oos_trades_across_all_folds():
    df, d = _mk_df_and_d(30)
    result = walkforward.run_walkforward(
        lambda: _AlwaysFiresModel(), df, d, PIP, cost_pips_default=1.0,
        is_days=10, oos_days=5, mode="rolling")
    n_folds = len(result["folds"])
    assert len(result["oos_pooled_trades"]) == n_folds * 5
    assert result["oos_pooled_stats"]["n"] == n_folds * 5


def test_run_walkforward_uses_a_fresh_model_instance_per_fold():
    df, d = _mk_df_and_d(30)
    instances = []

    def factory():
        m = _AlwaysFiresModel()
        instances.append(m)
        return m

    result = walkforward.run_walkforward(factory, df, d, PIP, cost_pips_default=1.0,
                                          is_days=10, oos_days=5, mode="rolling")
    assert len(instances) == len(result["folds"])
    # each fold's model only ever saw ITS OWN fold's days (IS+OOS = 15), never accumulated
    # across folds -- proves model state doesn't leak/carry over between folds.
    for inst in instances:
        assert inst.instance_signal_count == 15


def test_run_walkforward_no_bar_leakage_across_fold_boundaries():
    """A later fold's df/d slice must never include an earlier fold's IS-only days (rolling
    mode), and no fold may see days beyond its own oos_end."""
    df, d = _mk_df_and_d(30)
    result = walkforward.run_walkforward(
        lambda: _AlwaysFiresModel(), df, d, PIP, cost_pips_default=1.0,
        is_days=10, oos_days=5, mode="rolling")
    for f in result["folds"]:
        all_trade_days = pd.concat([f["is_trades"]["td"], f["oos_trades"]["td"]])
        assert (all_trade_days >= f["is_start"]).all()
        assert (all_trade_days <= f["oos_end"]).all()


def test_run_walkforward_handles_zero_trade_days_gracefully():
    df, d = _mk_df_and_d(30)

    class _NeverFiresModel(_AlwaysFiresModel):
        def signals(self, day_bars, day, events):
            self.instance_signal_count += 1
            return []

    result = walkforward.run_walkforward(
        lambda: _NeverFiresModel(), df, d, PIP, cost_pips_default=1.0,
        is_days=10, oos_days=5, mode="rolling")
    for f in result["folds"]:
        assert len(f["is_trades"]) == 0 and f["is_stats"]["n"] == 0
        assert len(f["oos_trades"]) == 0 and f["oos_stats"]["n"] == 0
    assert result["oos_pooled_stats"]["n"] == 0
