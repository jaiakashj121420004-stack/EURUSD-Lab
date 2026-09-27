"""nylab.backtest -- ROADMAP 7.4: the generic bar-by-bar backtest engine (ARCHITECTURE.md S4's
Model plugin interface). Every model from Phase 7 onward (nylab.models.silver_bullet_fvg, and
london_sweep_reversal's new Model-plugin form) is run through THIS engine, so there is exactly
one implementation of "walk bars forward, apply the conservative same-bar fill rule, respect the
time exit, subtract costs" -- not one per model, which is how look-ahead and fill-rule bugs
creep in one model at a time.

Conservative same-bar fills are delegated to nylab.replay.sim (check_bar/compute_r) -- the SAME
functions REPLAY_TRAINER.md's practice-trade fill engine uses ("Fill engine = the same backtest
engine rules"), so a manual practice trade and a coded model's trade are judged identically, not
by two independently-maintained implementations of "did this bar hit the stop or the target".

Models never see future bars: for every candidate bar `i`, the engine calls
`model.signals(day_bars.iloc[:i+1], day, events_upto_i)` -- the "slow but safe" rule
ARCHITECTURE.md S4 describes literally. The one performance concession (documented, not a
look-ahead risk): the engine only asks bars whose NY hour falls inside the model's own declared
`params['window']` -- every ICT model in this project is session-window scoped anyway, and a
model returning [] for the other ~250 bars/day would cost the same wall-clock time to compute
as not asking at all, just slower.
"""
from __future__ import annotations

import dataclasses
from typing import Optional, Protocol

import numpy as np
import pandas as pd

from nylab import hyp_dsl
from nylab import stats as stats_mod
from nylab.replay import sim


@dataclasses.dataclass
class Signal:
    bar_index: int                  # position WITHIN day_bars (0-based, matches iloc)
    side: str                       # 'long' | 'short'
    entry_price: float
    stop_price: float
    target_price: Optional[float]   # None -> no fixed target, time-exit or another rule decides
    time_exit_h: float              # flat by this NY hour (day-relative), same convention as `h`


class Model(Protocol):
    name: str
    version: str
    params: dict

    def signals(self, day_bars: pd.DataFrame, day: pd.Series, events: pd.DataFrame) -> list[Signal]:
        ...


def run_backtest(model: Model, df: pd.DataFrame, d: pd.DataFrame, pip: float,
                  cost_pips_default: float,
                  events: pd.DataFrame | dict[str, pd.DataFrame] | None = None,
                  one_trade_per_day: bool = True) -> pd.DataFrame:
    """Runs `model` over every trading day in `d`, returns a trades DataFrame with the same
    column shape nylab.models.london_sweep_reversal.backtest() already produces (td, side,
    entry, stop, target, exit, reason, risk_pips, R_gross, R_net, cost_R) -- so existing
    reporting/stats code (nylab.stats.r_stats, the report builder) works on either unchanged.

    `events` (optional): Phase 7.2/7.3 event table(s) already computed over the FULL continuous
    series -- either a single DataFrame (sliced per-day and passed to the model as
    `events[events.td == td]`), or a dict of named tables (e.g. {'mss': ..., 'fvg': ...} for
    nylab.models.silver_bullet_fvg, which needs both) each sliced the same way and passed to the
    model as a matching dict. `df` (and therefore `day_bars`) deliberately keeps its ORIGINAL
    RangeIndex positions rather than resetting per day -- an event table's extreme_idx/mss_idx/
    bar_idx columns are bar positions in that SAME global series, so a model can compare them
    directly against day_bars.index without any per-day position translation."""
    lo_w, hi_w = model.params.get("window", (0.0, 24.0))
    time_exit_h = model.params.get("time_exit", hi_w)
    max_hold_h = model.params.get("max_hold_h", 24.0)

    def _slice_events(tbl, td):
        if tbl is None or len(tbl) == 0:
            return tbl if tbl is not None else pd.DataFrame()
        if "td" not in tbl.columns:
            # Some event tables (e.g. nylab.events.fvg_lifecycle's output) aren't day-scoped --
            # an FVG a model looks up by bar_idx can have been created on an earlier day than
            # the one currently being walked, so there is nothing sensible to slice by `td`
            # here; pass the whole table through and let the model filter by bar position.
            return tbl
        return tbl[tbl["td"] == td]

    trades = []
    for td, day_bars in df.groupby("td"):
        if td not in d.index:
            continue
        day = d.loc[td]
        if isinstance(events, dict):
            day_events = {name: _slice_events(tbl, td) for name, tbl in events.items()}
        else:
            day_events = _slice_events(events, td)

        candidate_positions = np.flatnonzero(
            (day_bars["h"].to_numpy() >= lo_w) & (day_bars["h"].to_numpy() < hi_w)
        )
        signal = None
        for i in candidate_positions:
            partial = day_bars.iloc[: i + 1]
            sigs = model.signals(partial, day, day_events)
            if sigs:
                signal = sigs[0]
                break
            if signal is not None and one_trade_per_day:
                break

        if signal is None:
            continue

        # Manage the trade forward from the bar AFTER the signal bar (the signal's own entry
        # price is assumed fillable at/after its own bar's close -- same convention
        # london_sweep_reversal.backtest() already used: "enter at that close").
        exit_px, reason = None, "time"
        j_last = signal.bar_index
        for j in range(signal.bar_index + 1, len(day_bars)):
            h = day_bars["h"].iloc[j]
            if h >= time_exit_h or h >= lo_w + max_hold_h:
                break
            bar = dict(high=day_bars["high"].iloc[j], low=day_bars["low"].iloc[j])
            side_word = "long" if signal.side in ("long", "buy") else "short"
            check = sim.check_bar(dict(side=side_word, sl=signal.stop_price, tp=signal.target_price), bar)
            j_last = j
            if check["filled"]:
                exit_px, reason = check["exit"], check["reason"]
                break
        if exit_px is None:
            exit_px = day_bars["close"].iloc[j_last] if j_last < len(day_bars) else day_bars["close"].iloc[-1]

        spread_pips = None
        if "spread_pts" in day_bars.columns:
            sp = day_bars["spread_pts"].iloc[signal.bar_index]
            if pd.notna(sp):
                spread_pips = float(sp) / 10.0
        cost_pips = max(cost_pips_default, (spread_pips or 0) + 0.2)

        r = sim.compute_r(signal.side if signal.side in ("long", "short") else ("long" if signal.side == "buy" else "short"),
                           signal.entry_price, exit_px, signal.stop_price, cost_pips, pip)
        trades.append(dict(
            td=td, side=signal.side, entry_time_h=float(day_bars["h"].iloc[signal.bar_index]),
            entry=signal.entry_price, stop=signal.stop_price, target=signal.target_price,
            exit=exit_px, reason=reason,
            risk_pips=r["risk_pips"], R_gross=r["R_gross"], R_net=r["R_net"],
            cost_R=(r["R_gross"] - r["R_net"]),
        ))
    return pd.DataFrame(trades)


