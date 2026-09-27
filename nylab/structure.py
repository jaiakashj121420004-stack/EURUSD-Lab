"""nylab.structure -- ROADMAP 7.1: swing-point labeling (HH/LH/HL/LL) and structure_score
(FEATURES_SPEC.md S4, Formula Handbook 6.5).

Builds on nylab.ict_features.fractal_swings(), which already gives the two hard parts right:
the pivot bar j is found by looking n bars EACH SIDE (a real fractal swing), and it is only
"available" -- i.e. only knowable to a strategy or a hypothesis condition -- at bar j+n, once
the n confirming bars on the right have actually printed. Every function here keeps carrying
that distinction forward: a swing's PRICE/POSITION is fixed at bar j, but its LABEL (HH vs LH,
HL vs LL) and any score built from it must only be exposed at j+n. Get this backwards and you
get a hypothesis or a model that "knew" a swing existed before the market had actually shown it
-- the exact look-ahead trap FEATURES_SPEC S4 calls out by name.

Operates on the FULL continuous bar series (nylab.ict_features's own convention -- market
structure doesn't reset at midnight), never per-day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import ict_features


def label_swings(bars: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    """Returns a DataFrame indexed like `bars` with one row per bar and, at each PIVOT bar j
    (not at j+n -- see `available_idx` below for the confirmation-time columns a caller should
    actually gate on):
      - `swing_high`/`swing_low`: bool, True at the pivot bar (from ict_features.fractal_swings).
      - `swing_high_label`/`swing_low_label`: "HH"/"LH" or "HL"/"LL" vs the PREVIOUS confirmed
        swing of the same type (by price, at the pivot bar's price -- comparing prices needs no
        extra lag; only the label's AVAILABILITY does).
      - `swing_high_available_idx`/`swing_low_available_idx`: the integer bar POSITION at which
        this pivot's label first becomes knowable (pivot position + n). A caller filtering
        "swings known by bar position p" must use `available_idx <= p`, never the pivot's own
        row position.
    The very first swing of each type has no predecessor to compare against and is left
    unlabeled (NaN) -- there is nothing to call it HH/LH against.
    """
    swing_high, swing_low = ict_features.fractal_swings(bars, n=n)
    pos = np.arange(len(bars))

    out = pd.DataFrame(index=bars.index)
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    out["swing_high_available_idx"] = np.where(swing_high, pos + n, -1)
    out["swing_low_available_idx"] = np.where(swing_low, pos + n, -1)

    high_label = pd.Series(pd.NA, index=bars.index, dtype="object")
    prev_high = None
    for i in np.flatnonzero(swing_high.to_numpy()):
        price = bars["high"].iloc[i]
        if prev_high is not None:
            high_label.iloc[i] = "HH" if price > prev_high else "LH"
        prev_high = price
    out["swing_high_label"] = high_label

    low_label = pd.Series(pd.NA, index=bars.index, dtype="object")
    prev_low = None
    for i in np.flatnonzero(swing_low.to_numpy()):
        price = bars["low"].iloc[i]
        if prev_low is not None:
            low_label.iloc[i] = "HL" if price > prev_low else "LL"
        prev_low = price
    out["swing_low_label"] = low_label

    return out


def structure_score_at(swings: pd.DataFrame, as_of_idx: int, k: int) -> float:
    """FEATURES_SPEC S4 / Formula Handbook 6.5: (HH + HL - LH - LL) / k over the last k
    CONFIRMED swings as of bar position `as_of_idx` -- i.e. only swings whose
    `*_available_idx <= as_of_idx` are eligible, mixing swing highs and swing lows together in
    time order of when each became confirmed (not pivot order), then taking the most recent k.
    Returns NaN if fewer than k confirmed swings exist yet (not enough history to score)."""
    highs = swings[swings["swing_high"] & (swings["swing_high_available_idx"] >= 0) &
                    (swings["swing_high_available_idx"] <= as_of_idx)]
    lows = swings[swings["swing_low"] & (swings["swing_low_available_idx"] >= 0) &
                   (swings["swing_low_available_idx"] <= as_of_idx)]
    events = []
    for avail, label in zip(highs["swing_high_available_idx"], highs["swing_high_label"]):
        if pd.notna(label):
            events.append((avail, label))
    for avail, label in zip(lows["swing_low_available_idx"], lows["swing_low_label"]):
        if pd.notna(label):
            events.append((avail, label))
    events.sort(key=lambda e: e[0])
    if len(events) < k:
        return float("nan")
    recent = [label for _, label in events[-k:]]
    score = sum(1 for l in recent if l in ("HH", "HL")) - sum(1 for l in recent if l in ("LH", "LL"))
    return score / k


def structure_score_series(swings: pd.DataFrame, k: int) -> pd.Series:
    """Vectorized-ish convenience: structure_score_at() evaluated at every bar position, forward-
    filled between confirmation events (the score only changes when a new swing is confirmed).
    Fine for a few thousand bars; for a multi-year M5 series prefer calling structure_score_at()
    directly only at the handful of decision points a model/hypothesis actually needs."""
    n = len(swings)
    out = np.full(n, np.nan)
    # Only recompute at bar positions where a NEW swing becomes available -- the score is
    # piecewise-constant between those, so this is O(events) work, not O(n) work, then a single
    # ffill fills the plateaus.
    change_points = sorted(set(
        int(v) for v in pd.concat([
            swings.loc[swings["swing_high"], "swing_high_available_idx"],
            swings.loc[swings["swing_low"], "swing_low_available_idx"],
        ]) if 0 <= v < n
    ))
    for p in change_points:
        out[p] = structure_score_at(swings, p, k)
    s = pd.Series(out, index=swings.index)
    return s.ffill()
