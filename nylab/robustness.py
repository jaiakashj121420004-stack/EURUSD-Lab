"""nylab.robustness -- ROADMAP 8.3: RESEARCH_PROTOCOL.md S5 item 4's "robustness battery",
required before any model gets a "promising" verdict. Six checks, matching that item verbatim:

1. cost x1.5 and x2 -- still positive?
2. entry delayed by 1 bar -- still positive?
3. each year separately -- no single year contributes > 50% of total R?
4. remove the best 5% of trades -- still positive?
5. Monte Carlo 10k shuffles -- 95th-percentile max drawdown in R, probability of a 20-trade
   losing stretch (sizing advice, Formula Handbook 4.x).
6. thin/gappy days excluded vs included -- similar?

Built on top of ARCHITECTURE.md S4's generic engine (nylab.backtest.run_backtest) so it works
for ANY Model plugin (nylab.models.london_sweep_reversal.LondonSweepReversalModel,
nylab.models.silver_bullet_fvg.SilverBulletFVGModel, or any future one) without re-deriving
per-model backtest logic -- checks 1/3/4/5/6 are pure post-hoc math over an existing trades
DataFrame (no re-simulation needed), check 2 re-runs the engine once with a delayed-entry
wrapper Model.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from nylab import backtest as backtest_mod
from nylab import stats as stats_mod
from nylab.data import quality as quality_mod

_EMPTY_R = pd.Series([], dtype=float)


def cost_stress(trades: pd.DataFrame, multiplier: float) -> dict:
    """Check 1: rescales each trade's ALREADY-INCURRED cost (cost_R = R_gross - R_net, which
    nylab.backtest.run_backtest computes per-trade from that trade's OWN cost_pips/risk_pips --
    so this correctly reflects whatever mix of the cost floor and the recorded spread applied
    trade by trade) by `multiplier`, without re-running the backtest. Multiplying the incurred
    cost by a stress factor IS exactly what "what if costs were `multiplier`x bigger" means --
    re-simulating would produce the identical number, since entries/exits/risk never depend on
    cost. Returns nylab.stats.r_stats() on the stressed R_net."""
    if len(trades) == 0:
        return stats_mod.r_stats(_EMPTY_R)
    stressed = trades["R_gross"] - multiplier * trades["cost_R"]
    return stats_mod.r_stats(stressed)


class DelayedEntryModel:
    """Wraps another Model so every signal's ENTRY is delayed by `delay_bars` bars: the wrapped
    model's own signal decides side/stop/target (the rule itself doesn't change), but the entry
    only happens `delay_bars` bars later, at that later bar's own close -- RESEARCH_PROTOCOL.md
    S5 item 4's "entry delayed by 1 bar" check, generalized to any Model without a second copy
    of each model's own signal logic. The stop/target stay at their original PRICE LEVELS (not
    re-derived) -- risk naturally changes because the entry price moved, which is the entire
    point of the check. If the delay pushes past `inner`'s own `window`, the engine simply never
    calls signals() again for that bar and the trade is dropped -- a legitimate "no trade"
    outcome of the delay, not a bug to special-case."""

    def __init__(self, inner, delay_bars: int = 1):
        self.inner = inner
        self.name, self.version, self.params = inner.name, inner.version, inner.params
        self.delay_bars = delay_bars
        self._pending: dict = {}  # td -> (Signal, bars_waited)
        self._dead_days: set = set()
        self.skipped_invalid = 0  # delayed entries dropped because price was already past stop/target

    def signals(self, day_bars, day, events):
        td_key = day.name
        if td_key in self._dead_days:
            return []
        if td_key in self._pending:
            sig, waited = self._pending[td_key]
            waited += 1
            if waited >= self.delay_bars:
                del self._pending[td_key]
                new_entry = float(day_bars["close"].iloc[-1])
                # Audit fix 2026-09-28: if the delay bar already closed beyond the original
                # stop (or target), the setup is dead -- nobody would enter it. Before this
                # guard, check_bar() then saw the stop "hit" on the next bar and booked an exit
                # AT the stop, which is on the PROFITABLE side of such an entry -- a fake win
                # that flattered this very robustness check. Such days are skipped and counted.
                long_ = sig.side in ("long", "buy")
                past_stop = new_entry <= sig.stop_price if long_ else new_entry >= sig.stop_price
                past_tgt = sig.target_price is not None and (
                    new_entry >= sig.target_price if long_ else new_entry <= sig.target_price)
                if past_stop or past_tgt:
                    self.skipped_invalid += 1
                    self._dead_days.add(td_key)  # the day's one setup is gone; no re-entry later
                    return []
                return [backtest_mod.Signal(bar_index=len(day_bars) - 1, side=sig.side,
                                             entry_price=new_entry, stop_price=sig.stop_price,
                                             target_price=sig.target_price, time_exit_h=sig.time_exit_h)]
            self._pending[td_key] = (sig, waited)
            return []
        sigs = self.inner.signals(day_bars, day, events)
        if sigs:
            self._pending[td_key] = (sigs[0], 0)
        return []


def per_year_contribution(trades: pd.DataFrame) -> pd.DataFrame:
    """Check 3: each year's share of TOTAL summed R_net. Flags a year whose |share| exceeds 50%
    (RESEARCH_PROTOCOL.md S5 item 4: "no single year contributes > 50% of total R")."""
    cols = ["year", "n", "total_R", "share_of_total_R", "flag_over_50pct"]
    if len(trades) == 0:
        return pd.DataFrame(columns=cols)
    yearly = trades.assign(year=pd.to_datetime(trades["td"]).dt.year).groupby("year")["R_net"].agg(
        n="size", total_R="sum")
    total = yearly["total_R"].sum()
    yearly["share_of_total_R"] = (yearly["total_R"] / total) if total != 0 else np.nan
    yearly["flag_over_50pct"] = yearly["share_of_total_R"].abs() > 0.5
    return yearly.reset_index()


def remove_best_n_pct(trades: pd.DataFrame, pct: float = 0.05) -> dict:
    """Check 4: drop the best `pct` fraction of trades by R_net (ties broken by sort order) and
    re-check expectancy -- RESEARCH_PROTOCOL.md S5 item 4: "remove the best 5% of trades -- still
    positive?"."""
    if len(trades) == 0:
        return stats_mod.r_stats(_EMPTY_R)
    n_remove = int(np.ceil(len(trades) * pct))
    kept = trades.sort_values("R_net", ascending=False).iloc[n_remove:]
    return stats_mod.r_stats(kept["R_net"])


