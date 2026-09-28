"""ROADMAP 8.4: nylab.maven_sim -- the Maven pass simulator (bootstrap Monte Carlo)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nylab import maven_sim


SIMPLE_PROGRAM = dict(profit_targets_pct=[8], max_dd_pct=8, max_dd_type="static_balance",
                       daily_dd_pct=4)
TWO_STEP_PROGRAM = dict(profit_targets_pct=[8, 5], max_dd_pct=8, max_dd_type="static_balance",
                         daily_dd_pct=4, min_profitable_days_per_phase=3,
                         min_profit_per_profitable_day_pct=0.5)
ZERO_TARGET_PROGRAM = dict(profit_targets_pct=[], max_dd_pct=3, max_dd_type="trailing",
                            daily_dd_pct=2)


def test_simulate_challenge_raises_on_empty_trades():
    with pytest.raises(ValueError):
        maven_sim.simulate_challenge([], SIMPLE_PROGRAM, size=10000, risk_pct=0.5, n_sims=10)


def test_simulate_challenge_zero_target_program_always_passes_with_zero_days():
    out = maven_sim.simulate_challenge([0.5, -1.0], ZERO_TARGET_PROGRAM, size=10000, risk_pct=0.5,
                                        n_sims=20, seed=1)
    assert out["p_pass_all_phases"] == 1.0
    assert out["median_days_to_pass"] == 0.0


def test_simulate_challenge_all_winners_passes_quickly_and_often():
    # every trade is +3R -- at a reasonable risk_pct this should reach an 8% target fast and
    # never breach a drawdown (there are no losses at all).
    trades_r = [3.0] * 50
    out = maven_sim.simulate_challenge(trades_r, SIMPLE_PROGRAM, size=10000, risk_pct=1.0,
                                        n_sims=200, seed=2)
    assert out["p_pass_all_phases"] == 1.0
    assert out["median_days_to_pass"] >= 1
    assert out["expected_attempts_to_pass"] == pytest.approx(1.0)


def test_simulate_challenge_all_losers_never_passes():
    trades_r = [-1.0] * 50
    out = maven_sim.simulate_challenge(trades_r, SIMPLE_PROGRAM, size=10000, risk_pct=1.0,
                                        n_sims=100, seed=3)
    assert out["p_pass_all_phases"] == 0.0
    assert np.isnan(out["median_days_to_pass"])
    assert np.isnan(out["expected_attempts_to_pass"])


def test_simulate_challenge_higher_risk_breaches_drawdown_faster_on_losers():
    # a run of losses breaches the 8% max DD (static_balance) faster at higher risk_pct.
    trades_r = [-1.0] * 100
    low_risk = maven_sim.simulate_challenge(trades_r, SIMPLE_PROGRAM, size=10000, risk_pct=0.25,
                                             n_sims=50, seed=4, max_days=100)
    high_risk = maven_sim.simulate_challenge(trades_r, SIMPLE_PROGRAM, size=10000, risk_pct=1.5,
                                              n_sims=50, seed=4, max_days=100)
    # both fail every attempt (all losers), but higher risk should breach in fewer days.
    # median_days_to_pass is nan since nobody passes -- instead check via the phase-0 mechanics
    # directly by simulating one phase.
    rng = np.random.default_rng(0)
    lo = maven_sim._simulate_one_phase(np.array(trades_r), SIMPLE_PROGRAM, 10000, 0.25, 8, 200, rng)
    rng = np.random.default_rng(0)
    hi = maven_sim._simulate_one_phase(np.array(trades_r), SIMPLE_PROGRAM, 10000, 1.5, 8, 200, rng)
    assert hi["days_used"] <= lo["days_used"]
    assert hi["failed_breach"] and lo["failed_breach"]


def test_two_step_program_requires_min_profitable_days_before_passing():
    """A single day's gain that already clears the 8% target should NOT pass the phase until
    min_profitable_days_per_phase (3) qualifying days have occurred."""
    # First trade: a single huge win that instantly exceeds 8% in one day. Since that's only
    # 1 profitable day (< 3 required), the phase must keep going -- feed it 2 more small wins
    # afterward so it eventually satisfies the day-count rule.
    trades_r = [20.0, 0.6, 0.6, 0.6] + [0.0] * 50
    rng = np.random.default_rng(0)
    # Force deterministic order by using a tiny pool sampled with replacement -- with only these
    # values, rng.choice will still sample randomly, so instead directly test the day-count logic
    # by constructing a scenario where ALL trades are identical big wins (guarantees $ target hit
    # on day 1, and day-count rule needs 3 days regardless of order).
    trades_r_big = [20.0] * 10
    res = maven_sim._simulate_one_phase(np.array(trades_r_big), TWO_STEP_PROGRAM, 10000, 1.0,
                                         target_pct=8, max_days=10, rng=np.random.default_rng(1))
    assert res["passed"]
    assert res["days_used"] >= 3  # can't pass on day 1 even though $ target was hit on day 1


def test_sweep_risk_grid_returns_one_row_per_risk_level_with_expected_columns():
    trades_r = np.random.default_rng(5).normal(0.1, 1.0, 80)
    df = maven_sim.sweep_risk_grid(trades_r, SIMPLE_PROGRAM, size=10000,
                                    risk_grid=(0.25, 0.5, 1.0), n_sims=200, seed=9)
    assert len(df) == 3
    assert list(df["risk_pct"]) == [0.25, 0.5, 1.0]
    assert "p_pass_all_phases" in df.columns
    assert "expected_cost_usd" not in df.columns  # fee_usd not supplied


def test_sweep_risk_grid_adds_expected_cost_when_fee_given():
    trades_r = [3.0] * 30
    df = maven_sim.sweep_risk_grid(trades_r, SIMPLE_PROGRAM, size=10000, risk_grid=(1.0,),
                                    n_sims=50, seed=1, fee_usd=23.0)
    assert "expected_cost_usd" in df.columns
    row = df.iloc[0]
    assert row["expected_cost_usd"] == pytest.approx(23.0 * row["expected_attempts_to_pass"])


def test_simulate_challenge_deterministic_with_seed():
    trades_r = np.random.default_rng(1).normal(0.05, 1.0, 60)
    a = maven_sim.simulate_challenge(trades_r, TWO_STEP_PROGRAM, size=5000, risk_pct=0.5,
                                      n_sims=300, seed=123)
    b = maven_sim.simulate_challenge(trades_r, TWO_STEP_PROGRAM, size=5000, risk_pct=0.5,
                                      n_sims=300, seed=123)
    assert a == b


class _FixedSequenceRng:
    """Stand-in for np.random.Generator that returns a pre-set sequence from .choice(), so a
    day-by-day scenario can be constructed deterministically instead of hoping a real RNG draws
    a particular order."""
    def __init__(self, sequence):
        self._seq = list(sequence)
        self._i = 0

    def choice(self, arr):
        val = self._seq[self._i]
        self._i += 1
        return val


def test_trailing_max_dd_type_lets_peak_run_up_with_equity():
    """A trailing program's peak tracks equity upward, so a big early win followed by a pullback
    is measured against the NEW higher peak, not the original size -- a pullback that a
    static_balance program would tolerate (measured from the original size) can breach a
    trailing program's max DD (measured from the higher post-win peak)."""
    # Day 1: +20% (balance 10000 -> 12000, peak becomes 12000 under trailing).
    # Days 2+: -1% of CURRENT balance each day.
    # Under trailing (max_dd_pct=3, peak=12000): dropping just above 3% of 12000 (~360) from the
    # peak breaches -- balance 12000 -> 11640 is a ~3% pullback FROM THE PEAK, well within reach.
    # Under static_balance (peak fixed at 10000): balance would have to fall a further ~2000
    # below the ORIGINAL 10000 to breach the same 3%, which -1%-per-day compounding on ~10000+
    # never reaches within a handful of days.
    # target_pct=25 is deliberately ABOVE day 1's 20% gain so neither run passes immediately --
    # the point is to see what the SUBSEQUENT pullback does to each program's drawdown check.
    trailing = dict(profit_targets_pct=[25], max_dd_pct=3, max_dd_type="trailing", daily_dd_pct=50)
    static = dict(profit_targets_pct=[25], max_dd_pct=3, max_dd_type="static_balance", daily_dd_pct=50)
    sequence = [20.0] + [-1.0] * 20

    rng_t = _FixedSequenceRng(sequence)
    res_trailing = maven_sim._simulate_one_phase(np.array(sequence), trailing, 10000, 1.0, 25, 15, rng_t)
    rng_s = _FixedSequenceRng(sequence)
    res_static = maven_sim._simulate_one_phase(np.array(sequence), static, 10000, 1.0, 25, 15, rng_s)

    assert res_trailing["failed_breach"]
    assert not res_static["failed_breach"]
