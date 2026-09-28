"""ROADMAP 8.3: nylab.robustness -- the 6-check robustness battery."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import backtest, robustness

PIP = 0.0001


def _mk_day_bars(td, start_h, rows):
    n = len(rows)
    server = [td + pd.Timedelta(hours=start_h + 7 + i * (5 / 60)) for i in range(n)]
    return pd.DataFrame({
        "td": [td] * n,
        "h": [start_h + i * (5 / 60) for i in range(n)],
        "server": server,
        "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
    })


class _FixedSignalModel:
    name, version = "fixed", "test"

    def __init__(self, window=(8.0, 8.5), time_exit=11.0, stop_offset=0.0010, target_offset=0.0020):
        self.params = {"window": window, "time_exit": time_exit}
        self.stop_offset, self.target_offset = stop_offset, target_offset

    def signals(self, day_bars, day, events):
        entry = day_bars["close"].iloc[-1]
        return [backtest.Signal(bar_index=len(day_bars) - 1, side="long", entry_price=entry,
                                 stop_price=entry - self.stop_offset, target_price=entry + self.target_offset,
                                 time_exit_h=self.params["time_exit"])]


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


def test_cost_stress_scales_the_incurred_cost_not_the_gross_pnl():
    trades = pd.DataFrame({"R_gross": [1.0, -1.0, 2.0], "cost_R": [0.1, 0.1, 0.1]})
    out = robustness.cost_stress(trades, 2.0)
    expected = trades["R_gross"] - 2.0 * trades["cost_R"]
    assert out["expectancy"] == pytest.approx(expected.mean())


def test_cost_stress_handles_empty_trades():
    out = robustness.cost_stress(pd.DataFrame(columns=["R_gross", "cost_R"]), 1.5)
    assert out["n"] == 0


def test_delayed_entry_model_shifts_entry_price_to_a_later_bar_same_stop_target():
    td = pd.Timestamp("2024-01-02")
    rows = [(1.1000, 1.1002, 1.0998, 1.1000 + i * 0.0001) for i in range(10)]
    day_bars = _mk_day_bars(td, 8.0, rows)
    inner = _FixedSignalModel(window=(8.0, 8.5))
    wrapped = robustness.DelayedEntryModel(inner, delay_bars=1)
    d = pd.DataFrame(index=pd.DatetimeIndex([td], name="td"))
    d["day_range"] = 50.0
    trades = backtest.run_backtest(wrapped, day_bars, d, PIP, cost_pips_default=1.0)
    assert len(trades) == 1
    # inner model would enter at bar 0's close (1.1000); delayed-by-1 model enters at bar 1's close.
    assert trades.iloc[0]["entry"] == pytest.approx(1.1001)


def test_delayed_entry_model_preserves_name_version_params():
    inner = _FixedSignalModel()
    wrapped = robustness.DelayedEntryModel(inner, delay_bars=1)
    assert wrapped.name == inner.name and wrapped.version == inner.version and wrapped.params is inner.params


def test_per_year_contribution_flags_a_dominant_year():
    trades = pd.DataFrame({
        "td": [pd.Timestamp("2023-06-01"), pd.Timestamp("2023-06-02"), pd.Timestamp("2024-06-01")],
        "R_net": [10.0, 10.0, 1.0],
    })
    out = robustness.per_year_contribution(trades)
    row_2023 = out[out["year"] == 2023].iloc[0]
    assert row_2023["flag_over_50pct"]
    assert row_2023["share_of_total_R"] == pytest.approx(20.0 / 21.0)


def test_per_year_contribution_empty_trades():
    out = robustness.per_year_contribution(pd.DataFrame(columns=["td", "R_net"]))
    assert len(out) == 0
    assert list(out.columns) == ["year", "n", "total_R", "share_of_total_R", "flag_over_50pct"]


def test_remove_best_n_pct_drops_the_biggest_winners():
    trades = pd.DataFrame({"R_net": [10.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0]})
    out = robustness.remove_best_n_pct(trades, pct=0.1)  # drops the single +10 trade
    assert out["n"] == 9
    assert out["expectancy"] == pytest.approx(-1.0)


def test_monte_carlo_shuffle_deterministic_with_seed_and_sane_ranges():
    rng = np.random.default_rng(42)
    trades = pd.DataFrame({"R_net": rng.normal(0.1, 1.0, 60)})
    out1 = robustness.monte_carlo_shuffle(trades, n_shuffles=500, seed=7)
    out2 = robustness.monte_carlo_shuffle(trades, n_shuffles=500, seed=7)
    assert out1 == out2  # same seed -> identical result
    assert out1["n_trades"] == 60
    assert out1["max_dd_p95"] >= 0
    assert 0.0 <= out1["p_losing_streak"] <= 1.0


def test_monte_carlo_shuffle_empty_trades():
    out = robustness.monte_carlo_shuffle(pd.DataFrame(columns=["R_net"]), n_shuffles=10)
    assert out["n_trades"] == 0
    assert np.isnan(out["max_dd_p95"])


def test_monte_carlo_shuffle_detects_guaranteed_losing_streak():
    # 25 consecutive losses guarantee a 20-trade losing streak in EVERY shuffle order (shuffling
    # a list of all-identical-sign values can't break up the streak).
    trades = pd.DataFrame({"R_net": [-1.0] * 25})
    out = robustness.monte_carlo_shuffle(trades, n_shuffles=200, losing_streak_len=20, seed=1)
    assert out["p_losing_streak"] == 1.0


def test_thin_gappy_check_excludes_flagged_days():
    tds = pd.bdate_range("2024-01-01", periods=5)
    trades = pd.DataFrame({"td": tds, "R_net": [1.0, -1.0, 2.0, -2.0, 0.5]})
    quality_flags = pd.DataFrame({"thin_day": [True, False, False, False, False],
                                   "gappy": [False, False, True, False, False]}, index=tds)
    out = robustness.thin_gappy_check(trades, quality_flags)
    assert out["n_thin_or_gappy_days_removed"] == 2
    assert out["excluded"]["n"] == 3
    assert out["included"]["n"] == 5


def test_thin_gappy_check_empty_trades():
    out = robustness.thin_gappy_check(pd.DataFrame(columns=["td", "R_net"]), pd.DataFrame(columns=["thin_day", "gappy"]))
    assert out["n_thin_or_gappy_days_removed"] == 0


def test_run_robustness_battery_end_to_end_returns_all_keys_and_sane_shapes():
    df, d = _mk_df_and_d(80)
    result = robustness.run_robustness_battery(
        lambda: _FixedSignalModel(window=(7.0, 7.5)), df, d, PIP, cost_pips_default=1.0,
        n_shuffles=200, seed=3)
    for key in ("baseline_stats", "baseline_trades", "cost_x1_5", "cost_x2",
                "entry_delay_1bar_stats", "entry_delay_1bar_trades", "per_year",
                "remove_best_5pct_stats", "monte_carlo", "thin_gappy"):
        assert key in result
    assert result["baseline_stats"]["n"] == 80  # fires every day, one_trade_per_day default True
    # cost x2 expectancy must be <= cost x1.5 expectancy <= baseline (more cost never helps).
    assert result["cost_x2"]["expectancy"] <= result["cost_x1_5"]["expectancy"] <= result["baseline_stats"]["expectancy"]
    assert result["monte_carlo"]["n_trades"] == 80
    assert len(result["per_year"]) >= 1


def test_run_robustness_battery_handles_zero_trades_gracefully():
    df, d = _mk_df_and_d(10)

    class _NeverFires(_FixedSignalModel):
        def signals(self, day_bars, day, events):
            return []

    result = robustness.run_robustness_battery(lambda: _NeverFires(), df, d, PIP, cost_pips_default=1.0,
                                                n_shuffles=50, seed=1)
    assert result["baseline_stats"]["n"] == 0
    assert result["cost_x1_5"]["n"] == 0
    assert result["monte_carlo"]["n_trades"] == 0
