"""nylab.maven_sim -- ROADMAP 8.4: the Maven pass simulator. Bootstrap-Monte-Carlo's a model's
OOS R-multiple distribution through a Maven program's evaluation phase(s) (config/prop.yaml,
verified 2026-09-24 -- "Sizes are USD account size; prices are approximate and change --
re-verify before relying on them for cost math", so this module never hardcodes a challenge fee:
callers who want an expected-$-cost figure must supply their own verified `fee_usd`).

Per simulated trading day: bootstrap-resample ONE trade (with replacement) from the model's own
OOS R_net multiples (this project's Phase 7 models are one_trade_per_day, so "one trade" and "one
trading day" are the same unit here), convert it to a dollar P&L via `risk_pct` of the CURRENT
balance, and apply the exact same daily-drawdown-from-day-start / max-drawdown-from-peak breach
formulas nylab.replay.sim.maven_state() uses for the live replay account panel (re-derived here in
plain arithmetic for a fast inner loop rather than calling that function 10k*max_days times) --
so a live practice-trade breach and a simulated one are judged by the SAME rule. `max_dd_type`
('static_balance' keeps the peak fixed at the phase's starting size; 'trailing' lets it run up
with equity) is read from the program dict, exactly like the live account panel's caller has to
decide which balance to pass as `peak_balance`.

Each phase (config/prop.yaml's `profit_targets_pct` list) restarts the simulated balance at
`size` -- Maven's own evaluations don't carry equity from step 1 into step 2, they're separate
accounts. `min_profitable_days_per_phase` / `min_profit_per_profitable_day_pct` (standard_2step)
are enforced too: reaching the profit target in dollar terms is necessary but not sufficient if
the program also requires N days that each individually cleared the per-day profit floor.

This is a NO-TRADING-ADVICE simulation over already-computed historical R-multiples -- it never
places, sizes, or suggests placing any live order (RESEARCH_PROTOCOL.md's "read-only against
MT5" rule is unaffected; this module doesn't touch MT5 at all)."""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd


def _simulate_one_phase(trades_r: np.ndarray, program: dict, size: float, risk_pct: float,
                         target_pct: float, max_days: int, rng: np.random.Generator) -> dict:
    """One bootstrap walk through a single evaluation phase. Returns {'passed', 'days_used',
    'failed_breach'} for this one simulated attempt at this one phase."""
    if target_pct <= 0:
        # config/prop.yaml's `instant`/`mini` programs have an empty profit_targets_pct list --
        # no evaluation phase at all (already funded) -- callers skip this function for those,
        # but guard here too rather than looping forever on an unreachable target.
        return dict(passed=True, days_used=0, failed_breach=False)

    is_trailing = program.get("max_dd_type") == "trailing"
    daily_dd_limit = float(program["daily_dd_pct"])
    max_dd_limit = float(program["max_dd_pct"])
    min_profitable_days = int(program.get("min_profitable_days_per_phase", 0))
    min_profit_per_day_pct = float(program.get("min_profit_per_profitable_day_pct", 0.0))

    balance = size
    peak_balance = size
    n_profitable_days = 0

    for day in range(1, max_days + 1):
        day_start_balance = balance
        r = rng.choice(trades_r)
        risk_dollars = balance * (risk_pct / 100.0)
        balance = balance + r * risk_dollars

        peak_balance = max(peak_balance, balance) if is_trailing else size

        day_loss_pct = max(0.0, (day_start_balance - balance) / size * 100.0)
        if day_loss_pct >= daily_dd_limit:
            return dict(passed=False, days_used=day, failed_breach=True)

        dd_from_peak_pct = max(0.0, (peak_balance - balance) / size * 100.0)
        if dd_from_peak_pct >= max_dd_limit:
            return dict(passed=False, days_used=day, failed_breach=True)

        day_pnl_pct = (balance - day_start_balance) / size * 100.0
        if day_pnl_pct >= min_profit_per_day_pct and day_pnl_pct > 0:
            n_profitable_days += 1

        total_gain_pct = (balance - size) / size * 100.0
        if total_gain_pct >= target_pct and n_profitable_days >= min_profitable_days:
            return dict(passed=True, days_used=day, failed_breach=False)

    return dict(passed=False, days_used=max_days, failed_breach=False)  # ran out of max_days


