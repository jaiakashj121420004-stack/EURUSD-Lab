"""nylab.walkforward -- ROADMAP 7.7: a rolling/expanding walk-forward evaluator for a Model
(ARCHITECTURE.md S4). Splits the trading days in `d` into consecutive folds -- each fold has an
IS (in-sample) span followed by an OOS (out-of-sample) span -- and runs nylab.backtest.run_backtest
once per fold, restricted to that fold's own IS+OOS days, then reports per-fold IS/OOS
nylab.stats.r_stats() plus an aggregated OOS stats dict pooling every fold's OOS trades together.

This is walk-FORWARD, not k-fold cross-validation: folds always advance in time (RESEARCH_PROTOCOL
.md's "OOS is sacred" -- every fold's OOS trades are trades a trader running this model live would
genuinely not have seen yet at the time that fold's IS window ended). Pooling every fold's OOS
trades into one aggregate stat is what turns "one lucky/unlucky OOS window" into "the model's OOS
performance across the WHOLE multi-year history, evaluated one forward step at a time".

Two fold modes:
- 'rolling':   a FIXED-WIDTH IS window that slides forward each fold (old IS days drop off the
               front as new ones are added) -- tests whether the rule holds up under a stable,
               recent-history-only view, which is closer to how a live trader would actually
               operate (they don't remember 2019 forever).
- 'expanding': the IS window always starts at day 0 and grows every fold -- every fold's IS is a
               strict superset of the previous fold's. Tests whether the rule holds up as MORE
               history accumulates.

Phase 7's models (nylab.models.london_sweep_reversal, nylab.models.silver_bullet_fvg) have no
free parameters to refit per fold -- there is no "training" step here in the ML sense.
`model_factory` exists purely so each fold gets a FRESH Model instance: SilverBulletFVGModel/
LondonSweepReversalModel both carry per-trading-day walk state (`_committed`/`_done_days`/
`_abandoned_days`) across `signals()` calls within a single nylab.backtest.run_backtest run, and
reusing one instance across folds would let one fold's leftover state (for a `td` that happens to
recur, or just stale bookkeeping) bleed into the next fold's results.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from nylab import backtest as backtest_mod
from nylab import stats as stats_mod


def make_folds(day_index: pd.DatetimeIndex, is_days: int, oos_days: int, mode: str = "rolling") -> list[dict]:
    """Splits a (possibly unsorted) DatetimeIndex of trading days into non-overlapping,
    consecutive folds. Each fold is {'is_start','is_end','oos_start','oos_end'} (pd.Timestamp,
    both ends inclusive) -- `is_days` trading days followed immediately by `oos_days` trading
    days, walking forward across the whole series with no gaps and no overlap between one fold's
    OOS span and the next fold's IS span (the next fold's IS starts exactly where this fold's OOS
    ended, in 'rolling' mode; in 'expanding' mode the next fold's IS additionally swallows this
    fold's whole OOS span too).

    `mode`: 'rolling' (fixed-width IS, slides forward) or 'expanding' (IS always starts at day 0).
    Returns an empty list if there isn't enough history for even one fold."""
    if mode not in ("rolling", "expanding"):
        raise ValueError(f"mode must be 'rolling' or 'expanding', got {mode!r}")
    days = pd.DatetimeIndex(sorted(day_index))
    n = len(days)
    folds = []
    oos_start_pos = is_days
    while oos_start_pos + oos_days <= n:
        is_start_pos = 0 if mode == "expanding" else max(0, oos_start_pos - is_days)
        oos_end_pos = oos_start_pos + oos_days - 1
        folds.append(dict(
            is_start=days[is_start_pos], is_end=days[oos_start_pos - 1],
            oos_start=days[oos_start_pos], oos_end=days[oos_end_pos],
        ))
        oos_start_pos += oos_days
    return folds


def run_walkforward(model_factory: Callable[[], object], df: pd.DataFrame, d: pd.DataFrame,
                     pip: float, cost_pips_default: float, is_days: int, oos_days: int,
                     mode: str = "rolling",
                     events: pd.DataFrame | dict[str, pd.DataFrame] | None = None,
                     one_trade_per_day: bool = True) -> dict:
    """Runs `model_factory()` (a zero-arg callable returning a FRESH Model instance each time --
    see module docstring) once per fold from `make_folds(d.index, is_days, oos_days, mode)`. Each
    fold's nylab.backtest.run_backtest call is restricted to `df`/`d` rows within that fold's own
    [is_start, oos_end] span (a later fold's OOS days are invisible to an earlier fold's run, and
    an earlier fold's IS-only days are dropped from a later fold in 'rolling' mode -- no
    across-fold leakage of bar data either, not just of model state).

    `events` is passed through to every fold's run_backtest call UNCHANGED (not re-sliced per
    fold): event tables (nylab.events.detect_mss/fvg_lifecycle output) are global bar-position-
    indexed and run_backtest already restricts which `td`s it ever looks up per fold via `d`, so
    there is nothing to gain and real complexity to lose by re-slicing them here too.

    Returns {'folds': [{'is_start','is_end','oos_start','oos_end','is_trades','is_stats',
    'oos_trades','oos_stats'}, ...], 'oos_pooled_trades': every fold's OOS trades concatenated,
    'oos_pooled_stats': nylab.stats.r_stats() over that pooled set}."""
    folds = make_folds(d.index, is_days, oos_days, mode)
    out_folds = []
    pooled_oos = []

    for f in folds:
        span_mask = (df["td"] >= f["is_start"]) & (df["td"] <= f["oos_end"])
        df_span = df[span_mask]
        d_span = d[(d.index >= f["is_start"]) & (d.index <= f["oos_end"])]

        model = model_factory()
        trades = backtest_mod.run_backtest(model, df_span, d_span, pip, cost_pips_default,
                                            events=events, one_trade_per_day=one_trade_per_day)
        if len(trades):
            is_trades = trades[trades["td"] <= f["is_end"]]
            oos_trades = trades[trades["td"] >= f["oos_start"]]
        else:
            is_trades = trades
            oos_trades = trades

        # run_backtest returns pd.DataFrame([]) (no columns at all) when it finds zero trades
        # -- indexing ["R_net"] on that would KeyError, so guard with an explicit empty Series.
        is_r = is_trades["R_net"] if len(is_trades) else pd.Series([], dtype=float)
        oos_r = oos_trades["R_net"] if len(oos_trades) else pd.Series([], dtype=float)
        out_folds.append(dict(
            is_start=f["is_start"], is_end=f["is_end"],
            oos_start=f["oos_start"], oos_end=f["oos_end"],
            is_trades=is_trades, is_stats=stats_mod.r_stats(is_r),
            oos_trades=oos_trades, oos_stats=stats_mod.r_stats(oos_r),
        ))
        pooled_oos.append(oos_trades)

    pooled_trades = pd.concat(pooled_oos, ignore_index=True) if pooled_oos else pd.DataFrame()
    pooled_r = pooled_trades["R_net"] if len(pooled_trades) else pd.Series([], dtype=float)
    pooled_stats = stats_mod.r_stats(pooled_r)
    return dict(folds=out_folds, oos_pooled_trades=pooled_trades, oos_pooled_stats=pooled_stats)
