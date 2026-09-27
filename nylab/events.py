"""nylab.events -- ROADMAP 7.2/7.3: FVG lifecycle tracking, full raid/sweep event detail,
Market Structure Shift (MSS), and order blocks (FEATURES_SPEC.md S3, S7, S8, S9).

This is the Phase 7 generalization nylab/ict_features.py's own docstring explicitly deferred:
that module gives per-bar BOOLEANS (was bar i a swing pivot / displacement candle / FVG bar-3)
suitable for Phase 5's per-session COUNTS. This module turns those booleans into actual EVENT
records with a full lifecycle -- when an FVG got touched/filled/invalidated, every raid (not
just the first per session, which nylab.sessions.py already tracks for its own character/day-type
labels), and the sweep -> MSS -> order-block chain those raids can trigger.

Reuses nylab.sessions's already-validated raid/sweep-vs-break constants and classification rule
(K_BACK, BREAK_CLOSE_PIPS, RAID_TOL_PIPS) rather than re-deriving a second, possibly-drifted
copy of FEATURES_SPEC S3 -- config/features.yaml's `raid` section documents the same numbers for
readers, but the CODE path imports the sessions.py constants directly so there is exactly one
place a change to the rule would need to happen.

Every function here operates on the FULL continuous bar series, same convention as
nylab.ict_features and nylab.structure -- an MSS or a sweep doesn't reset at midnight.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import ict_features
from nylab.sessions import BREAK_CLOSE_PIPS, K_BACK, RAID_TOL_PIPS


def _time_col(bars: pd.DataFrame) -> pd.Series:
    """Real bar DataFrames in this codebase carry a plain 0..n-1 RangeIndex (see
    nylab.__main__._prepare_bars's `reset_index(drop=True)`) with the actual NY timestamp in a
    separate `ny` column -- so `bars.index[i]` alone is just the integer position, not a useful
    time for an events table a person might read. Prefer `ny` when present; fall back to the
    index itself (e.g. in tests that build a DatetimeIndex fixture directly)."""
    return bars["ny"] if "ny" in bars.columns else pd.Series(bars.index, index=bars.index)


# ---------------------------------------------------------------------------------- FVG lifecycle
def fvg_lifecycle(bars: pd.DataFrame, atr_series: pd.Series, pip: float,
                   min_pips: float = 0.8, min_atr_mult: float = 0.15,
                   horizon_bars: int = 288) -> pd.DataFrame:
    """FEATURES_SPEC S7: one row per FVG (bar 3 of the 3-bar pattern), with top/bottom/ce and
    the four lifecycle timestamps (as integer bar POSITIONS into `bars`, or -1 if not reached
    within `horizon_bars` bars of the FVG's own creation -- 576 bars = 2 days on M5, generous
    for a "did this get touched at all" descriptive stat without scanning the entire rest of a
    5-year series for every one of tens of thousands of gaps).

    A bullish FVG (created during an up-move) has price return to it from ABOVE, so its
    lifecycle checks LOW against top/ce/bottom; a bearish FVG's price returns from BELOW, so it
    checks HIGH. `full_fill` = price trades through the FAR side (bottom for bullish, top for
    bearish); `invalidated` = a bar actually CLOSES beyond that far side (a wick reaching it is
    only full_fill, not yet invalidation -- FEATURES_SPEC's own distinction)."""
    bull_fvg, bear_fvg = ict_features.fair_value_gaps(bars, atr_series, min_pips, min_atr_mult, pip)
    high, low, close = bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy()
    tcol = _time_col(bars)
    n = len(bars)

    rows = []
    for direction, mask in (("bull", bull_fvg), ("bear", bear_fvg)):
        for i in np.flatnonzero(mask.to_numpy()):
            if direction == "bull":
                bottom, top = high[i - 2], low[i]
            else:
                bottom, top = high[i], low[i - 2]
            ce = (top + bottom) / 2.0
            is_disp_leg = bool(ict_features.displacement_candles(
                bars.iloc[max(0, i - 2):i - 1], atr_series.iloc[max(0, i - 2):i - 1]
            ).any()) if i >= 2 else False

            end = min(n, i + 1 + horizon_bars)
            # Vectorized (numpy) rather than a bar-by-bar python loop -- with tens of thousands
            # of FVGs over a multi-year M5 series, a python-level loop over up to `horizon_bars`
            # iterations PER EVENT was too slow to finish in practice (verified: it didn't
            # complete within 2 minutes on the 2-year fixture). Semantics are unchanged: once a
            # bar CLOSES beyond the far side (invalidated), the gap is considered dead and later
            # bars don't count toward first_touch/ce_touch/full_fill either -- so invalidated is
            # found first and used to clip the search window for the other three, exactly
            # mirroring the old loop's `break` on invalidation.
            first_touch = ce_touch = full_fill = invalidated = -1
            if end > i + 1:
                if direction == "bull":
                    inval_hits = np.flatnonzero(close[i + 1:end] < bottom)
                else:
                    inval_hits = np.flatnonzero(close[i + 1:end] > top)
                search_end = (i + 1 + inval_hits[0] + 1) if len(inval_hits) else end
                if len(inval_hits):
                    invalidated = i + 1 + inval_hits[0]

                if search_end > i + 1:
                    if direction == "bull":
                        lo_slice = low[i + 1:search_end]
                        t = np.flatnonzero(lo_slice <= top)
                        c = np.flatnonzero(lo_slice <= ce)
                        f = np.flatnonzero(lo_slice <= bottom)
                    else:
                        hi_slice = high[i + 1:search_end]
                        t = np.flatnonzero(hi_slice >= bottom)
                        c = np.flatnonzero(hi_slice >= ce)
                        f = np.flatnonzero(hi_slice >= top)
                    if len(t):
                        first_touch = i + 1 + t[0]
                    if len(c):
                        ce_touch = i + 1 + c[0]
                    if len(f):
                        full_fill = i + 1 + f[0]

            rows.append(dict(
                bar_idx=i, t=tcol.iloc[i], direction=direction, top=top, bottom=bottom, ce=ce,
                gap_pips=(top - bottom) / pip, is_displacement_leg=is_disp_leg,
                first_touch_idx=first_touch, ce_touch_idx=ce_touch,
                full_fill_idx=full_fill, invalidated_idx=invalidated,
            ))
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("bar_idx").reset_index(drop=True)
    return out


# --------------------------------------------------------------------------------- raid / sweep
def detect_raids(bars: pd.DataFrame, levels: dict, lo_h: float, hi_h: float, pip: float,
                  tol_pips: float = RAID_TOL_PIPS, k_back: int = K_BACK,
                  break_close_pips: float = BREAK_CLOSE_PIPS) -> pd.DataFrame:
    """FEATURES_SPEC S3, generalized from nylab.sessions._first_raid_table to record EVERY raid
    of every level within [lo_h, hi_h) per trading day, not just the first (nylab.sessions
    already covers "first raid" for the day-table character/day-type columns -- this is the full
    event log ROADMAP 7.3's events.parquet needs, e.g. for sweep -> MSS conversion stats, which
    need every sweep, not only the day's first one).

    `levels`: {name: (side, per-td level Series)} where side is 'above' or 'below' (mirrors
    nylab.sessions's own convention). One output row per raid with full detail: t_raid,
    t_close_back, raid_type ('sweep' | 'break'), sweep_extreme (the most-favorable price reached
    before closing back -- max high for an above-side raid, min low for below-side),
    extreme_idx (bar position of that extreme, needed by detect_mss below),
    penetration_pips, bars_to_close_back."""
    tol = tol_pips * pip
    highs, lows, closes, hs = (bars["high"].to_numpy(), bars["low"].to_numpy(),
                                bars["close"].to_numpy(), bars["h"].to_numpy())
    tcol = _time_col(bars)
    n = len(bars)
    rows = []
    for td_val, day_slice in bars.groupby("td").groups.items():
        pos = day_slice.to_numpy()
        win_pos = pos[(hs[pos] >= lo_h) & (hs[pos] < hi_h)]
        if len(win_pos) == 0:
            continue
        start_pos, end_pos = int(win_pos.min()), int(win_pos.max()) + 1
        for name, (side, level_series) in levels.items():
            level = level_series.get(td_val, np.nan)
            if pd.isna(level):
                continue
            level = float(level)
            i = start_pos
            while i < end_pos:
                raid_pos = None
                for k in range(i, end_pos):
                    if side == "above" and highs[k] > level + tol:
                        raid_pos = k
                        break
                    if side == "below" and lows[k] < level - tol:
                        raid_pos = k
                        break
                if raid_pos is None:
                    break
                close_back_pos, raid_type = None, None
                extreme_pos = raid_pos
                for j in range(raid_pos, min(raid_pos + k_back + 1, n)):
                    if side == "above":
                        if highs[j] > highs[extreme_pos]:
                            extreme_pos = j
                    else:
                        if lows[j] < lows[extreme_pos]:
                            extreme_pos = j
                    c = closes[j]
                    if side == "above":
                        if c > level and (c - level) / pip > break_close_pips:
                            raid_type = "break"
                            break
                        if c < level:
                            raid_type, close_back_pos = "sweep", j
                            break
                    else:
                        if c < level and (level - c) / pip > break_close_pips:
                            raid_type = "break"
                            break
                        if c > level:
                            raid_type, close_back_pos = "sweep", j
                            break
                if raid_type is None:
                    raid_type = "break"
                extreme = highs[extreme_pos] if side == "above" else lows[extreme_pos]
                penetration = (extreme - level) / pip if side == "above" else (level - extreme) / pip
                rows.append(dict(
                    td=td_val, level_name=name, side=side, level_price=level,
                    raid_idx=raid_pos, t_raid=tcol.iloc[raid_pos], t_raid_h=float(hs[raid_pos]),
                    raid_type=raid_type,
                    close_back_idx=close_back_pos,
                    t_close_back=tcol.iloc[close_back_pos] if close_back_pos is not None else pd.NaT,
                    bars_to_close_back=(close_back_pos - raid_pos) if close_back_pos is not None else None,
                    extreme_idx=extreme_pos, sweep_extreme=float(extreme),
                    penetration_pips=float(penetration),
                ))
                if close_back_pos is not None:
                    # price is back on the original side right away -- a fresh raid can be
                    # detected starting the very next bar.
                    i = close_back_pos + 1
                else:
                    # 'break' (acceptance): price never closed back within k_back. It would be
                    # wrong to let every subsequent bar still sitting beyond the level count as
                    # its OWN new raid (that would fire a spurious raid on every single bar of an
                    # extended trend) -- a genuinely NEW raid requires price to first come back to
                    # the original side, THEN trade through the level again. Find that reset point
                    # (if any) before resuming the scan; if price never comes back in this window,
                    # there is nothing more to find here.
                    reset_pos = None
                    for r in range(min(raid_pos + k_back + 1, end_pos), end_pos):
                        back_on_original_side = closes[r] < level if side == "above" else closes[r] > level
                        if back_on_original_side:
                            reset_pos = r
                            break
                    if reset_pos is None:
                        break
                    i = reset_pos + 1
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("raid_idx").reset_index(drop=True)
    return out


# -------------------------------------------------------------------------------------------- MSS
def detect_mss(bars: pd.DataFrame, raids: pd.DataFrame, swings: pd.DataFrame,
                displacement: pd.Series, bull_fvg: pd.Series, bear_fvg: pd.Series,
                max_bars: int = 24) -> pd.DataFrame:
    """FEATURES_SPEC S8: for every 'sweep' raid, look for the Market Structure Shift it can
    trigger -- an above-side sweep implies a BEARISH MSS (close below the most recent confirmed
    swing low that formed before the sweep's extreme), a below-side sweep implies a BULLISH MSS
    (close above the most recent confirmed swing high before the extreme). Requires at least one
    displacement candle somewhere in the move from the sweep extreme to the MSS close, within
    `max_bars`. `leg_fvgs` records the (bar-3) positions of any FVGs in the sweep's own direction
    created between the extreme and the MSS close -- the ones a silver_bullet_fvg-style model
    would look to retrace into."""
    close = bars["close"].to_numpy()
    disp = displacement.to_numpy()
    low_arr, high_arr = bars["low"].to_numpy(), bars["high"].to_numpy()
    n = len(bars)
    tcol = _time_col(bars)

    # Precompute ONCE, outside the per-raid loop: swing pivot bar POSITIONS in ascending order
    # (np.flatnonzero on a boolean array is already sorted ascending) plus their availability
    # lag `n_confirm` -- swing_low_available_idx = pivot_pos + n_confirm for every pivot (same
    # fixed n_confirm from structure.label_swings), so "available_idx <= extreme_pos" is
    # EXACTLY "pivot_pos <= extreme_pos - n_confirm", which also automatically satisfies "pivot
    # formed before the extreme" (n_confirm >= 1). That turns "most recent qualifying swing
    # before this raid's extreme" into a single np.searchsorted binary search per raid instead
    # of re-filtering and re-scanning the WHOLE swings table for every raid -- the previous
    # per-raid O(n_swings) version made this function quadratic in the number of raids and
    # confirmed swings, which didn't finish in under 2 minutes on the real 2-year fixture.
    low_positions = np.flatnonzero(swings["swing_low"].to_numpy())
    high_positions = np.flatnonzero(swings["swing_high"].to_numpy())
    n_confirm = int(swings["swing_low_available_idx"].iloc[low_positions[0]] - low_positions[0]) if len(low_positions) else 2

    def _most_recent_before(positions: np.ndarray, extreme_pos: int):
        cutoff = extreme_pos - n_confirm  # pivot_pos <= cutoff  <=>  available_idx <= extreme_pos
        k = np.searchsorted(positions, cutoff, side="right") - 1
        return int(positions[k]) if k >= 0 else None

    bull_idx = np.flatnonzero(bull_fvg.to_numpy())
    bear_idx = np.flatnonzero(bear_fvg.to_numpy())
    hs = bars["h"].to_numpy()

    rows = []
    for r in raids.itertuples():
        if r.raid_type != "sweep":
            continue
        extreme_pos = r.extreme_idx
        bearish = r.side == "above"  # swept a high -> expect bearish reversal
        ref_pos = _most_recent_before(low_positions if bearish else high_positions, extreme_pos)
        if ref_pos is None:
            continue
        ref_price = low_arr[ref_pos] if bearish else high_arr[ref_pos]

        mss_pos = None
        for j in range(extreme_pos + 1, min(n, extreme_pos + 1 + max_bars)):
            if (bearish and close[j] < ref_price) or (not bearish and close[j] > ref_price):
                if disp[extreme_pos + 1:j + 1].any():
                    mss_pos = j
                break
        if mss_pos is None:
            continue
        leg_pool = bear_idx if bearish else bull_idx  # sorted ascending (flatnonzero) -> binary search the range
        lo_i = np.searchsorted(leg_pool, extreme_pos, side="left")
        hi_i = np.searchsorted(leg_pool, mss_pos, side="right")
        leg_fvgs = [int(p) for p in leg_pool[lo_i:hi_i]]
        rows.append(dict(
            raid_idx=r.raid_idx, td=r.td, level_name=r.level_name, direction="bearish" if bearish else "bullish",
            extreme_idx=extreme_pos, mss_idx=mss_pos, t_mss=tcol.iloc[mss_pos],
            extreme_h=float(hs[extreme_pos]), mss_h=float(hs[mss_pos]),
            mss_level=float(ref_price), bars_from_sweep=mss_pos - extreme_pos,
            leg_fvgs=leg_fvgs,
        ))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------- order block
def detect_order_blocks(bars: pd.DataFrame, mss: pd.DataFrame, displacement: pd.Series) -> pd.DataFrame:
    """FEATURES_SPEC S9 (low priority, defined for completeness): for each MSS, find the first
    displacement candle in [extreme_idx, mss_idx] (the leg that caused the MSS), then walk
    backward from it for the last OPPOSITE-colored close bar -- a bearish MSS's order block is
    the last UP-close bar before the down-displacement leg (mirror for bullish). Zone = that
    bar's [low, high]; `mean_threshold` = its 50% level."""
    disp = displacement.to_numpy()
    open_, high, low, close = (bars["open"].to_numpy(), bars["high"].to_numpy(),
                                bars["low"].to_numpy(), bars["close"].to_numpy())
    rows = []
    for r in mss.itertuples():
        disp_pos = None
        for k in range(r.extreme_idx, r.mss_idx + 1):
            if disp[k]:
                disp_pos = k
                break
        if disp_pos is None:
            continue
        ob_pos = None
        for k in range(disp_pos - 1, max(-1, disp_pos - 50), -1):
            is_up = close[k] > open_[k]
            if (r.direction == "bearish" and is_up) or (r.direction == "bullish" and not is_up):
                ob_pos = k
                break
        if ob_pos is None:
            continue
        rows.append(dict(
            mss_idx=r.mss_idx, td=r.td, direction=r.direction, ob_idx=ob_pos, t=_time_col(bars).iloc[ob_pos],
            zone_low=float(low[ob_pos]), zone_high=float(high[ob_pos]),
            mean_threshold=float((low[ob_pos] + high[ob_pos]) / 2.0),
        ))
    return pd.DataFrame(rows)