def simulate_challenge(trades_r: Sequence[float], program: dict, size: float, risk_pct: float,
                        n_sims: int = 5000, max_days: int = 250,
                        seed: Optional[int] = None) -> dict:
    """Monte Carlo's `n_sims` full attempts (every phase in `program['profit_targets_pct']`,
    sequentially, a phase failure ends the whole attempt) at ONE `risk_pct` for ONE program.

    `trades_r` must be non-empty (a model's OOS R_net values) -- raises ValueError otherwise,
    since bootstrapping from zero trades would silently simulate an undefined distribution.

    Returns {'risk_pct', 'n_sims', 'p_pass_all_phases', 'p_pass_per_phase' (list, one entry per
    phase: P(reaching at least that phase's pass), unconditional on earlier phases), 'median_days
    _to_pass' (over PASSING attempts only, nan if none passed), 'expected_attempts_to_pass' (1 /
    p_pass_all_phases = the MEAN of a geometric distribution, nan if p_pass_all_phases == 0;
    renamed from `median_attempts_to_pass` in the 2026-09-28 audit -- 1/p is the average, not the
    median)}."""
    trades_r = np.asarray(trades_r, dtype=float)
    if len(trades_r) == 0:
        raise ValueError("trades_r must be non-empty -- cannot bootstrap from zero OOS trades")

    rng = np.random.default_rng(seed)
    targets = list(program.get("profit_targets_pct") or [])
    n_phases = max(len(targets), 1)  # a 0-target program ("instant"/"mini") still counts as 1 "phase" that trivially passes

    reached_phase = np.zeros(n_phases, dtype=int)  # reached_phase[k] = attempts that passed phase k (0-indexed)
    n_pass_all = 0
    days_to_pass = []

    for _ in range(n_sims):
        total_days = 0
        all_passed = True
        if not targets:
            reached_phase[0] += 1
        else:
            for k, target_pct in enumerate(targets):
                res = _simulate_one_phase(trades_r, program, size, risk_pct, target_pct, max_days, rng)
                total_days += res["days_used"]
                if not res["passed"]:
                    all_passed = False
                    break
                reached_phase[k] += 1
        if all_passed:
            n_pass_all += 1
            days_to_pass.append(total_days)

    p_pass_all = n_pass_all / n_sims
    return dict(
        risk_pct=risk_pct, n_sims=n_sims, size=size,
        p_pass_all_phases=p_pass_all,
        p_pass_per_phase=(reached_phase / n_sims).tolist(),
        median_days_to_pass=float(np.median(days_to_pass)) if days_to_pass else float("nan"),
        expected_attempts_to_pass=(1.0 / p_pass_all) if p_pass_all > 0 else float("nan"),
    )


def sweep_risk_grid(trades_r: Sequence[float], program: dict, size: float,
                     risk_grid: Sequence[float] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5),
                     n_sims: int = 5000, max_days: int = 250,
                     seed: Optional[int] = None, fee_usd: Optional[float] = None) -> pd.DataFrame:
    """ROADMAP 8.4's own wording: "for risk 0.25-1.5%" -- runs simulate_challenge() once per
    `risk_grid` value (same `seed` reused for each, so the only thing that differs between rows
    is risk_pct, not the random draws) and returns one row per risk level.

    `fee_usd` is optional and UNVERIFIED by default (config/prop.yaml has no confirmed per-
    program challenge fee) -- pass a number you've actually checked on maven's site if you want
    an `expected_cost_usd` column; otherwise that column is left out entirely rather than
    guessing."""
    rows = []
    for risk_pct in risk_grid:
        res = simulate_challenge(trades_r, program, size, risk_pct, n_sims=n_sims,
                                  max_days=max_days, seed=seed)
        if fee_usd is not None and np.isfinite(res["expected_attempts_to_pass"]):
            res["expected_cost_usd"] = fee_usd * res["expected_attempts_to_pass"]
        rows.append(res)
    return pd.DataFrame(rows)