def _context_mask(expr: str, d: pd.DataFrame) -> pd.Series:
    """Evaluates a `context_filter:` DSL string (SESSIONS_AND_CONTEXT.md S5.3) against the DAY
    table `d`, returning a boolean Series aligned to `d.index`. Reuses nylab.hyp_dsl's safe
    whitelist evaluator -- the SAME parser/evaluator every hypothesis YAML's condition/outcome
    already goes through (nylab.hyp_engine's own `_mask` does this identical
    parse-then-coerce-to-bool dance; duplicated here as four lines rather than importing a
    leading-underscore "private" helper from another module). NaN (missing/not-yet-available
    data) coerces to False, same convention as nylab.hyp_engine._mask -- a day the filter can't
    evaluate is treated as not matching, never as matching by default."""
    ns = {col: d[col] for col in d.columns}
    val = hyp_dsl.evaluate(expr, ns)
    if not isinstance(val, pd.Series):
        val = pd.Series(val, index=d.index)
    return val.reindex(d.index).fillna(False).astype(bool)


def run_backtest_with_context_filter(model: Model, df: pd.DataFrame, d: pd.DataFrame, pip: float,
                                      cost_pips_default: float,
                                      context_filter: str | None = None,
                                      events: pd.DataFrame | dict[str, pd.DataFrame] | None = None,
                                      one_trade_per_day: bool = True) -> dict:
    """ROADMAP 7.5's `context_filter` support (SESSIONS_AND_CONTEXT.md S5.3): "Models accept
    context_filter: (DSL) in YAML; results are always reported for filtered vs unfiltered vs
    complement, with the filter counted as one extra test per filter tried."

    Runs `model` through run_backtest exactly once (the filter is a POST-hoc split of the same
    trade list, not a second backtest run -- a trade's entry/exit/R is identical whichever bucket
    it lands in) and partitions the resulting trades by whether `context_filter` evaluates True
    for that trade's `td` in `d`. When `context_filter` is None, `filtered`/`complement` are both
    the same as `unfiltered` (nothing to split on) -- callers can always destructure the same
    three keys either way.

    Returns {'unfiltered': (trades_df, r_stats_dict), 'filtered': (...), 'complement': (...)}."""
    trades = run_backtest(model, df, d, pip, cost_pips_default, events=events,
                           one_trade_per_day=one_trade_per_day)
    unfiltered = (trades, stats_mod.r_stats(trades["R_net"] if len(trades) else pd.Series([], dtype=float)))

    if context_filter is None:
        return dict(unfiltered=unfiltered, filtered=unfiltered, complement=unfiltered)

    mask = _context_mask(context_filter, d)
    if len(trades):
        matches = trades["td"].map(mask).fillna(False).astype(bool)
        filtered_trades, complement_trades = trades[matches], trades[~matches]
    else:
        filtered_trades = complement_trades = trades

    return dict(
        unfiltered=unfiltered,
        filtered=(filtered_trades, stats_mod.r_stats(filtered_trades["R_net"] if len(filtered_trades) else pd.Series([], dtype=float))),
        complement=(complement_trades, stats_mod.r_stats(complement_trades["R_net"] if len(complement_trades) else pd.Series([], dtype=float))),
    )
