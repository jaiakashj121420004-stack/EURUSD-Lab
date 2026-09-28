"""nylab.report.trades_page -- ROADMAP 8.1 audit fix (2026-09-28): an "open in replay" link for
EVERY backtest trade, not just the 30 in report.html's gallery (nylab.report.gallery_section).

A PNG snapshot per trade for ~640 trades would bloat report.html (disclosed choice, HANDOFF.md
S4 step 1: "PNGs for all ~640 trades would bloat the HTML ... ask Akash which he prefers" --
Akash had no preference, so this keeps the lighter option: a plain sortable-by-eye table with a
replay deep link per row, as its own page (trades.html) next to report.html, linked from the
gallery section. No snapshot images here at all -- the gallery already has those for a sample.
"""
from __future__ import annotations

import pandas as pd

from nylab.report import deeplink
from nylab.report.html import _css
from nylab.report.snapshot import entry_hour


def _row_html(idx: int, trade: pd.Series, is_oos: bool, replay_host: str, replay_port: int) -> str:
    url = deeplink.replay_url(trade["td"], entry_hour(trade), host=replay_host, port=replay_port)
    r_net = trade.get("R_net")
    r_txt = f"{r_net:+.2f}R" if r_net is not None and pd.notna(r_net) else "—"
    sample = "OOS" if is_oos else "IS"
    return (f"<tr><td>{pd.Timestamp(trade['td']).date()}</td><td>{trade.get('side', '?')}</td>"
            f"<td>{entry_hour(trade):.2f}h NY</td><td>{r_txt}</td><td>{trade.get('reason', '?')}</td>"
            f"<td>{sample}</td><td><a href='{url}' target='_blank' rel='noopener'>Open in replay ↗</a></td></tr>")


def build(trades: pd.DataFrame, split_date, replay_host: str = "127.0.0.1", replay_port: int = 8765) -> str:
    """Returns a full standalone HTML page (its own <html>...</html>, same CSS tokens as
    report.html so it doesn't look like a different tool) listing every row of `trades` with a
    replay deep link. Rows are in the same order as trades.csv (chronological)."""
    rows = "\n".join(_row_html(i, t, t["td"] >= split_date, replay_host, replay_port)
                      for i, t in trades.iterrows())
    n_oos = int((trades["td"] >= split_date).sum())
    return f"""<html><head><meta charset='utf-8'><title>All trades — EURUSD Session Lab</title>
<style>{_css()}</style></head><body>
<h1>All backtest trades</h1>
<div class='muted'>{len(trades)} trades total ({n_oos} out-of-sample, {len(trades) - n_oos} in-sample) ·
<a href='report.html'>← back to report.html</a></div>
<div class='box info'>Every row below is a real backtest trade, in chronological order. Click "Open in
replay" to see the exact bars in the replay trainer and confirm the rule did what the row says it did.
This page has no charts of its own -- report.html's trade gallery (section 11) has snapshot images for
a sample of these.</div>
<table><tr><th>Day</th><th>Side</th><th>Entry (NY)</th><th>R (net)</th><th>Reason</th><th>Sample</th><th></th></tr>
{rows}
</table>
<div class='footer-note'>Not financial advice -- this is a research report, no live trading, read-only
against MT5. Every number above is historical; nothing here is a recommendation to trade anything live.</div>
</body></html>"""
