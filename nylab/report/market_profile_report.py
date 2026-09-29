"""nylab.report.market_profile_report -- builds reports/market_profile/report.html, the
descriptive "how does EURUSD usually behave" map from nylab.market_profile (Akash's request,
2026-09-28/29). See nylab.market_profile's module docstring for the exploratory-vs-confirmatory
distinction repeated at the top of the generated page itself -- this is a map for building
intuition, not a tested/tradeable edge."""
from __future__ import annotations

import numpy as np
import pandas as pd

from nylab import market_profile as mp
from nylab.report.html import _css, _THEME_SCRIPT

_PCT_COLS_HINT = ("pct_up", "pct_down", "pct_flat", "pct_quiet", "pct_chop", "pct_trend",
                   "pct_reversal", "pct_range_both", "pct_normal", "dominant_pct",
                   "pct_range_or_normal_day", "pct_sets_week_high", "pct_sets_week_low")


def _fmt_cell(col: str, v) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "<span class='muted'>—</span>"
    if col in _PCT_COLS_HINT or col.startswith("pct_"):
        return f"{v * 100:.1f}%"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def _table_html(df: pd.DataFrame, caption: str = "") -> str:
    if df is None or not len(df):
        return "<p class='muted'>Not enough data for this table.</p>"
    cols = list(df.columns)
    head = "".join(f"<th>{c.replace('_', ' ')}</th>" for c in cols)
    body_rows = []
    for _, r in df.iterrows():
        low_n = bool(r.get("low_n", False))
        cells = "".join(f"<td>{_fmt_cell(c, r[c])}</td>" for c in cols)
        cls = " class='low-n'" if low_n else ""
        body_rows.append(f"<tr{cls}>{cells}</tr>")
    cap = f"<div class='muted' style='margin:4px 0'>{caption}</div>" if caption else ""
    return f"{cap}<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _highlight(text: str) -> str:
    return f"<li>{text}</li>"


def _build_highlights(hour_tbl, weekday_tbl, wk_extremes, month_tbl, quiet_lon) -> list[str]:
    out = []
    if len(hour_tbl):
        top = hour_tbl.loc[hour_tbl["median_range_pips"].idxmax()]
        low = hour_tbl.loc[hour_tbl["median_range_pips"].idxmin()]
        out.append(_highlight(
            f"The busiest hour of the day (by median pip range) is <b>{int(top['ny_hour']):02d}:00 NY</b> "
            f"(~{top['median_range_pips']:.1f} pips typical); the quietest is <b>{int(low['ny_hour']):02d}:00 NY</b> "
            f"(~{low['median_range_pips']:.1f} pips) -- across {int(top['n_days'])} days."))
    if len(weekday_tbl):
        top = weekday_tbl.loc[weekday_tbl["median_range_pips"].idxmax()]
        low = weekday_tbl.loc[weekday_tbl["median_range_pips"].idxmin()]
        out.append(_highlight(
            f"<b>{top['weekday']}</b> has had the widest typical daily range (~{top['median_range_pips']:.1f} pips); "
            f"<b>{low['weekday']}</b> the narrowest (~{low['median_range_pips']:.1f} pips)."))
    if len(wk_extremes):
        top_hi = wk_extremes.loc[wk_extremes["pct_sets_week_high"].idxmax()]
        top_lo = wk_extremes.loc[wk_extremes["pct_sets_week_low"].idxmax()]
        out.append(_highlight(
            f"<b>{top_hi['weekday']}</b> sets the week's high most often ({top_hi['pct_sets_week_high']*100:.0f}% of weeks); "
            f"<b>{top_lo['weekday']}</b> sets the week's low most often ({top_lo['pct_sets_week_low']*100:.0f}% of weeks)."))
    if len(month_tbl):
        top = month_tbl.loc[month_tbl["median_range_pips"].idxmax()]
        low = month_tbl.loc[month_tbl["median_range_pips"].idxmin()]
        out.append(_highlight(
            f"<b>{top['month']}</b> has been the widest-range month on average (~{top['median_range_pips']:.1f} pips/day); "
            f"<b>{low['month']}</b> the narrowest (~{low['median_range_pips']:.1f} pips/day)."))
    if len(quiet_lon):
        q = quiet_lon[quiet_lon["bucket"].str.startswith("quiet")]
        if len(q):
            row = q.iloc[0]
            dom = row.get("dominant")
            out.append(_highlight(
                f"When London opened unusually quiet (range so far under 60% of its typical), it most often went on "
                f"to be labelled <b>'{dom}'</b> ({row['dominant_pct']*100:.0f}% of {int(row['n'])} such days)."))
    return out


