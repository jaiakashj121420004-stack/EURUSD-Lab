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
