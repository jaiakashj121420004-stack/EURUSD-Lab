"""nylab.report.sessions_section -- ROADMAP Phase 5.5 / SESSIONS_AND_CONTEXT.md S6: renders
the descriptive session-layer, cross-session, news, and Silver Bullet material (Phases
5.1-5.4) into report.html, plus a small "relational hypotheses" table that visibly
distinguishes matrix-family promotions (like H016, matrix_cells=36) from ordinary 1-cell
hypotheses. Every number in this module is DESCRIPTIVE (nylab.cross_session.DESCRIPTIVE_BANNER)
except item 6, which reads already-tested hypothesis rows straight from `H`.

Disclosed simplifications (see docs/PROGRESS.md's Phase 5.5 write-up for the full rationale):
  - item 1's "by year" breakdown is limited to median range_pips per session x year, not a full
    character-distribution-by-year table -- S6 doesn't specify a shape for this, and a full
    breakdown would be a large, mostly-empty table for the rarer characters (S5.3 already
    flagged `trend` firing on ~9/1300 asia-days; slicing that further by year isn't informative).
  - item 4's "surprise severity" reuses nyam_kz's own `news_surprise_z`/`news_high_usd`/
    `news_high_eur` columns as the single family-agnostic proxy for "the morning's news
    surprise", rather than adding a new bar-level scan; "time-to-high/low after releases" reuses
    the existing session `hi_t`/`lo_t` columns (nyam_kz, since 08:30 releases land inside it)
    split by news-day vs non-news-day, rather than writing new bar-level release-anchored
    scanning code. Both are named explicitly in the rendered HTML, not left implicit.
  - the heatmap (item 2) buckets by whole NY hour x weekday, matching charts.py's existing
    hour-bucketing convention (`sub.h.astype(int)`), not finer time buckets.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import cross_session as cs
from nylab import sessions as sessions_mod
from nylab.report.charts import fig_b64

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover
    plt = None


def _pct(x):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x*100:.1f}%"


def _num(x, f="{:.2f}"):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f.format(x)


def _matrix_table(m: pd.DataFrame, title: str, note: str = "") -> str:
    if len(m) == 0:
        return f"<h3>{title}</h3><p class='muted'>No rows (missing inputs).</p>"
    h = [f"<h3>{title}</h3>"]
    if note:
        h.append(f"<p class='muted'>{note}</p>")
    h.append("<table><tr><th>A label</th><th>B label</th><th>n</th><th>P(B|A)</th>"
              "<th>P(B) unconditional</th><th>95% CI</th></tr>")
    for _, r in m.iterrows():
        cls = " class='muted'" if r.greyed else ""
        grey_note = " (n&lt;25, greyed)" if r.greyed else ""
        h.append(f"<tr{cls}><td>{r.a_label}</td><td>{r.b_label}</td><td>{int(r.n)}{grey_note}</td>"
                 f"<td>{_pct(r.cond_pct)}</td><td>{_pct(r.uncond_pct)}</td>"
                 f"<td>{_pct(r.ci_lo)}–{_pct(r.ci_hi)}</td></tr>")
    h.append("</table>")
    return "\n".join(h)


def _bucket_table(b: pd.DataFrame, title: str, note: str = "") -> str:
    h = [f"<h3>{title}</h3>"]
    if note:
        h.append(f"<p class='muted'>{note}</p>")
    h.append("<table><tr><th>Bucket</th><th>n</th><th>Rate</th><th>95% CI</th></tr>")
    for _, r in b.iterrows():
        cls = " class='muted'" if r.greyed else ""
        grey_note = " (n&lt;25, greyed)" if r.greyed else ""
        h.append(f"<tr{cls}><td>{r.bucket}</td><td>{int(r.n)}{grey_note}</td>"
                 f"<td>{_pct(r.rate)}</td><td>{_pct(r.ci_lo)}–{_pct(r.ci_hi)}</td></tr>")
    h.append("</table>")
    return "\n".join(h)


def _heatmap_fig(df: pd.DataFrame, pip: float):
    """Median range (pips) by NY hour (rows 0-16) x weekday (cols Mon-Fri) -- disclosed
    simplification in the module docstring: whole-hour buckets, same convention charts.py uses."""
    if plt is None:
        return None
    sub = df[(df.h >= 0) & (df.h < 17)].copy()
    sub["hour"] = sub.h.astype(int)
    sub["dow"] = sub.td.dt.dayofweek
    rng = sub.groupby(["td", "hour", "dow"]).agg(hi=("high", "max"), lo=("low", "min")).reset_index()
    rng["range_pips"] = (rng["hi"] - rng["lo"]) / pip
    pivot = rng.groupby(["hour", "dow"])["range_pips"].median().unstack("dow").reindex(
        index=range(0, 17), columns=range(5))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd", origin="lower")
    ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels([f"{h}:00" for h in pivot.index], fontsize=7)
    ax.set_xticks(range(5)); ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri"])
    ax.set_xlabel("weekday"); ax.set_ylabel("NY hour")
    ax.set_title("Median range (pips) by NY hour x weekday", fontsize=10)
    fig.colorbar(im, ax=ax, label="pips")
    return fig_b64(fig)


def build_figs(df: pd.DataFrame, pip: float) -> dict:
    """Extra figures for this section (called alongside nylab.report.charts.build())."""
    out = {}
    hm = _heatmap_fig(df, pip)
    if hm is not None:
        out["hour_dow_heatmap"] = hm
    return out


def build(df: pd.DataFrame, d: pd.DataFrame, session_tables: dict, sessions_cfg: dict,
          cal, H: pd.DataFrame, pip: float, figs: dict) -> str:
    """Builds the full S6 section as an HTML fragment (sections 5-10 numbering, appended
    before html.py's "Files" footer). `figs` is this module's own build_figs() output."""
    h = [f"<div class='box info'><b>{cs.DESCRIPTIVE_BANNER}</b> Everything in section 5-9 below "
         "is a plain count/rate, not a significance test -- only section 3 (and item 10's "
         "relational-hypotheses table) has gone through the multiple-testing ledger.</div>"]

    # --- 5. Session overview (S6 item 1) ---
    h.append("<h2>5 · Session overview (descriptive)</h2>")
    h.append("<table><tr><th>Session</th><th>Window (NY)</th><th>Median range (pips)</th>"
             "<th>Mean ER</th><th>Character distribution</th></tr>")
    for sid in sessions_mod.SESSION_IDS:
        t = session_tables[sid]
        lo, hi = sessions_cfg[sid]
        dist = t["character"].value_counts(normalize=True)
        dist_str = ", ".join(f"{k} {v*100:.0f}%" for k, v in dist.sort_values(ascending=False).items())
        h.append(f"<tr><td>{sid}</td><td>{lo:g}–{hi:g}</td><td>{_num(t['range_pips'].median(), '{:.1f}')}</td>"
                 f"<td>{_num(t['er'].mean())}</td><td class='muted'>{dist_str}</td></tr>")
    h.append("</table>")
    h.append("<p class='muted'>By year (median range, pips) -- disclosed simplification: median "
             "range only, not a full character-by-year breakdown (see nylab/report/sessions_section.py).</p>")
    years = sorted(pd.to_datetime(d.index).year.unique())
    h.append("<table><tr><th>Session</th>" + "".join(f"<th>{y}</th>" for y in years) + "</tr>")
    for sid in sessions_mod.SESSION_IDS:
        t = session_tables[sid]
        yr = pd.to_datetime(t.index).year
        row = [f"<td>{sid}</td>"]
        for y in years:
            v = t.loc[yr == y, "range_pips"].median()
            row.append(f"<td>{_num(v, '{:.1f}')}</td>")
        h.append("<tr>" + "".join(row) + "</tr>")
    h.append("</table>")

    # --- 6. Hour x weekday heatmap (S6 item 2) ---
    h.append("<h2>6 · Volatility heatmap — NY hour x weekday</h2>")
    if "hour_dow_heatmap" in figs:
        h.append(f"<img src='data:image/png;base64,{figs['hour_dow_heatmap']}'>")
    h.append("<p class='muted'>Median range per hour bucket, split by weekday -- a finer-grained "
             "version of section 0's sanity check, useful for spotting day-of-week seasonality.</p>")

    # --- 7. Cross-session transition matrices (S6 item 3) ---
    h.append("<h2>7 · Cross-session transition matrices (descriptive)</h2>")
    char_matrices = cs.run_default_character_matrices(session_tables)
    dir_matrices = cs.run_default_dir_matrices(session_tables)
    for key, m in char_matrices.items():
        h.append(_matrix_table(m, f"Character: {key.replace('_', ' ')}"))
    for key, m in dir_matrices.items():
        h.append(_matrix_table(m, f"Direction: {key.replace('_', ' ')}"))
    takes = cs.run_default_takes(df, sessions_cfg, session_tables)
    h.append("<h3>Takes-rate (does session B trade through session A's high/low)</h3>")
    h.append("<table><tr><th>A -> B</th><th>n</th><th>Takes high</th><th>Takes low</th><th>Takes both</th></tr>")
    for key, t in takes.items():
        grey_note = " (n&lt;25)" if t["greyed"] else ""
        h.append(f"<tr><td>{key.replace('_', ' ')}</td><td>{t['n']}{grey_note}</td>"
                 f"<td>{_pct(t['takes_high_rate'])}</td><td>{_pct(t['takes_low_rate'])}</td>"
                 f"<td>{_pct(t['takes_both_rate'])}</td></tr>")
    h.append("</table>")

    # --- 8. News impact (S6 item 4) ---
    h.append("<h2>8 · News impact (descriptive)</h2>")
    if cal is not None and "nyam_kz_news_high_usd" in d.columns:
        h.append("<p class='muted'>Reuses nyam_kz's own news_high_usd/news_high_eur/news_surprise_z "
                 "columns as the single proxy for \"the morning's news surprise\" (disclosed "
                 "simplification -- see nylab/report/sessions_section.py's module docstring).</p>")
        outcome = (session_tables["nyam_kz"]["character"] == "reversal")
        nc = cs.news_conditioned_rate(d["nyam_kz_news_high_usd"], d["nyam_kz_news_high_eur"], outcome)
        h.append(_bucket_table(nc, "NY AM killzone reversal rate, conditioned on London-window news",
                                "bucket = which currency had a high-importance event during the London window."))
        ns = cs.news_severity_rate(d["nyam_kz_news_high_usd"] + d["nyam_kz_news_high_eur"],
                                    d["nyam_kz_news_surprise_z"], outcome)
        h.append(_bucket_table(ns, "...and by surprise severity (|z| > 1.0 = event_high_z)"))

        h.append("<h3>Time-of-high/low inside the NY AM killzone, news day vs not</h3>")
        h.append("<p class='muted'>Stand-in for \"time-to-high/low after 08:30/14:00 releases\" -- "
                 "reuses the existing nyam_kz hi_t/lo_t session columns split by whether ANY "
                 "high-importance event fell in the London window that day, rather than new "
                 "bar-level release-anchored scanning (disclosed simplification).</p>")
        has_news = (d["nyam_kz_news_high_usd"] + d["nyam_kz_news_high_eur"]) > 0
        h.append("<table><tr><th>Day type</th><th>n</th><th>Median hi_t (NY h)</th><th>Median lo_t (NY h)</th></tr>")
        for label, mask in (("news day", has_news), ("non-news day", ~has_news)):
            sub = session_tables["nyam_kz"][mask.reindex(session_tables["nyam_kz"].index, fill_value=False)]
            h.append(f"<tr><td>{label}</td><td>{len(sub)}</td>"
                     f"<td>{_num(sub['hi_t'].median())}</td><td>{_num(sub['lo_t'].median())}</td></tr>")
        h.append("</table>")
    else:
        h.append("<p class='muted'>No calendar cache attached this run (`nylab calendar-import` "
                 "not yet run, or --calendar path missing) -- news-impact section skipped.</p>")

    # --- 9. Silver Bullet windows (S6 item 5) ---
    h.append("<h2>9 · Silver Bullet windows (descriptive)</h2>")
    sb = cs.silver_bullet_stats(session_tables)
    h.append("<table><tr><th>Window</th><th>n</th><th>FVG forms</th><th>Reversal-character rate</th>"
             "<th>Median range (pips)</th></tr>")
    for _, r in sb.iterrows():
        h.append(f"<tr><td>{r.session_id}</td><td>{int(r.n)}</td><td>{_pct(r.fvg_rate)}</td>"
                 f"<td>{_pct(r.reversal_rate)}</td><td>{_num(r.median_range_pips, '{:.1f}')}</td></tr>")
    h.append("</table>")
    h.append("<p class='muted'>\"Reversal-character rate\" is this module's closest available proxy "
             "for \"reaches the nearest opposite liquidity within the window\" -- see "
             "nylab.cross_session.silver_bullet_stats's own docstring.</p>")

    # --- 10. Relational hypotheses (S6 item 6) ---
    h.append("<h2>10 · Relational (matrix-family) hypotheses</h2>")
    rel = H[H["family"].notna()] if "family" in H.columns else H.iloc[0:0]
    if len(rel):
        h.append("<p class='muted'>Promoted from a transition matrix cell -- each one counts its "
                 "WHOLE matrix toward m (matrix_cells), not just the one cell that looked extreme "
                 "(SESSIONS_AND_CONTEXT.md S5.2).</p>")
        h.append("<table><tr><th>Hypothesis</th><th>Family</th><th>Matrix cells</th><th>N</th>"
                 "<th>Hit</th><th>Baseline</th><th>Bonf.</th><th>Holds OOS</th></tr>")
        for _, r in rel.iterrows():
            h.append(f"<tr><td>{r.hypothesis}</td><td>{r.family}</td><td>{int(r.matrix_cells)}</td>"
                     f"<td>{r.n}</td><td>{_pct(r.hit)}</td><td>{_pct(r.baseline)}</td>"
                     f"<td class='{'y' if r.bonferroni_sig else 'n'}'>{'YES' if r.bonferroni_sig else 'no'}</td>"
                     f"<td class='{'y' if r.oos_holds else 'n'}'>{'YES' if r.oos_holds else 'no'}</td></tr>")
        h.append("</table>")
    else:
        h.append("<p class='muted'>No matrix-family hypotheses in this run's hypothesis set.</p>")

    return "\n".join(h)