def build(d: pd.DataFrame, df: pd.DataFrame, pip: float, sessions_cfg: dict) -> str:
    """d: the full session-attached day table (nylab.days + nylab.sessions). df: raw M5 bars
    (needs an `ny` column) for the hour-of-day profile. sessions_cfg: nylab.config.sessions(),
    used only to read each session's own start hour for the early-raid timing tables."""
    hour_tbl = mp.hour_of_day_profile(df, pip)
    weekday_tbl = mp.weekday_profile(d)
    wk_extremes = mp.weekday_extremes_table(d)
    month_tbl = mp.monthly_profile(d)
    quarter_tbl = mp.quarterly_profile(d)

    lon_start = sessions_cfg.get("lon", (5.0, 8.0))[0] if "lon" in sessions_cfg else 5.0
    nyam_start = sessions_cfg.get("nyam", (7.0, 12.0))[0] if "nyam" in sessions_cfg else 7.0

    rel_asia_lon_nyam = mp.session_relationship_table(
        d, ["asia_character", "lon_character"], "nyam_full_dir", "dir") if "nyam_full_dir" in d.columns else pd.DataFrame()
    rel_asia_lon = mp.session_relationship_table(
        d, ["asia_character"], "lon_dir", "dir") if "lon_dir" in d.columns else pd.DataFrame()
    rel_lon_nyamkz = mp.session_relationship_table(
        d, ["lon_character"], "nyam_kz_character", "character") if "nyam_kz_character" in d.columns else pd.DataFrame()

    early_lon = mp.early_raid_outcome_table(d, "lon", lon_start, "lon_character", "character") \
        if "lon_first_raid_t" in d.columns else pd.DataFrame()
    early_nyam = mp.early_raid_outcome_table(d, "nyam_full", nyam_start, "nyam_full_dir", "dir") \
        if "nyam_full_first_raid_t" in d.columns else pd.DataFrame()
    quiet_lon = mp.quiet_start_outcome_table(d, "lon") if "lon_range_rel" in d.columns else pd.DataFrame()
    quiet_nyam = mp.quiet_start_outcome_table(d, "nyam_full") if "nyam_full_range_rel" in d.columns else pd.DataFrame()

    news_nyam_usd = mp.news_reaction_table(d, "nyam_full", "usd")
    news_lon_eur = mp.news_reaction_table(d, "lon", "eur")

    highlights = _build_highlights(hour_tbl, weekday_tbl, wk_extremes, month_tbl, quiet_lon)

    n_days = len(d)
    date_range = f"{d.index.min():%Y-%m-%d} to {d.index.max():%Y-%m-%d}" if n_days else "—"

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>EURUSD Market Profile</title>
<style>{_css()}
.low-n td{{opacity:.55}}
.disclaimer{{background:var(--panel);border:1px solid var(--border);border-left:4px solid var(--amber);
  border-radius:8px;padding:14px 16px;margin:16px 0}}
</style></head><body>
{_THEME_SCRIPT}
<button id="themeToggle" onclick="toggleReportTheme()">Toggle theme</button>
<h1>EURUSD Market Profile</h1>
<p class="muted">{n_days:,} trading days, {date_range}.</p>

<div class="disclaimer">
<b>Read this first.</b> Everything below is <b>descriptive</b> -- "here's what usually happened" --
not a tested trading edge. It slices the same years of data dozens of ways at once (every session
combination, every hour, every weekday, every month), and with that many slices shown side by side,
some will look like a pattern purely by chance. Every table shows its sample size (n); rows with
fewer than {mp.LOW_N} days are shaded and should be treated as anecdotes, not patterns. If something
here looks worth trading, the next step is to write it up as a proper hypothesis
(<code>config/hypotheses/</code>) and let it earn a real verdict the way H013/H014 did -- not to
act on it straight from this page.
</div>

<h2>Highlights</h2>
<ul>{"".join(highlights) if highlights else "<li class='muted'>Not enough data yet.</li>"}</ul>

<h2>1. Session relationships -- what does the next session usually do?</h2>
<h3>Asia + London character -&gt; NY direction</h3>
{_table_html(rel_asia_lon_nyam, "Every observed (Asia character, London character) combination, sorted by how often it occurred.")}
<h3>Asia character -&gt; London direction</h3>
{_table_html(rel_asia_lon)}
<h3>London character -&gt; NY AM killzone character</h3>
{_table_html(rel_lon_nyamkz)}

<h2>2. In-session timing</h2>
<h3>London: early vs late sweep of Asia's level -&gt; London's own character</h3>
{_table_html(early_lon, "'Early' = the session's first sweep of the prior level happened within 60 minutes of its own open.")}
<h3>NY (broad): early vs late sweep -&gt; NY direction</h3>
{_table_html(early_nyam)}
<h3>London: quiet/active start -&gt; London's eventual character</h3>
{_table_html(quiet_lon, "'Quiet so far' = range covered is under 60% of the session's typical (trailing 20-day median).")}
<h3>NY (broad): quiet/active start -&gt; NY's eventual direction</h3>
{_table_html(quiet_nyam)}

<h2>3. News reaction</h2>
<h3>NY (broad): with vs without high-impact USD news in the window</h3>
{_table_html(news_nyam_usd)}
<h3>London: with vs without high-impact EUR news in the window</h3>
{_table_html(news_lon_eur)}

<h2>4. Hour-of-day profile (NY time, all sessions pooled)</h2>
{_table_html(hour_tbl, "Median/mean pip range covered within each clock hour, and the fraction of those hourly candles that closed above their open.")}

<h2>5. Seasonality</h2>
<h3>By weekday</h3>
{_table_html(weekday_tbl)}
<h3>Which weekday sets the week's high/low</h3>
{_table_html(wk_extremes)}
<h3>By month (pooled across all years)</h3>
{_table_html(month_tbl)}
<h3>By quarter</h3>
{_table_html(quarter_tbl)}

<div class="footer-note">Generated by <code>python -m nylab market-profile</code>. Descriptive only -- see the notice at the top of this page.</div>
</body></html>"""
    return html
