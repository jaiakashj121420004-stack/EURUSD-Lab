"""ROADMAP 7.6: nylab.regime -- adr_ratio/er10/adx14_d1/chop14_d1/realized_vol_pct + tercile()."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import regime


def _mk_daily(n, seed=0):
    """A synthetic daily OHLC series with a mix of trend and chop -- enough days for ADX(14)/
    CHOP(14)/a 126-day vol-percentile lookback to all warm up and produce non-NaN tails."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    close = 1.1000 + np.cumsum(rng.normal(0, 0.0020, n))
    high = close + rng.uniform(0.0005, 0.0030, n)
    low = close - rng.uniform(0.0005, 0.0030, n)
    open_ = close - rng.normal(0, 0.0010, n)
    d = pd.DataFrame({"day_open": open_, "day_high": high, "day_low": low, "day_close": close}, index=idx)
    pip = 0.0001
    d["day_range"] = (d["day_high"] - d["day_low"]) / pip
    d["adr5"] = d["day_range"].shift(1).rolling(5).mean()
    d["adr20"] = d["day_range"].shift(1).rolling(20).mean()
    return d


REGIME_CFG = dict(er10_days=10, adx14_period=14, chop14_period=14,
                   realized_vol_window_days=20, realized_vol_pctile_lookback_days=126)


def test_column_docs_registers_all_five_at_h_minus_7():
    docs = regime.column_docs()
    assert set(docs) == {"adr_ratio", "er10", "adx14_d1", "chop14_d1", "realized_vol_pct"}
    assert all(v == -7.0 for v in docs.values())


def test_add_regime_features_adds_all_five_columns_and_warms_up_to_non_nan():
    d = _mk_daily(200)
    out = regime.add_regime_features(d, REGIME_CFG)
    for col in ("adr_ratio", "er10", "adx14_d1", "chop14_d1", "realized_vol_pct"):
        assert col in out.columns
        assert out[col].notna().sum() > 0, f"{col} never warms up to a non-NaN value"


def test_adr_ratio_matches_manual_division_of_adr5_adr20():
    d = _mk_daily(60)
    out = regime.add_regime_features(d, REGIME_CFG)
    expected = d["adr5"] / d["adr20"]
    pd.testing.assert_series_equal(out["adr_ratio"], expected, check_names=False)


def test_regime_columns_use_only_previous_completed_days_no_lookahead():
    """Truncation test (ROADMAP 7 accept criterion: 'truncation tests for every feature'):
    changing today's OWN high/low/close must NOT change today's regime feature values -- if it
    did, the feature would be leaking same-day information forward of h=-7."""
    d = _mk_daily(200)
    out_a = regime.add_regime_features(d, REGIME_CFG)

    d2 = d.copy()
    last = d2.index[-1]
    d2.loc[last, "day_high"] += 0.05  # a huge, obviously-detectable same-day move
    d2.loc[last, "day_low"] -= 0.05
    d2.loc[last, "day_close"] += 0.03
    d2.loc[last, "day_range"] = (d2.loc[last, "day_high"] - d2.loc[last, "day_low"]) / 0.0001
    out_b = regime.add_regime_features(d2, REGIME_CFG)

    for col in ("adr_ratio", "er10", "adx14_d1", "chop14_d1", "realized_vol_pct"):
        va, vb = out_a[col].iloc[-1], out_b[col].iloc[-1]
        if pd.isna(va) and pd.isna(vb):
            continue
        assert va == pytest.approx(vb, nan_ok=True), f"{col} changed when only TODAY's bar changed"


def test_er10_matches_manual_formula():
    d = _mk_daily(40)
    pip = 0.0001
    out = regime.add_regime_features(d, REGIME_CFG, pip=pip)
    i = 25
    net_move_pips = abs(d["day_close"].iloc[i - 1] - d["day_close"].iloc[i - 11]) / pip
    sum_ranges = d["day_range"].shift(1).iloc[i - 9: i + 1].sum()
    expected = net_move_pips / sum_ranges
    assert out["er10"].iloc[i] == pytest.approx(expected)


def test_adx14_and_chop14_are_finite_and_in_expected_ranges_once_warmed_up():
    d = _mk_daily(150)
    out = regime.add_regime_features(d, REGIME_CFG)
    adx_tail = out["adx14_d1"].dropna()
    chop_tail = out["chop14_d1"].dropna()
    assert len(adx_tail) > 0 and len(chop_tail) > 0
    assert (adx_tail >= 0).all() and (adx_tail <= 100).all()
    assert (chop_tail >= 0).all() and (chop_tail <= 100).all()


def test_realized_vol_pct_is_a_percentile_0_to_100():
    d = _mk_daily(200)
    out = regime.add_regime_features(d, REGIME_CFG)
    tail = out["realized_vol_pct"].dropna()
    assert len(tail) > 0
    assert (tail >= 0).all() and (tail <= 100).all()


def test_tercile_buckets_into_three_roughly_equal_low_mid_high_groups():
    s = pd.Series(np.arange(300, dtype=float))
    buckets = regime.tercile(s)
    counts = buckets.value_counts()
    assert set(counts.index) == {"low", "mid", "high"}
    assert counts.min() >= 90  # roughly 100 each, allow qcut edge slack


def test_tercile_handles_too_few_values_gracefully():
    s = pd.Series([1.0, np.nan])
    out = regime.tercile(s)
    assert out.isna().all()
