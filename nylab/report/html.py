"""nylab.report.html -- report.html builder. Ported verbatim from ny_session_lab.py's
html_report(), parameterized by pip + model params instead of a global CONFIG."""
from __future__ import annotations

import numpy as np
import pandas as pd


def pct(x):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x*100:.1f}%"


def num(x, f="{:.2f}"):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f.format(x)


def build(meta, d, H, m, trades, st_all, st_is, st_oos, figs, pip, model_params, extra_section="") -> str:
    css = """body{font-family:Segoe UI,Inter,Arial,sans-serif;max-width:980px;margin:30px auto;padding:0 18px;color:#1d2433;line-height:1.55}
h1{color:#0f1a2e;margin-bottom:4px}h2{color:#0f1a2e;border-bottom:2px solid #e8c77a;padding-bottom:4px;margin-top:34px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}th{background:#0f1a2e;color:#fff;text-align:left;padding:6px}
td{border-bottom:1px solid #e3e6ee;padding:5px 6px}tr:nth-child(even) td{background:#f6f7fa}.box{padding:12px 14px;border-left:4px solid;border-radius:6px;margin:14px 0}
.warn{background:#fcecee;border-color:#c8354b}.info{background:#eef4fd;border-color:#2f73d6}.good{background:#eaf7f1;border-color:#119469}
.y{color:#119469;font-weight:700}.n{color:#9aa6bd}.muted{color:#5e6678;font-size:13px}img{max-width:100%;border:1px solid #e3e6ee;border-radius:8px;margin:8px 0}"""
    D = d
    n = len(D)
    desc = [
        ("NY session makes the high of the trading day", D.ny_forms_day_high.mean()),
        ("NY session makes the low of the trading day", D.ny_forms_day_low.mean()),
        ("NY raids London KZ high", D.ny_takes_lon_high.mean()),
        ("NY raids London KZ low", D.ny_takes_lon_low.mean()),
        ("NY raids BOTH London extremes", (D.ny_takes_lon_high & D.ny_takes_lon_low).mean()),
        ("NY raids previous-day high (PDH)", D.ny_takes_pdh.mean()),
        ("NY raids previous-day low (PDL)", D.ny_takes_pdl.mean()),
        ("NY raids Asian high", D.ny_takes_asia_high.mean()),
        ("NY raids Asian low", D.ny_takes_asia_low.mean()),
        ("...of days NY raids London high, it CLOSES back below it", D.ny_close_back_below_lon_high.sum() / max(1, D.ny_takes_lon_high.sum())),
        ("...of days NY raids London low, it CLOSES back above it", D.ny_close_back_above_lon_low.sum() / max(1, D.ny_takes_lon_low.sum())),
        ("NY reaches Asian range +1 SD", D["ny_hits_asia_+1sd"].mean()),
        ("NY reaches Asian range −1 SD", D["ny_hits_asia_-1sd"].mean()),
        ("NY reaches Asian range ±2 SD (either side)", (D["ny_hits_asia_+2sd"] | D["ny_hits_asia_-2sd"]).mean()),
    ]
    rng = [("Day (17:00–17:00)", D.day_range), ("Asia 20:00–00:00", D.asia_range), ("London KZ 02:00–05:00", D.lon_range),
           ("NY 07:00–16:00", D.ny_range), ("CBDR 14:00–20:00", D.cbdr_range)]
    dow = D.groupby("dow").agg(days=("ny_range", "size"), ny_range=("ny_range", "median"),
                               up=("ny_drive", lambda s: (s > 0).mean()))
    names = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    h = [f"<html><head><meta charset='utf-8'><title>NY Session Lab — {meta['file']}</title><style>{css}</style></head><body>"]
    h.append(f"<h1>EURUSD New York Session Lab</h1><div class='muted'>{meta['file']} · {meta['first']} → {meta['last']} · "
             f"{n} trading days · {meta['bar']:.0f}-min bars · server time mode <b>{meta['tz']}</b> · "
             f"in-sample before {meta['split']}, out-of-sample after</div>")
    h.append("<div class='box info'><b>How to read this report.</b> Section 1–2 describe what happened (facts, not signals). "
             "Section 3 tests specific ideas against the market's own baseline; only rows that are <b>Bonferroni-significant AND hold out-of-sample</b> "
             "deserve further work. Section 4 is an example of turning an idea into rules and R-multiples. "
             "Before trusting ANY timing statistic, check Section 0: if the volatility profile doesn't spike at 08:30 and 09:30–11:00 NY, your --tz setting is wrong.</div>")
    h.append("<h2>0 · Sanity check — volatility by NY hour</h2>")
    if "profile" in figs:
        h.append(f"<img src='data:image/png;base64,{figs['profile']}'>")
    h.append("<p class='muted'>Expected shape for EURUSD: a bump at London open (02:00–04:00), the biggest bars 08:00–11:00, a fade into lunch. "
             "If the peak sits somewhere else (e.g. 15:00–18:00), rerun with --tz utc or --tz utc+2.</p>")

    h.append("<h2>1 · Session ranges (pips)</h2><table><tr><th>Window (NY)</th><th>Median</th><th>Mean</th><th>20th pct</th><th>80th pct</th></tr>")
    for nm, s in rng:
        h.append(f"<tr><td>{nm}</td><td>{s.median():.1f}</td><td>{s.mean():.1f}</td><td>{s.quantile(.2):.1f}</td><td>{s.quantile(.8):.1f}</td></tr>")
    h.append(f"</table><p class='muted'>Median ADR(5) share already used by 09:30 NY: {pct(D.adr_used_0930.median())}.</p>")

    h.append("<h2>2 · What the NY session does</h2>")
    if "extremes" in figs:
        h.append(f"<img src='data:image/png;base64,{figs['extremes']}'>")
    h.append("<table><tr><th>Observation</th><th>Frequency</th></tr>")
    for nm, v in desc:
        h.append(f"<tr><td>{nm}</td><td>{pct(v)}</td></tr>")
    h.append("</table><table><tr><th>Day</th><th>Days</th><th>Median NY range</th><th>NY drive up %</th></tr>")
    for i, r in dow.iterrows():
        h.append(f"<tr><td>{names[i]}</td><td>{int(r.days)}</td><td>{r.ny_range:.1f}</td><td>{pct(r.up)}</td></tr>")
    h.append("</table>")

    h.append(f"<h2>3 · Hypothesis tests ({m} ideas tested)</h2>"
             f"<p class='muted'>Hit = how often the outcome happened when the condition was true. Baseline = how often the same outcome happens on ALL days. "
             f"An idea matters only if hit is meaningfully above baseline. Bonferroni threshold: p &lt; {0.05/m:.4f}. "
             f"'Holds OOS' = still ≥3 points better than baseline on the unseen out-of-sample period (≥20 cases).</p>")
    h.append("<table><tr><th>Hypothesis</th><th>N</th><th>Hit</th><th>Baseline</th><th>95% CI</th><th>z</th><th>Bonf.</th><th>IS hit</th><th>OOS hit (n)</th><th>Holds OOS</th></tr>")
    for _, r in H.iterrows():
        h.append(f"<tr><td>{r.hypothesis}</td><td>{r.n}</td><td>{pct(r.hit)}</td><td>{pct(r.baseline)}</td>"
                 f"<td>{pct(r.ci_lo)}–{pct(r.ci_hi)}</td><td>{num(r.z)}</td>"
                 f"<td class='{'y' if r.bonferroni_sig else 'n'}'>{'YES' if r.bonferroni_sig else 'no'}</td>"
                 f"<td>{pct(r.is_hit)}</td><td>{pct(r.oos_hit)} ({r.oos_n})</td>"
                 f"<td class='{'y' if r.oos_holds else 'n'}'>{'YES' if r.oos_holds else 'no'}</td></tr>")
    h.append("</table>")
    strong = H[H.bonferroni_sig & H.oos_holds]
    if len(strong):
        h.append("<div class='box good'><b>Candidates worth deeper research:</b><ul>" +
                 "".join(f"<li>{x}</li>" for x in strong.hypothesis) +
                 "</ul>A candidate is a <i>starting point</i>, not a strategy: it still needs an entry, a stop, a target and a cost-inclusive backtest.</div>")
    else:
        h.append("<div class='box warn'><b>No idea passed both filters.</b> That is a normal, useful result: it means none of these simple "
                 "conditions is a reliable directional edge on its own. Edges usually come from combining a context filter with a precise "
                 "entry model (Section 4) — and some of these may still work as <i>filters</i>.</div>")

    h.append("<h2>4 · Example model — London KZ sweep reversal (NY AM)</h2>")
    C = model_params
    h.append(f"<p class='muted'>Rules: between {C['window'][0]:g}h and {C['window'][1]:g}h NY, price trades beyond the London killzone "
             f"high (low); within {C['max_bars_after_sweep']} bars an M5 candle closes back inside → enter at that close, opposite direction. "
             f"Stop {C['stop_buffer_pips']:g} pip beyond the sweep extreme. Target {('%gR' % C['rr']) if C['rr'] else 'the opposite London extreme'}. "
             f"Flat by {C['time_exit']:g}:00. One trade per day. Costs ≥ {C['default_cost_pips']:g} pip round trip (or the recorded spread + 0.2). "
             "If stop and target are touched in the same bar, the stop is assumed (conservative).</p>")
    if st_all.get("n", 0):
        h.append("<table><tr><th></th><th>Trades</th><th>Win rate</th><th>Expectancy (R, net)</th><th>95% CI</th><th>t</th><th>Profit factor</th><th>SQN</th><th>Max DD (R)</th><th>Worst streak</th></tr>")
        for nm, s in [("All", st_all), ("In-sample", st_is), ("Out-of-sample", st_oos)]:
            if s.get("n", 0):
                h.append(f"<tr><td>{nm}</td><td>{s['n']}</td><td>{pct(s['win_rate'])}</td><td>{num(s['expectancy'],'{:+.3f}')}</td>"
                         f"<td>{num(s['ci_lo'],'{:+.2f}')} to {num(s['ci_hi'],'{:+.2f}')}</td><td>{num(s['t'])}</td>"
                         f"<td>{num(s['profit_factor'])}</td><td>{num(s['sqn'])}</td><td>{num(s['max_dd_R'],'{:.1f}')}</td><td>{s['longest_losing_streak']}</td></tr>")
        h.append("</table>")
        if "equity" in figs:
            h.append(f"<img src='data:image/png;base64,{figs['equity']}'>")
        verdict = ("<div class='box good'><b>The OOS confidence interval is above zero.</b> Promising — next: vary one parameter at a time, "
                   "check each year separately, then forward-test on demo.</div>") if st_oos.get("n", 0) and st_oos["ci_lo"] > 0 else \
                  ("<div class='box warn'><b>Not proven.</b> The out-of-sample confidence interval includes zero (or is negative). "
                   "Do NOT trade this as-is. Use it as a template: change one rule, re-run, and keep a log of every variant you tried "
                   "(that count is your 'm' for the multiple-testing correction).</div>")
        h.append(verdict)
        yearly = trades.assign(y=pd.to_datetime(trades.td).dt.year).groupby("y").R_net.agg(["size", "mean", "sum"])
        h.append("<table><tr><th>Year</th><th>Trades</th><th>Expectancy (R)</th><th>Total R</th></tr>" +
                 "".join(f"<tr><td>{y}</td><td>{int(r['size'])}</td><td>{r['mean']:+.3f}</td><td>{r['sum']:+.1f}</td></tr>" for y, r in yearly.iterrows()) + "</table>")
    else:
        h.append("<p>No trades were generated with the current rules.</p>")
    if extra_section:
        h.append(extra_section)
    h.append("<h2>Files</h2><p class='muted'><b>days.csv</b> — one row per day with every level and flag above (open it in Excel and filter). "
             "<b>trades.csv</b> — every example-model trade with entry, stop, target, exit and R. "
             "Always open 10–20 of those trades on your MT5 chart and check the rules did what you think they did.</p></body></html>")
    return "\n".join(h)
