"""nylab.regime -- ROADMAP 7.6: daily regime features (FEATURES_SPEC.md S11, "Formula Handbook
Part 6"). All five columns (adr_ratio, er10, adx14_d1, chop14_d1, realized_vol_pct) are available
at h=-7 (same convention as nylab.days.build_days's own adr5/adr20) because every one of them is
built from PREVIOUS COMPLETED trading days only: the daily OHLC series (day_open/day_high/
day_low/day_close -- already NY 17:00-17:00 bars from nylab.days.window(df,-7,17,'day')) is used
to compute each raw daily indicator (ADX/Choppiness/realized-vol, a running series computed
day-over-day across the whole history so day i's OWN value only ever looks backward through day
i), and that raw indicator is then .shift(1)'d before being assigned onto `d` -- so
`d.loc[td, 'adx14_d1']` is literally YESTERDAY's ADX(14), fully settled before today's 00:00
candle even opens, exactly like `d['adr5']`/`d['adr20']` already are.

Config knobs come from config/features.yaml's `regime:` block (nylab.config.load_features()).
Kept as a separate module (not folded into nylab.days.build_days) so it can be tested and
run independently, and so build_days's own signature doesn't grow a regime_cfg parameter every
caller has to thread through -- callers that want these columns call add_regime_features(d, cfg)
right after build_days(df, C), same additive-join pattern as nylab.days.attach_calendar_features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ROADMAP 5.7.2/4.3 precedent: every DAY-table column has to be registered in
# nylab.days.COLUMN_DOCS (available_at_h) for nylab.hyp_loader's look-ahead check to know about
# it at all -- a hypothesis referencing an unregistered column is silently unchecked, not merely
# unavailable. All five columns here are -7 (see module docstring): known before the trading day
# even opens.
_AVAILABLE_AT_H = -7.0


def column_docs() -> dict:
    """nylab.days.COLUMN_DOCS.update(regime.column_docs()) registers all five columns at h=-7,
    mirroring nylab.calendar_features.column_docs()'s own registration pattern."""
    return {name: _AVAILABLE_AT_H for name in
            ("adr_ratio", "er10", "adx14_d1", "chop14_d1", "realized_vol_pct")}


def _wilder_ema(x: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (RMA): alpha=1/period. This is the classical recursive definition ADX/
    ATR/RSI all use -- NOT a plain EMA's alpha=2/(period+1), which would give different numbers."""
    return x.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _true_range(day_high: pd.Series, day_low: pd.Series, day_close: pd.Series) -> pd.Series:
    prev_close = day_close.shift(1)
    return pd.concat([
        day_high - day_low,
        (day_high - prev_close).abs(),
        (day_low - prev_close).abs(),
    ], axis=1).max(axis=1)


def _adx14(day_high: pd.Series, day_low: pd.Series, day_close: pd.Series, period: int) -> pd.Series:
    """Classic Wilder ADX on a daily OHLC series. Returns the RAW series indexed the same as the
    input (day i's own value already uses data through day i inclusive) -- callers wanting a
    look-ahead-safe value shift(1) the result themselves (see add_regime_features)."""
    tr = _true_range(day_high, day_low, day_close)
    up_move = day_high.diff()
    down_move = -day_low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=day_high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=day_high.index)

    atr = _wilder_ema(tr, period)
    plus_di = 100 * _wilder_ema(plus_dm, period) / atr
    minus_di = 100 * _wilder_ema(minus_dm, period) / atr
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return _wilder_ema(dx, period)


def _chop14(day_high: pd.Series, day_low: pd.Series, day_close: pd.Series, period: int) -> pd.Series:
    """Choppiness Index: 100*log10(sum(TR,period) / (max(High,period)-min(Low,period))) /
    log10(period). Conventionally >~61.8 reads "choppy/ranging", <~38.2 "trending" -- this
    function returns the raw value only; bucketing/thresholding is the caller's business."""
    tr = _true_range(day_high, day_low, day_close)
    sum_tr = tr.rolling(period).sum()
    range_hl = day_high.rolling(period).max() - day_low.rolling(period).min()
    return 100 * np.log10(sum_tr / range_hl) / np.log10(period)


