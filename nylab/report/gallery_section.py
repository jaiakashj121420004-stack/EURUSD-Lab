"""nylab.report.gallery_section -- ROADMAP 8.2: report.html's trade gallery (20 random OOS
trades + 5 best + 5 worst), each with a snapshot chart (nylab.report.snapshot) and an
"open in replay" deep link (nylab.report.deeplink) per ROADMAP 8.1 / the Phase 8 accept line
("user can open report.html offline, click any trade, see it in replay").

Disclosed design choice: ROADMAP 8.2's wording ("20 random OOS trades, 5 best, 5 worst") doesn't
explicitly say best/worst are OOS-only too, but this module scopes ALL THREE groups to
out-of-sample trades -- consistent with RESEARCH_PROTOCOL.md's "OOS is sacred" framing (the
in-sample trades were already used to pick the model/parameters; a gallery meant to build trust
in the RESULT should stick to the untouched sample). If Akash wants IS trades in the gallery too,
that's a one-line change to select_gallery_trades's `pool` argument."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from nylab.report import deeplink
from nylab.report import snapshot as snapshot_mod
from nylab.report.html import _chart_imgs


def select_gallery_trades(trades: pd.DataFrame, split_date, n_random: int = 20, n_best: int = 5,
                           n_worst: int = 5, seed: Optional[int] = None) -> dict:
    """Selects the gallery's trade rows from the OOS slice of `trades` (td >= split_date).
    Returns {'random': DataFrame, 'best': DataFrame, 'worst': DataFrame} -- each keeps its
    ORIGINAL positional index from `trades` (never reset), since nylab.report.snapshot
    .build_gallery_figs looks trades up by that same positional index."""
    if len(trades) == 0:
        empty = trades.iloc[0:0]
        return dict(random=empty, best=empty, worst=empty)
    oos = trades[trades["td"] >= split_date]
    if len(oos) == 0:
        empty = trades.iloc[0:0]
        return dict(random=empty, best=empty, worst=empty)
    rng = np.random.default_rng(seed)
    n_random = min(n_random, len(oos))
    random_idx = rng.choice(oos.index.to_numpy(), size=n_random, replace=False) if n_random else np.array([])
    best = oos.sort_values("R_net", ascending=False).head(n_best)
    worst = oos.sort_values("R_net", ascending=True).head(n_worst)
    return dict(
        random=oos.loc[sorted(random_idx)] if len(random_idx) else oos.iloc[0:0],
        best=best, worst=worst,
    )


def _trade_row_html(idx: int, trade: pd.Series, figs: dict, replay_host: str, replay_port: int) -> str:
    url = deeplink.replay_url(trade["td"], snapshot_mod.entry_hour(trade), host=replay_host, port=replay_port)
    r_net = trade.get("R_net")
    r_txt = f"{r_net:+.2f}R" if r_net is not None and pd.notna(r_net) else "—"
    return (
        f"<div class='gallery-card'>"
        f"<div class='gallery-imgs'>{_chart_imgs(figs, f'trade_{idx}')}</div>"
        f"<div class='gallery-meta'><b>{pd.Timestamp(trade['td']).date()}</b> · {trade.get('side', '?')} · "
        f"entry {snapshot_mod.entry_hour(trade):.2f}h NY · {r_txt} · reason: {trade.get('reason', '?')}<br>"
        f"<a href='{url}' target='_blank' rel='noopener'>Open in replay ↗</a></div></div>"
    )


def build_figs(df: pd.DataFrame, trades: pd.DataFrame, split_date, n_random: int = 20,
               n_best: int = 5, n_worst: int = 5, seed: Optional[int] = None) -> dict:
    """Renders every gallery trade's snapshot PNGs (nylab.report.snapshot.build_gallery_figs) --
    call this ONCE, merge its result into the report's shared `figs` dict (same convention as
    nylab.report.sessions_section.build_figs), THEN call build() with the same selection args
    (same `seed` -- the two calls must agree on which trades were picked)."""
    selection = select_gallery_trades(trades, split_date, n_random, n_best, n_worst, seed)
    all_idx = sorted(set(selection["random"].index) | set(selection["best"].index) | set(selection["worst"].index))
    return snapshot_mod.build_gallery_figs(df, trades, all_idx)


def build(trades: pd.DataFrame, split_date, figs: dict, n_random: int = 20, n_best: int = 5,
          n_worst: int = 5, seed: Optional[int] = None, replay_host: str = "127.0.0.1",
          replay_port: int = 8765, all_trades_href: Optional[str] = None) -> str:
    """Returns the HTML fragment for report.html's trade gallery section. `figs` must already
    contain this same selection's snapshots (see build_figs above).

    `all_trades_href` (ROADMAP 8.1 audit fix, 2026-09-28): "every backtest trade" needs an
    open-in-replay link, not just this gallery's 30 -- pass the relative path to the separate
    nylab.report.trades_page page (e.g. "trades.html") to link to it here; omitted, no link is
    shown (keeps this module usable standalone / in tests without that page existing)."""
    selection = select_gallery_trades(trades, split_date, n_random, n_best, n_worst, seed)
    h = ["<h2>11 · Trade gallery (out-of-sample)</h2>",
         "<p class='muted'>Every chart below is out-of-sample -- trades the model/parameters were never "
         "chosen to fit. Click a trade's replay link to see the exact bars in the replay trainer "
         "(REPLAY_TRAINER.md) and confirm the rule did what this snapshot suggests it did.</p>"]
    if all_trades_href:
        h.append(f"<p><a href='{all_trades_href}'>Open in replay ↗ -- every backtest trade "
                 f"({len(trades)}), not just the gallery below</a></p>")
    for title, key in (("Random sample", "random"), ("Best", "best"), ("Worst", "worst")):
        group = selection[key]
        h.append(f"<h3>{title} ({len(group)})</h3>")
        if len(group) == 0:
            h.append("<p class='muted'>No out-of-sample trades available.</p>")
            continue
        h.append("<div class='gallery-grid'>")
        for idx, trade in group.iterrows():
            h.append(_trade_row_html(idx, trade, figs, replay_host, replay_port))
        h.append("</div>")
    return "\n".join(h)
