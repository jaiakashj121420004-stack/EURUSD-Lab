"""nylab.report.hand_check -- HANDOFF.md S4 Step 3 / ROADMAP Phase 7's own remaining item
("Akash's manual check of 10 FVGs + 10 sweeps"): a small, standalone HTML page that samples a
fixed number of FVGs and sweeps from the Phase 7.2/7.3 events table
(nylab.events_report.build_events_table) and gives each one a replay deep link, so Akash can
open the exact bars in the replay trainer and confirm the detector did what the row says it did.

Deliberately simpler than nylab.label_validate's review page: that one collects graded
agree/disagree answers back through a JSON round trip because ROADMAP 5.6 needed a scored,
repeatable 80%-agreement bar. This is a one-off spot-check with no accept threshold of its own
(HANDOFF S4 Step 3: "record his verdicts in PROGRESS; investigate any disagreement against
FEATURES_SPEC before changing code") -- a plain list with replay links is all it needs to be.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab.report import deeplink
from nylab.report.html import _css


def _bar_td_h(df: pd.DataFrame, bar_idx: int) -> tuple:
    row = df.iloc[int(bar_idx)]
    return row["td"], float(row["h"])


def sample_fvgs(fvg: pd.DataFrame, df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Samples up to `n` FVG rows, stratified bull/bear as evenly as the pool allows (so a
    lopsided bull/bear split in the data doesn't silently produce an all-bull or all-bear
    sample) -- deterministic for a fixed seed."""
    if not len(fvg):
        return fvg
    rng = np.random.default_rng(seed)
    parts = []
    groups = list(fvg.groupby("direction"))
    per_group = max(1, n // max(1, len(groups)))
    for _, g in groups:
        k = min(per_group, len(g))
        idx = rng.choice(g.index.to_numpy(), size=k, replace=False)
        parts.append(g.loc[idx])
    out = pd.concat(parts) if parts else fvg.iloc[0:0]
    if len(out) < n:
        remaining = fvg.drop(out.index)
        extra_n = min(n - len(out), len(remaining))
        if extra_n:
            extra_idx = rng.choice(remaining.index.to_numpy(), size=extra_n, replace=False)
            out = pd.concat([out, remaining.loc[extra_idx]])
    tds, hs = zip(*(_bar_td_h(df, i) for i in out["bar_idx"])) if len(out) else ((), ())
    out = out.copy()
    out["td"] = tds
    out["h"] = hs
    return out.sort_values("t").reset_index(drop=True).head(n)


def sample_sweeps(raids: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Samples up to `n` sweep-type raids (raid_type == 'sweep'), stratified across sessions as
    evenly as the pool allows, same reasoning as sample_fvgs."""
    sweeps = raids[raids["raid_type"] == "sweep"] if len(raids) else raids
    if not len(sweeps):
        return sweeps
    rng = np.random.default_rng(seed + 1)  # separate stream from sample_fvgs
    parts = []
    groups = list(sweeps.groupby("session"))
    per_group = max(1, n // max(1, len(groups)))
    for _, g in groups:
        k = min(per_group, len(g))
        idx = rng.choice(g.index.to_numpy(), size=k, replace=False)
        parts.append(g.loc[idx])
    out = pd.concat(parts) if parts else sweeps.iloc[0:0]
    if len(out) < n:
        remaining = sweeps.drop(out.index)
        extra_n = min(n - len(out), len(remaining))
        if extra_n:
            extra_idx = rng.choice(remaining.index.to_numpy(), size=extra_n, replace=False)
            out = pd.concat([out, remaining.loc[extra_idx]])
    return out.sort_values("t_raid").reset_index(drop=True).head(n)


def _fvg_row_html(row: pd.Series, replay_host: str, replay_port: int) -> str:
    url = deeplink.replay_url(row["td"], row["h"], host=replay_host, port=replay_port)
    return (f"<tr><td>{pd.Timestamp(row['td']).date()}</td><td>{row['direction']}</td>"
            f"<td>{row['gap_pips']:.1f} pips</td><td>{row['top']:.5f} / {row['ce']:.5f} / {row['bottom']:.5f}</td>"
            f"<td>{'yes' if row['is_displacement_leg'] else 'no'}</td>"
            f"<td>{'touched' if row['first_touch_idx'] >= 0 else 'never touched'}</td>"
            f"<td><a href='{url}' target='_blank' rel='noopener'>Open in replay ↗</a></td></tr>")


def _sweep_row_html(row: pd.Series, replay_host: str, replay_port: int) -> str:
    url = deeplink.replay_url(row["td"], row["t_raid_h"], host=replay_host, port=replay_port)
    return (f"<tr><td>{pd.Timestamp(row['td']).date()}</td><td>{row['session']}</td>"
            f"<td>{row['level_name']}</td><td>{row['side']}</td>"
            f"<td>{row['penetration_pips']:.1f} pips</td>"
            f"<td>{row['bars_to_close_back'] if pd.notna(row['bars_to_close_back']) else '?'} bars</td>"
            f"<td><a href='{url}' target='_blank' rel='noopener'>Open in replay ↗</a></td></tr>")


def build(fvg_sample: pd.DataFrame, sweep_sample: pd.DataFrame,
          replay_host: str = "127.0.0.1", replay_port: int = 8765) -> str:
    """Standalone HTML page (own <html>...</html>, same CSS tokens as report.html) listing the
    sampled FVGs and sweeps with a replay deep link each, for a manual visual check -- not a
    graded review like label_validate's (see module docstring)."""
    fvg_rows = "\n".join(_fvg_row_html(r, replay_host, replay_port) for _, r in fvg_sample.iterrows())
    sweep_rows = "\n".join(_sweep_row_html(r, replay_host, replay_port) for _, r in sweep_sample.iterrows())
    return f"""<html><head><meta charset='utf-8'><title>Hand-check: FVGs & sweeps — EURUSD Session Lab</title>
<style>{_css()}</style></head><body>
<h1>Hand-check: {len(fvg_sample)} FVGs + {len(sweep_sample)} sweeps</h1>
<div class='box info'>HANDOFF.md Step 3 -- Phase 7's last open item. For each row below, click
"Open in replay" and check the bars against what the row claims (a fair value gap between the
listed prices, or a sweep of the listed level that closed back within a few bars). If anything
looks wrong, tell me the row (day + type) and what you see instead -- I'll check it against
FEATURES_SPEC.md before changing any code.</div>

<h2>Fair value gaps ({len(fvg_sample)})</h2>
<table><tr><th>Day</th><th>Direction</th><th>Gap size</th><th>Top / CE / Bottom</th>
<th>On a displacement leg?</th><th>Ever touched?</th><th></th></tr>
{fvg_rows}
</table>

<h2>Sweeps ({len(sweep_sample)})</h2>
<table><tr><th>Day</th><th>Session</th><th>Level swept</th><th>Side</th><th>Penetration</th>
<th>Closed back in</th><th></th></tr>
{sweep_rows}
</table>

<div class='footer-note'>Not financial advice -- this is a research report, no live trading,
read-only against MT5. A "fair value gap" is a 3-bar price gap the pipeline flags as an
imbalance; a "sweep" is a brief break of a prior high/low that closed back on the original side
within a few bars (see FEATURES_SPEC.md S3/S7 for the exact definitions).</div>
</body></html>"""
