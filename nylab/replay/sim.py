"""nylab.replay.sim -- mock-trade fill engine + Maven account state.

Stateless, pure functions (no server-side session state) so the same logic is directly
testable and reused by nylab/models/*.py's conservative same-bar rule (REPLAY_TRAINER.md S8:
"Fill engine = the same backtest engine rules"). The replay frontend keeps the *position*
state client-side (it already legitimately holds every bar the no-leak API has revealed to
it); the server's job is just the per-bar fill check and the lot-size/account math, so there
is exactly one implementation of "did this bar hit the stop or the target" -- not one in
Python and a second, possibly-different one in JS.
"""
from __future__ import annotations

import math


def market_fill_price(next_bar: dict) -> float:
    """A market order fills at the next bar's open (REPLAY_TRAINER.md S8) -- conservative,
    same rule the backtest engine uses (no fills inside the bar that triggered the order)."""
    return float(next_bar["open"])


def check_bar(position: dict, bar: dict) -> dict:
    """position: {side: 'long'|'short', sl: float, tp: float|None}. bar: {high, low, close}.
    Same conservative rule as nylab.models.london_sweep_reversal.backtest(): if both the stop
    and the target are touched in the same bar, the STOP wins (RESEARCH_PROTOCOL rule 6).
    Returns {filled: bool, reason: 'stop'|'target'|None, exit: float|None}."""
    side, sl, tp = position["side"], position.get("sl"), position.get("tp")
    hi, lo = float(bar["high"]), float(bar["low"])

    # long: stop is BELOW entry (hit when price falls through it: lo <= sl), target ABOVE
    # (hit when price rises through it: hi >= tp). short is the mirror image.
    hit_stop = sl is not None and ((lo <= sl) if side == "long" else (hi >= sl))
    hit_tgt = tp is not None and ((hi >= tp) if side == "long" else (lo <= tp))

    if hit_stop:
        return {"filled": True, "reason": "stop", "exit": float(sl)}
    if hit_tgt:
        return {"filled": True, "reason": "target", "exit": float(tp)}
    return {"filled": False, "reason": None, "exit": None}


def compute_r(side: str, entry: float, exit_price: float, sl: float, cost_pips: float, pip: float) -> dict:
    """R-multiple, net of cost -- same formula as nylab.models.london_sweep_reversal."""
    risk = abs(entry - sl)
    if risk <= 0:
        return {"risk_pips": 0.0, "R_gross": 0.0, "R_net": 0.0}
    pnl = (exit_price - entry) if side == "long" else (entry - exit_price)
    cost = cost_pips * pip
    return {
        "risk_pips": risk / pip,
        "R_gross": pnl / risk,
        "R_net": (pnl - cost) / risk,
    }


def lots_from_risk(balance: float, risk_pct: float, sl_distance_pips: float, pip_value_per_lot: float = 10.0) -> float:
    """Standard FX position sizing (Formula Handbook 2.1): lots = risk$ / (SL pips * pip value
    per lot), rounded DOWN to 0.01 (REPLAY_TRAINER.md S8). pip_value_per_lot defaults to $10/pip
    for a standard lot on a USD-quote pair like EURUSD."""
    if sl_distance_pips <= 0:
        return 0.0
    risk_dollars = balance * (risk_pct / 100.0)
    lots = risk_dollars / (sl_distance_pips * pip_value_per_lot)
    return math.floor(lots * 100) / 100.0


def maven_state(starting_balance: float, current_balance: float, day_start_balance: float,
                 peak_balance: float, program: dict) -> dict:
    """Live account panel numbers (REPLAY_TRAINER.md S8): day P&L %, distance to the daily
    and max drawdown limits, amber at 50% of the limit consumed, red at 75%."""
    daily_dd_limit_pct = float(program["daily_dd_pct"])
    max_dd_limit_pct = float(program["max_dd_pct"])

    day_pnl_pct = (current_balance - day_start_balance) / starting_balance * 100.0
    day_loss_pct = max(0.0, -day_pnl_pct)
    day_used_frac = day_loss_pct / daily_dd_limit_pct if daily_dd_limit_pct else 0.0

    dd_from_peak_pct = max(0.0, (peak_balance - current_balance) / starting_balance * 100.0)
    max_used_frac = dd_from_peak_pct / max_dd_limit_pct if max_dd_limit_pct else 0.0

    def _status(frac):
        if frac >= 0.75:
            return "red"
        if frac >= 0.5:
            return "amber"
        return "green"

    return {
        "balance": round(current_balance, 2),
        "day_pnl_pct": round(day_pnl_pct, 3),
        "day_dd_limit_pct": daily_dd_limit_pct,
        "day_dd_used_pct": round(day_loss_pct, 3),
        "day_dd_status": _status(day_used_frac),
        "day_dd_breached": day_loss_pct >= daily_dd_limit_pct,
        "max_dd_limit_pct": max_dd_limit_pct,
        "max_dd_used_pct": round(dd_from_peak_pct, 3),
        "max_dd_status": _status(max_used_frac),
        "max_dd_breached": dd_from_peak_pct >= max_dd_limit_pct,
    }