def _max_drawdown(r: np.ndarray) -> float:
    eq = np.cumsum(r)
    running_max = np.maximum.accumulate(eq)
    return float((running_max - eq).max()) if len(eq) else 0.0


def _longest_true_run(mask: np.ndarray) -> int:
    """Longest run of consecutive True values in a 1-D boolean array, vectorized (no per-element
    Python loop) -- used per-shuffle inside monte_carlo_shuffle's 10k-iteration outer loop."""
    if not mask.any():
        return 0
    padded = np.concatenate(([False], mask, [False]))
    diffs = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diffs == 1)
    ends = np.flatnonzero(diffs == -1)
    return int((ends - starts).max())


def monte_carlo_shuffle(trades: pd.DataFrame, n_shuffles: int = 10_000, losing_streak_len: int = 20,
                         seed: Optional[int] = None) -> dict:
    """Check 5: RESEARCH_PROTOCOL.md S5 item 4: "Monte Carlo 10k shuffles -> 95th-percentile max
    drawdown in R, probability of a 20-trade losing stretch". Shuffles the ORDER of the existing
    trades' R-multiples `n_shuffles` times -- this tests SEQUENCING risk (does the actual order
    of wins/losses matter for drawdown/a losing stretch) while holding the win/loss distribution
    itself fixed at whatever it already is; it does not resample new outcomes from a fitted
    distribution."""
    r = trades["R_net"].to_numpy(dtype=float) if len(trades) else np.array([], dtype=float)
    if len(r) == 0:
        return dict(n_trades=0, n_shuffles=n_shuffles, max_dd_p95=float("nan"),
                    p_losing_streak=float("nan"), losing_streak_len=losing_streak_len)
    rng = np.random.default_rng(seed)
    max_dds = np.empty(n_shuffles)
    has_streak = np.empty(n_shuffles, dtype=bool)
    for i in range(n_shuffles):
        shuffled = rng.permutation(r)
        max_dds[i] = _max_drawdown(shuffled)
        has_streak[i] = _longest_true_run(shuffled <= 0) >= losing_streak_len
    return dict(
        n_trades=len(r), n_shuffles=n_shuffles,
        max_dd_p95=float(np.percentile(max_dds, 95)),
        p_losing_streak=float(has_streak.mean()),
        losing_streak_len=losing_streak_len,
    )


