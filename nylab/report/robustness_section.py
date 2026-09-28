"""nylab.report.robustness_section -- ROADMAP 8.3: renders nylab.robustness
.run_robustness_battery()'s output as a report.html section, matching
RESEARCH_PROTOCOL.md S5 item 4's own wording for each of the 6 checks."""
from __future__ import annotations

from nylab.report.html import num, pct


def _stats_row(label: str, s: dict) -> str:
    if not s.get("n", 0):
        return f"<tr><td>{label}</td><td colspan='4' class='muted'>No trades</td></tr>"
    return (f"<tr><td>{label}</td><td>{s['n']}</td><td>{num(s['expectancy'], '{:+.3f}')}</td>"
            f"<td>{num(s['ci_lo'], '{:+.2f}')} to {num(s['ci_hi'], '{:+.2f}')}</td>"
            f"<td>{num(s.get('max_dd_R'), '{:.1f}')}</td></tr>")


def build(result: dict) -> str:
    """`result` is nylab.robustness.run_robustness_battery()'s return dict."""
    h = ["<h2>12 · Robustness battery</h2>",
         "<p class='muted'>RESEARCH_PROTOCOL.md S5 item 4 -- required before any model gets a "
         "“promising” verdict. Each check re-examines the SAME baseline trades under a "
         "different stress, or a different lens on the same results; none of it re-fits anything.</p>"]

    h.append("<h3>1 &amp; 2 · Cost stress and entry-delay</h3>")
    h.append("<table><tr><th></th><th>N</th><th>Expectancy (R)</th><th>95% CI</th><th>Max DD (R)</th></tr>")
    h.append(_stats_row("Baseline", result["baseline_stats"]))
    h.append(_stats_row("Cost ×1.5", result["cost_x1_5"]))
    h.append(_stats_row("Cost ×2", result["cost_x2"]))
    h.append(_stats_row("Entry delayed 1 bar", result["entry_delay_1bar_stats"]))
    h.append("</table>")
    skipped = result.get("entry_delay_1bar_skipped", 0)
    if skipped:
        h.append(f"<p class='muted'>{skipped} delayed entries were skipped because one bar later price "
                 "had already closed past the original stop or target (the setup no longer existed).</p>")
    base_e = result["baseline_stats"].get("expectancy")
    still_positive = all(result[k].get("expectancy") is not None and result[k]["expectancy"] > 0
                          for k in ("cost_x1_5", "cost_x2", "entry_delay_1bar_stats") if result[k].get("n", 0))
    if base_e is not None and base_e > 0:
        badge = "good" if still_positive else "warn"
        msg = "still positive under every stress above" if still_positive else "NOT positive under every stress above"
        h.append(f"<div class='box {badge}'><b>{msg}.</b></div>")

    h.append("<h3>3 · Per-year contribution</h3>")
    py = result["per_year"]
    if len(py) == 0:
        h.append("<p class='muted'>No trades.</p>")
    else:
        h.append("<table><tr><th>Year</th><th>N</th><th>Total R</th><th>Share of total R</th><th>&gt;50%?</th></tr>")
        for _, r in py.iterrows():
            flag = "<span class='badge v-bad'>YES</span>" if r["flag_over_50pct"] else "no"
            h.append(f"<tr><td>{int(r['year'])}</td><td>{int(r['n'])}</td><td>{r['total_R']:+.1f}</td>"
                     f"<td>{pct(r['share_of_total_R'])}</td><td>{flag}</td></tr>")
        h.append("</table>")
        if py["total_R"].sum() <= 0:
            h.append("<p class='muted'>Total R is not positive, so the “share of total” column is not "
                     "meaningful here (it can flip sign or exceed 100%). This check only matters for a "
                     "model that is net positive.</p>")
        elif py["flag_over_50pct"].any():
            h.append("<div class='box warn'><b>At least one year contributes over 50% of total R</b> -- "
                      "the result may be driven by a single year's conditions rather than a durable edge.</div>")

    h.append("<h3>4 · Remove best 5% of trades</h3>")
    h.append("<table><tr><th></th><th>N</th><th>Expectancy (R)</th><th>95% CI</th><th>Max DD (R)</th></tr>")
    h.append(_stats_row("Baseline", result["baseline_stats"]))
    h.append(_stats_row("Best 5% removed", result["remove_best_5pct_stats"]))
    h.append("</table>")

    mc = result["monte_carlo"]
    h.append("<h3>5 · Monte Carlo (10,000 shuffles of trade order)</h3>")
    if mc.get("n_trades", 0):
        h.append(f"<p>95th-percentile max drawdown across {mc['n_shuffles']:,} reshuffles of the same "
                 f"{mc['n_trades']} trades: <b>{mc['max_dd_p95']:.1f}R</b>. "
                 f"Probability of a {mc['losing_streak_len']}-trade losing stretch somewhere in the "
                 f"sequence: <b>{pct(mc['p_losing_streak'])}</b>. Use these for position sizing, not "
                 "as a pass/fail test on their own (Formula Handbook 4.x).</p>")
    else:
        h.append("<p class='muted'>No trades.</p>")

    tg = result["thin_gappy"]
    h.append("<h3>6 · Thin/gappy days excluded vs included</h3>")
    h.append("<table><tr><th></th><th>N</th><th>Expectancy (R)</th><th>95% CI</th><th>Max DD (R)</th></tr>")
    h.append(_stats_row("Included (all days)", tg["included"]))
    h.append(_stats_row(f"Excluded ({tg['n_thin_or_gappy_days_removed']} thin/gappy trades removed)", tg["excluded"]))
    h.append("</table>")

    return "\n".join(h)
