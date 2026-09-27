"""nylab.models.london_sweep_reversal -- the v0 example model, ported verbatim.

London KZ sweep reversal in the NY AM window. Phase 7 turns this into a proper Model plugin
(ARCHITECTURE.md S4); for Phase 1 it just needs to reproduce v0's trades/numbers exactly.
Params come from config/models/london_sweep_reversal.yaml (+ default_cost_pips from costs.yaml).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def backtest(df: pd.DataFrame, d: pd.DataFrame, pip: float, params: dict) -> pd.DataFrame:
    lo_w, hi_w = params["window"]
    cost_default = params["default_cost_pips"] * pip
    trades = []
    bars = df[(df.h >= lo_w) & (df.h < params["time_exit"])]
    for td, g in bars.groupby("td"):
        if td not in d.index:
            continue
        L_hi, L_lo = d.at[td, "lon_high"], d.at[td, "lon_low"]
        if not np.isfinite(L_hi):
            continue
        g = g.reset_index(drop=True)
        trade = None
        for side in ("short", "long"):
            poke = g[(g.h < hi_w) & ((g.high > L_hi) if side == "short" else (g.low < L_lo))]
            if poke.empty:
                continue
            i0 = poke.index[0]
            for j in range(i0, min(i0 + params["max_bars_after_sweep"] + 1, len(g))):
                if g.at[j, "h"] >= hi_w:
                    break
                back_inside = g.at[j, "close"] < L_hi if side == "short" else g.at[j, "close"] > L_lo
                if back_inside:
                    ext = g.loc[i0:j, "high"].max() if side == "short" else g.loc[i0:j, "low"].min()
                    cand = dict(td=td, side=side, i=j, entry=g.at[j, "close"], ext=ext)
                    if trade is None or j < trade["i"]:
                        trade = cand
                    break
        if trade is None:
            continue
        side, e, j = trade["side"], trade["entry"], trade["i"]
        spread = (g.at[j, "spread_pts"] * pip / 10) if "spread_pts" in g and np.isfinite(g.at[j, "spread_pts"]) else None
        cost = max(cost_default, (spread or 0) + 0.2 * pip)
        buf = params["stop_buffer_pips"] * pip
        stop = trade["ext"] + buf if side == "short" else trade["ext"] - buf
        risk = abs(e - stop)
        if risk < 2 * pip:
            continue
        if params["rr"]:
            tgt = e - params["rr"] * risk if side == "short" else e + params["rr"] * risk
        else:
            tgt = L_lo if side == "short" else L_hi
        exit_px, reason = None, "time"
        for k in range(j + 1, len(g)):
            hi, lo = g.at[k, "high"], g.at[k, "low"]
            hit_stop = hi >= stop if side == "short" else lo <= stop
            hit_tgt = lo <= tgt if side == "short" else hi >= tgt
            if hit_stop:
                exit_px, reason = stop, "stop"; break
            if hit_tgt:
                exit_px, reason = tgt, "target"; break
        if exit_px is None:
            exit_px = g["close"].iloc[-1]
        pnl = (e - exit_px) if side == "short" else (exit_px - e)
        trades.append(dict(
            td=td, side=side,
            entry_time_ny=f"{int(g.at[j,'h']):02d}:{int(round((g.at[j,'h']%1)*60)):02d}",
            entry=e, stop=stop, target=tgt, exit=exit_px, reason=reason,
            risk_pips=risk / pip, R_gross=pnl / risk, R_net=(pnl - cost) / risk, cost_R=cost / risk,
        ))
    return pd.DataFrame(trades)



# ---------------------------------------------------------------------------------------------
# ROADMAP 7.5: the same v0 rules, restructured as a proper ARCHITECTURE.md S4 Model plugin so it
# runs through the ONE generic engine (nylab.backtest.run_backtest) every Phase 7+ model uses,
# instead of this file's own bespoke bar-scanning loop above. The function above is kept
# UNCHANGED and still what `nylab run` calls for the Phase 1 report (so existing report numbers
# never move); this class is the new go-forward path new work (silver_bullet_fvg, walk-forward,
# ledger-logged model runs) should use. tests/test_models_london_sweep_reversal.py proves the two
# produce IDENTICAL trades on the same data -- this is a plumbing refactor, not a rule change, so
# the version stays "1.0".
from nylab import backtest as backtest_mod


class LondonSweepReversalModel:
    name = "london_sweep_reversal"
    version = "1.0"

    def __init__(self, params: dict):
        self.params = params
        # The ad hoc backtest() above decides a day's trade ONCE, by looking at BOTH sides'
        # full resolutions and picking whichever completes earliest -- if THAT one fails the
        # min-risk filter, the whole day is abandoned (no fallback to the other side, even if it
        # would have resolved later with valid risk). Our per-bar walk-forward only ever sees
        # one bar at a time, so it can't "look ahead" to know in advance which side wins; instead
        # it reproduces the same rule by remembering, once the chronologically-first resolution
        # across either side is finally SEEN (whichever bar that turns out to be), whether that
        # attempt was rejected -- and if so, treats the rest of that trading day as a dead end,
        # exactly like the ad hoc version's `continue`. Keyed by td so state never leaks across
        # days (each day gets a fresh decision).
        self._abandoned_days: set = set()

    def signals(self, day_bars: pd.DataFrame, day: pd.Series, events: pd.DataFrame) -> list:
        p = self.params
        lo_w, hi_w = p["window"]
        td_key = day.name
        if td_key in self._abandoned_days:
            return []
        L_hi, L_lo = day.get("lon_high"), day.get("lon_low")
        if L_hi is None or not np.isfinite(L_hi):
            return []
        pip = p.get("pip", 0.0001)

        h = day_bars["h"].to_numpy()
        high, low, close = day_bars["high"].to_numpy(), day_bars["low"].to_numpy(), day_bars["close"].to_numpy()
        win_pos = np.flatnonzero((h >= lo_w) & (h < hi_w))
        if len(win_pos) == 0 or win_pos[-1] != len(day_bars) - 1:
            # Only worth evaluating once the CURRENT last bar is itself the window's own latest
            # bar so far (mirrors the ad hoc version's `if g.h[j] >= hi_w: break`) -- the engine
            # only calls us for in-window bars anyway, so this is normally always true; the guard
            # is defensive if this model is ever driven a different way.
            return []

        i_last = len(day_bars) - 1
        best = None
        for side in ("short", "long"):
            cond = high > L_hi if side == "short" else low < L_lo
            side_win_pos = win_pos[cond[win_pos]]
            if len(side_win_pos) == 0:
                continue
            i0 = int(side_win_pos[0])
            j_end = min(i0 + p["max_bars_after_sweep"], win_pos[-1])
            for j in range(i0, j_end + 1):
                back_inside = close[j] < L_hi if side == "short" else close[j] > L_lo
                if back_inside:
                    if j == i_last:
                        ext = high[i0:j + 1].max() if side == "short" else low[i0:j + 1].min()
                        cand = (j, side, float(close[j]), float(ext))
                        if best is None or j < best[0]:
                            best = cand
                    break  # first close-back only, same as the ad hoc version

        if best is None:
            return []
        j, side, entry, ext = best
        buf = p["stop_buffer_pips"] * pip
        stop = ext + buf if side == "short" else ext - buf
        risk = abs(entry - stop)
        if risk < 2 * pip:
            self._abandoned_days.add(td_key)  # matches the ad hoc version's whole-day `continue`
            return []
        if p.get("rr"):
            tgt = entry - p["rr"] * risk if side == "short" else entry + p["rr"] * risk
        else:
            tgt = L_lo if side == "short" else L_hi
        return [backtest_mod.Signal(bar_index=j, side=side, entry_price=entry, stop_price=stop,
                                     target_price=tgt, time_exit_h=p["time_exit"])]
