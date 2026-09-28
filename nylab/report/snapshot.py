"""nylab.report.snapshot -- ROADMAP 8.1: trade snapshot PNGs for report.html's trade gallery
(nylab.report.gallery_section). Follows nylab.report.charts.py's exact conventions (THEMES,
_style(), fig_b64()) so a snapshot looks like it belongs on the same page as every other chart,
rather than introducing a second visual language or a new charting dependency (mplfinance is
available in this environment, per Phase 8 research, but every other chart in this report is
plain matplotlib -- adding a second library for one section would be visual/dependency drift for
no real benefit, since a plain OHLC bar chart shows exactly the same information).

Disclosed simplification: nylab.backtest.run_backtest's trades DataFrame does not record the
EXACT exit bar/time (only the exit PRICE and `reason`), so a snapshot draws a fixed hours-before/
after context window around the ENTRY time rather than trying to end exactly at the exit bar.
The entry/stop/target/exit levels are still drawn as horizontal price lines across that whole
window, which is enough to see whether the rule and the fill look right -- exactly what
RESEARCH_PROTOCOL.md's "always open 10-20 of those trades ... and check the rules did what you
think they did" is for."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from nylab.report.charts import THEMES, _style, fig_b64

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


def _ohlc_bars(ax, day_bars: pd.DataFrame, t: dict, tick_width_h: float = 0.03) -> None:
    """Classic OHLC bar chart (a vertical high-low line with a left open tick and a right close
    tick) drawn with plain matplotlib Line2D segments -- no extra charting library needed."""
    up = day_bars["close"] >= day_bars["open"]
    for is_up, color in ((True, t["bull"]), (False, t["bear"])):
        sub = day_bars[up == is_up]
        if len(sub) == 0:
            continue
        ax.vlines(sub["h"], sub["low"], sub["high"], color=color, linewidth=1)
        ax.hlines(sub["open"], sub["h"] - tick_width_h, sub["h"], color=color, linewidth=1)
        ax.hlines(sub["close"], sub["h"], sub["h"] + tick_width_h, color=color, linewidth=1)


def entry_hour(trade: pd.Series) -> float:
    """The trade's entry time as a day-relative NY hour. Trades from the generic engine
    (nylab.backtest.run_backtest) carry `entry_time_h` directly; trades from the frozen v0
    `london_sweep_reversal.backtest()` -- which is what `nylab run` actually reports, and whose
    trades.csv shape is pinned by the v0 golden test -- only carry `entry_time_ny` ("HH:MM").
    Audit fix 2026-09-28: the gallery used to assume `entry_time_h` and crashed `nylab run`."""
    if "entry_time_h" in trade.index and pd.notna(trade["entry_time_h"]):
        return float(trade["entry_time_h"])
    hh, mm = str(trade["entry_time_ny"]).split(":")
    return int(hh) + int(mm) / 60.0


def trade_snapshot_fig(day_bars: pd.DataFrame, trade: pd.Series, t: dict,
                        context_hours_before: float = 1.0, context_hours_after: float = 4.0):
    """`day_bars`: this trade's OWN trading day's bars (h/open/high/low/close columns, as
    produced by nylab.__main__._prepare_bars). `trade`: one row of a nylab.backtest.run_backtest
    trades DataFrame (needs entry_time_h/entry/stop/target/exit/side/reason/R_net). `t`: one of
    nylab.report.charts.THEMES's palettes."""
    entry_h = entry_hour(trade)
    lo_h, hi_h = entry_h - context_hours_before, entry_h + context_hours_after
    window = day_bars[(day_bars["h"] >= lo_h) & (day_bars["h"] <= hi_h)]
    if len(window) == 0:
        window = day_bars  # degenerate fallback (e.g. a hand-built test fixture with few bars)

    fig, ax = plt.subplots(figsize=(8, 3.4))
    _ohlc_bars(ax, window, t)

    ax.axvline(entry_h, color=t["accent"], ls="-", lw=1, label="entry")
    ax.axhline(float(trade["entry"]), color=t["accent"], ls="-", lw=1)
    ax.axhline(float(trade["stop"]), color=t["bear"], ls="--", lw=1, label="stop")
    if trade.get("target") is not None and pd.notna(trade.get("target")):
        ax.axhline(float(trade["target"]), color=t["bull"], ls="--", lw=1, label="target")
    ax.axhline(float(trade["exit"]), color=t["text"], ls=":", lw=1.2, label=f"exit ({trade.get('reason', '?')})")

    side = trade.get("side", "?")
    r_net = trade.get("R_net")
    r_txt = f"{r_net:+.2f}R" if r_net is not None and pd.notna(r_net) else "?"
    ax.set_title(f"{pd.Timestamp(trade['td']).date()} · {side} · entry {entry_h:.2f}h NY · {r_txt}", fontsize=10)
    ax.set_xlabel("NY hour"); ax.set_ylabel("price")
    ax.legend(fontsize=7, loc="best")
    _style(fig, ax, t)
    return fig


def build_gallery_figs(df: pd.DataFrame, trades: pd.DataFrame, trade_indices) -> dict:
    """Renders one snapshot PNG (light + dark, matching nylab.report.charts.build()'s own
    per-theme convention) per row of `trades` selected by `trade_indices` (positional integer
    indices into `trades`, e.g. from nylab.report.gallery_section's random/best/worst selection).
    Returns {f"trade_{i}_light": b64png, f"trade_{i}_dark": b64png, ...} keyed by the SAME
    positional index passed in, so a caller can look a snapshot back up by the row it came from."""
    if plt is None:
        return {}
    out = {}
    for i in trade_indices:
        trade = trades.loc[i]  # label lookup: gallery_section passes index LABELS (audit fix)
        day_bars = df[df["td"] == trade["td"]]
        if len(day_bars) == 0:
            continue
        for theme, t in THEMES.items():
            out[f"trade_{i}_{theme}"] = fig_b64(trade_snapshot_fig(day_bars, trade, t), bg=t["bg"])
    return out
