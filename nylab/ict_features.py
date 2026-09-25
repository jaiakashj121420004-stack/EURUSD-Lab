"""nylab.ict_features -- the handful of ICT building blocks Phase 5's SESSION table needs
(FEATURES_SPEC.md S4/S5/S7): confirmed fractal swings, displacement candles, and Fair Value Gaps.

Deliberately NOT here (FEATURES_SPEC S8-10, explicitly Phase 7 "ICT features & models"): FVG
lifecycle tracking (first_touch/ce_touch/full_fill/invalidated), Market Structure Shift, order
blocks, premium/discount. Phase 5 only needs COUNTS of swings/displacement/FVGs per session
window -- the full lifecycle machinery is deferred on purpose, same way Phase 2 deferred
Challenge mode to Phase 6 rather than bolting it on early.

Every function here operates on the FULL continuous bar series (not per-day), because market
structure doesn't reset at midnight -- a fractal swing spanning a session boundary is still a
real swing. Session-window counting (done in nylab.sessions) is what restricts these to "did
this happen, and was it CONFIRMED, before this session's own close" -- the look-ahead-safety
line, not an artificial per-day reset.
"""
from __future__ import annotations

import pandas as pd


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR(n) "known before bar i" (FEATURES_SPEC S4/S5): true range averaged over the n bars
    UP TO AND INCLUDING i-1, then reported at i's own index via shift(1) -- so atr.iloc[i] is
    exactly what a strategy could have known at the OPEN of bar i, never using bar i itself."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().shift(1)


def fractal_swings(bars: pd.DataFrame, n: int = 2) -> tuple[pd.Series, pd.Series]:
    """FEATURES_SPEC S4: a fractal swing high at bar j has high_j strictly greater than the highs
    of n bars on EACH side (mirror for swing low). Returns (swing_high, swing_low) boolean
    Series indexed like `bars`, True at the PIVOT bar j itself -- NOT yet knowable there; the
    pivot is only CONFIRMED at bar j+n (nylab.sessions is what enforces that availability rule
    when counting swings inside a session window, by requiring the confirming bar to also fall
    inside that window)."""
    high, low = bars["high"], bars["low"]
    swing_high = pd.Series(True, index=bars.index)
    swing_low = pd.Series(True, index=bars.index)
    for k in range(1, n + 1):
        swing_high &= (high > high.shift(k)) & (high > high.shift(-k))
        swing_low &= (low < low.shift(k)) & (low < low.shift(-k))
    return swing_high.fillna(False), swing_low.fillna(False)


def displacement_candles(bars: pd.DataFrame, atr_series: pd.Series,
                          k_disp: float = 1.3, body_ratio: float = 0.6) -> pd.Series:
    """FEATURES_SPEC S5: bar i is a displacement candle if its body >= k_disp * ATR (known
    before i, i.e. atr_series already shifted -- see atr() above) AND body/range >= body_ratio.
    Fully knowable at bar i's own close; no extra lag beyond that."""
    body = (bars["close"] - bars["open"]).abs()
    rng = (bars["high"] - bars["low"]).replace(0, pd.NA)
    return ((body >= k_disp * atr_series) & (body / rng >= body_ratio)).fillna(False)


def fair_value_gaps(bars: pd.DataFrame, atr_series: pd.Series,
                     min_pips: float = 0.8, min_atr_mult: float = 0.15, pip: float = 0.0001
                     ) -> tuple[pd.Series, pd.Series]:
    """FEATURES_SPEC S7: three consecutive bars (1,2,3 -- 3 latest). Bullish FVG (BISI):
    low_3 > high_1, gap = low_3 - high_1. Bearish (SIBI): high_3 < low_1. Size filter: gap >=
    max(min_pips, min_atr_mult * ATR at bar 2 -- the middle bar, known before bar 3 opens).
    Returns (bull_fvg, bear_fvg) boolean Series, True at bar 3's own index (available at bar
    3's close, per spec -- no extra lag)."""
    high, low = bars["high"], bars["low"]
    high1, low1 = high.shift(2), low.shift(2)
    # atr_series.iloc[i] is already "ATR known before bar i" (see atr() above). Bar 2 is i-1, so
    # shifting that back by 1 more aligns "ATR known before bar 2" onto bar 3's own row (i) --
    # the same alignment high1/low1 use for bar 1's prices.
    atr2 = atr_series.shift(1)

    min_gap = pd.Series(min_pips * pip, index=bars.index)
    min_gap = min_gap.where(min_gap >= min_atr_mult * atr2, min_atr_mult * atr2)

    bull_gap = low - high1
    bear_gap = low1 - high
    bull_fvg = (low > high1) & (bull_gap >= min_gap)
    bear_fvg = (high < low1) & (bear_gap >= min_gap)
    return bull_fvg.fillna(False), bear_fvg.fillna(False)
