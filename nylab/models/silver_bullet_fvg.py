"""nylab.models.silver_bullet_fvg -- ROADMAP 7.5: the "ICT Silver Bullet" concept as a proper
ARCHITECTURE.md S4 Model plugin, parameterized by window (config/models/silver_bullet_fvg_*.yaml
runs the SAME class in the London, NY AM, and NY PM Silver Bullet windows -- three separate
(name, version) ledger entries, per ROADMAP 7.5's "same rules... 3 separate ledger entries").

Rule (FEATURES_SPEC.md S7/S8): within the model's window, wait for a Market Structure Shift
(nylab.events.detect_mss) whose triggering SWEEP happened inside the same window. If that MSS's
displacement leg created at least one Fair Value Gap in the continuation direction
(`leg_fvgs`, already computed by detect_mss), enter on the first retracement into that FVG's
center (`ce`) within `entry_max_bars_after_mss` bars of the MSS -- in the direction the MSS
itself continues (bearish MSS -> short, bullish MSS -> long: retracement UP into a bear FVG
before continuing down, mirror for bullish). Stop beyond the FVG's far edge, target a fixed R
multiple. No MSS, or an MSS with no leg FVG, or a retracement that never arrives within the
window -- no trade that day (disclosed simplification: this model only ever acts on the FIRST
qualifying MSS per window/day, and only ever the FIRST FVG in its leg).

Needs BOTH the MSS table (with its leg_fvgs) and the FVG lifecycle table (for each leg FVG's own
top/bottom/ce) -- nylab.backtest.run_backtest's `events` param accepts a dict of tables for
exactly this ({'mss': ..., 'fvg': ...}).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import backtest as backtest_mod


class SilverBulletFVGModel:
    def __init__(self, name: str, params: dict):
        self.name = name
        self.version = "1.0"
        self.params = params
        # `_committed` remembers WHICH MSS this trading day has locked onto, once found -- this
        # must persist across calls so a retracement that lands several bars AFTER the MSS itself
        # confirms (the normal case: it essentially never happens on the exact same bar) still
        # gets checked on those later bars. `_done_days` is the genuinely TERMINAL state -- only
        # set when a signal actually fires, the committed MSS turns out to have no leg FVG, its
        # FVG row can't be found, the retracement deadline expires without a touch, or the
        # resulting risk is degenerate. Bug fixed 2026-09-27: the original single `_resolved_days`
        # set was populated the moment a candidate MSS was found (before the retracement check),
        # which meant every day silently gave up on its first call and produced zero trades.
        self._committed: dict = {}
        self._done_days: set = set()

    def signals(self, day_bars: pd.DataFrame, day: pd.Series, events: dict) -> list:
        p = self.params
        # `window` (used by the ENGINE to decide which bars to even call us on) has to be wider
        # than the true silver-bullet killzone: the MSS confirming a killzone sweep can land up
        # to `mss_max_bars` after it, and the retracement entry up to `entry_max_bars_after_mss`
        # after THAT -- both need to fall inside `window` too, or the engine would never call us
        # on the very bar the entry needs. `kz_window` (defaulting to `window` for backward
        # compatibility) is the narrower gate that actually defines "this sweep counts as a
        # silver-bullet setup" via `extreme_h`.
        kz_lo, kz_hi = p.get("kz_window", p["window"])
        td_key = day.name
        if td_key in self._done_days:
            return []

        mss = events.get("mss", pd.DataFrame())
        fvg = events.get("fvg", pd.DataFrame())

        current_pos = day_bars.index[-1]  # global bar position (see backtest.run_backtest docstring)

        if td_key in self._committed:
            row = self._committed[td_key]
        else:
            if len(mss) == 0:
                return []
            # The MSS whose triggering sweep happened in THIS killzone, already fully visible by
            # the current bar, earliest first, not yet used.
            candidates = mss[(mss["extreme_h"] >= kz_lo) & (mss["extreme_h"] < kz_hi) &
                              (mss["mss_idx"] <= current_pos)].sort_values("mss_idx")
            if len(candidates) == 0:
                return []
            row = candidates.iloc[0]
            # Commit to this MSS (this window only ever acts on the FIRST such MSS) -- but do NOT
            # mark the day done yet; the retracement may still be bars away.
            self._committed[td_key] = row

        leg_fvgs = row["leg_fvgs"]
        if not leg_fvgs:
            self._done_days.add(td_key)
            return []  # no FVG in the leg -- disclosed simplification, no trade
        fvg_bar_idx = leg_fvgs[0]
        fvg_row = fvg[fvg["bar_idx"] == fvg_bar_idx]
        if len(fvg_row) == 0:
            self._done_days.add(td_key)
            return []
        fvg_row = fvg_row.iloc[0]
        top, bottom, ce = float(fvg_row["top"]), float(fvg_row["bottom"]), float(fvg_row["ce"])

        bearish = row["direction"] == "bearish"
        pip = p.get("pip", 0.0001)
        buf = p["stop_buffer_pips"] * pip
        deadline_pos = row["mss_idx"] + p["entry_max_bars_after_mss"]

        if current_pos > deadline_pos:
            self._done_days.add(td_key)
            return []  # retracement window expired without a fill

        high = day_bars["high"].to_numpy()
        low = day_bars["low"].to_numpy()
        # Only bars strictly AFTER the MSS itself count toward the retracement.
        mask = day_bars.index.to_numpy() > row["mss_idx"]
        if not mask[-1]:
            return []  # current bar isn't past the MSS yet -- keep waiting, not done
        touched = (high[-1] >= ce) if bearish else (low[-1] <= ce)
        if not touched:
            return []  # still waiting for the retracement, not done

        side = "short" if bearish else "long"
        stop = top + buf if bearish else bottom - buf  # far edge of the gap, plus a buffer
        risk = abs(ce - stop)
        if risk < 2 * pip:
            self._done_days.add(td_key)
            return []
        rr = p.get("rr")
        target = (ce - rr * risk) if (bearish and rr) else (ce + rr * risk) if rr else None
        self._done_days.add(td_key)  # signal fired -- terminal for this day
        return [backtest_mod.Signal(bar_index=len(day_bars) - 1, side=side, entry_price=ce,
                                     stop_price=stop, target_price=target,
                                     time_exit_h=p["time_exit"])]