def _pct_rank_last(window: np.ndarray) -> float:
    """% of the window's non-NaN values that are <= the window's LAST value (the "current"
    reading), scaled 0..100. Used as a rolling .apply so "today's" realized vol is ranked
    against its own trailing history -- a percentile, not a z-score, per FEATURES_SPEC S11."""
    cur = window[-1]
    if np.isnan(cur):
        return np.nan
    hist = window[~np.isnan(window)]
    if len(hist) < 2:
        return np.nan
    return float((hist <= cur).sum() - 1) / (len(hist) - 1) * 100.0


def _realized_vol_pct(day_close: pd.Series, vol_window: int, pctile_lookback: int) -> pd.Series:
    """Percentile rank of the trailing `vol_window`-day realized volatility (stdev of daily log
    returns) within the trailing `pctile_lookback`-day history of that same rolling-vol series."""
    log_ret = np.log(day_close / day_close.shift(1))
    realized_vol = log_ret.rolling(vol_window).std()
    return realized_vol.rolling(pctile_lookback, min_periods=2).apply(_pct_rank_last, raw=True)


def add_regime_features(d: pd.DataFrame, regime_cfg: dict, pip: float = 0.0001) -> pd.DataFrame:
    """Adds adr_ratio, er10, adx14_d1, chop14_d1, realized_vol_pct to the DAY table `d`
    (nylab.days.build_days's output; must already have adr5/adr20/day_range/day_high/day_low/
    day_close). `regime_cfg` is config/features.yaml's `regime:` block
    (nylab.config.load_features()['regime']); `pip` is config/features.yaml's top-level `pip`
    (nylab.config.load_features()['pip']) -- needed because `er10`'s numerator (a raw price
    difference) must be converted to the SAME pip units as its denominator (`day_range`, which
    nylab.days.build_days already stores in pips, not raw price) or the ratio comes out several
    orders of magnitude too small."""
    d = d.copy()

    # adr5/adr20 (nylab.days.build_days) are already `.shift(1)`'d -- available_at_h=-7 -- so
    # their ratio is too, with no further shift needed here.
    d["adr_ratio"] = d["adr5"] / d["adr20"]

    er_days = int(regime_cfg.get("er10_days", 10))
    # "codex variant: |net 10-day move| / sum of 10 daily ranges" (FEATURES_SPEC S11) -- built
    # from closes/ranges shift(1)'d first so the 10-day window is td-1 .. td-10, never today.
    net_move_pips = (d["day_close"].shift(1) - d["day_close"].shift(1 + er_days)).abs() / pip
    sum_ranges = d["day_range"].shift(1).rolling(er_days).sum()
    d["er10"] = net_move_pips / sum_ranges

    adx_period = int(regime_cfg.get("adx14_period", 14))
    d["adx14_d1"] = _adx14(d["day_high"], d["day_low"], d["day_close"], adx_period).shift(1)

    chop_period = int(regime_cfg.get("chop14_period", 14))
    d["chop14_d1"] = _chop14(d["day_high"], d["day_low"], d["day_close"], chop_period).shift(1)

    vol_window = int(regime_cfg.get("realized_vol_window_days", 20))
    pctile_lookback = int(regime_cfg.get("realized_vol_pctile_lookback_days", 126))
    d["realized_vol_pct"] = _realized_vol_pct(d["day_close"], vol_window, pctile_lookback).shift(1)

    return d


def tercile(s: pd.Series) -> pd.Series:
    """Buckets a numeric Series into 'low'/'mid'/'high' terciles by ITS OWN in-sample quantiles
    (pd.qcut(3)) -- FEATURES_SPEC S11: "bucket each into terciles for slicing results". This is
    for slicing ALREADY-COMPUTED results for a descriptive report (same in-sample-terciles
    convention RESEARCH_PROTOCOL.md's reporting uses elsewhere), NOT for use inside a hypothesis
    `condition` -- a full-sample qcut there would be exactly the full-sample-quantile look-ahead
    nylab.hyp_dsl's quantile_prior()/median_prior() split already exists to prevent (see
    nylab.hyp_dsl's module docstring). nylab.hyp_loader's `_check_prior_only()` would reject a
    `condition` referencing this function's output used as a rolling feature anyway; this helper
    is meant for report-building code, not hypothesis YAMLs."""
    valid = s.dropna()
    if len(valid) < 3:
        return pd.Series(np.nan, index=s.index, dtype=object)
    labels = pd.qcut(valid, 3, labels=["low", "mid", "high"], duplicates="drop")
    return labels.reindex(s.index)