def thin_gappy_check(trades: pd.DataFrame, quality_flags: pd.DataFrame) -> dict:
    """Check 6: RESEARCH_PROTOCOL.md S5 item 4: "thin/gappy days excluded vs included --
    similar?". `quality_flags` is nylab.data.quality.flag_days()'s output (indexed by td, with
    thin_day/gappy bool columns)."""
    if len(trades) == 0:
        empty = stats_mod.r_stats(_EMPTY_R)
        return dict(included=empty, excluded=empty, n_thin_or_gappy_days_removed=0)
    flagged_days = set(quality_flags.index[quality_flags["thin_day"] | quality_flags["gappy"]])
    mask = trades["td"].isin(flagged_days)
    return dict(
        included=stats_mod.r_stats(trades["R_net"]),
        excluded=stats_mod.r_stats(trades.loc[~mask, "R_net"]),
        n_thin_or_gappy_days_removed=int(mask.sum()),
    )


def run_robustness_battery(model_factory: Callable[[], object], df: pd.DataFrame, d: pd.DataFrame,
                            pip: float, cost_pips_default: float,
                            events: pd.DataFrame | dict[str, pd.DataFrame] | None = None,
                            one_trade_per_day: bool = True, n_shuffles: int = 10_000,
                            seed: Optional[int] = None) -> dict:
    """Runs the full 6-check battery for one Model. `model_factory()` is a zero-arg callable
    returning a FRESH Model instance (same fresh-per-run reasoning as nylab.walkforward -- the
    baseline run and the delayed-entry run each need their own unpolluted per-day walk state).

    Returns {'baseline_stats', 'cost_x1_5', 'cost_x2', 'entry_delay_1bar_stats', 'per_year',
    'remove_best_5pct_stats', 'monte_carlo', 'thin_gappy', 'baseline_trades'}."""
    baseline_trades = backtest_mod.run_backtest(model_factory(), df, d, pip, cost_pips_default,
                                                 events=events, one_trade_per_day=one_trade_per_day)
    baseline_stats = stats_mod.r_stats(baseline_trades["R_net"] if len(baseline_trades) else _EMPTY_R)

    delayed_model = DelayedEntryModel(model_factory(), delay_bars=1)
    delayed_trades = backtest_mod.run_backtest(delayed_model, df, d, pip, cost_pips_default,
                                                events=events, one_trade_per_day=one_trade_per_day)
    entry_delay_stats = stats_mod.r_stats(delayed_trades["R_net"] if len(delayed_trades) else _EMPTY_R)

    quality_flags = quality_mod.flag_days(df, d["day_range"])

    return dict(
        baseline_stats=baseline_stats,
        baseline_trades=baseline_trades,
        cost_x1_5=cost_stress(baseline_trades, 1.5),
        cost_x2=cost_stress(baseline_trades, 2.0),
        entry_delay_1bar_stats=entry_delay_stats,
        entry_delay_1bar_trades=delayed_trades,
        entry_delay_1bar_skipped=delayed_model.skipped_invalid,
        per_year=per_year_contribution(baseline_trades),
        remove_best_5pct_stats=remove_best_n_pct(baseline_trades, 0.05),
        monte_carlo=monte_carlo_shuffle(baseline_trades, n_shuffles=n_shuffles, seed=seed),
        thin_gappy=thin_gappy_check(baseline_trades, quality_flags),
    )
