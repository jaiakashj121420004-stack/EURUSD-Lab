"""nylab.report.maven_section -- ROADMAP 8.4: report.html section 13 + summary.json's `maven`
block for nylab.maven_sim's Maven pass simulator output (config/prop.yaml's verified program
rules; `nylab run --maven-program <name>` picks the program, default prop.yaml's default_program).

Plain-English framing throughout (CLAUDE.md S1: "explain every statistic in one sentence"): this
is a Monte Carlo -- it bootstraps thousands of imaginary attempts from the model's OWN historical
out-of-sample trades, it never predicts the future, and a HIGH pass probability on a model whose
own OOS expectancy is negative or unproven just means the challenge's target is small/lenient
relative to the account's drawdown room, not that the model is good -- section 4's own OOS
verdict (survives-oos/promising/negative/not proven) is what actually says whether there's an
edge; this section only says "if that edge (or lack of one) repeats, how much of a Maven pass or
fail is luck vs. skill."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from nylab.report.html import num, pct


def summary_block(maven_df: pd.DataFrame, program_name: str, size: float,
                   fee_usd: Optional[float] = None) -> dict:
    """HANDOFF.md S4 step 1's own wording: "a `maven` block in summary.json: per risk level
    P(pass all phases), P(pass each phase), median days, expected attempts." One dict per risk
    level in `maven_df` (nylab.maven_sim.sweep_risk_grid's return)."""
    rows = []
    for _, r in maven_df.iterrows():
        row = dict(
            risk_pct=float(r["risk_pct"]),
            p_pass_all_phases=round(float(r["p_pass_all_phases"]), 4),
            p_pass_per_phase=[round(float(x), 4) for x in r["p_pass_per_phase"]],
            median_days_to_pass=(None if pd.isna(r["median_days_to_pass"])
                                  else round(float(r["median_days_to_pass"]), 1)),
            expected_attempts_to_pass=(None if pd.isna(r["expected_attempts_to_pass"])
                                        else round(float(r["expected_attempts_to_pass"]), 2)),
        )
        if "expected_cost_usd" in r and pd.notna(r["expected_cost_usd"]):
            row["expected_cost_usd"] = round(float(r["expected_cost_usd"]), 2)
        rows.append(row)
    return dict(program=program_name, account_size_usd=size, fee_usd=fee_usd, by_risk_level=rows)


def build(maven_df: pd.DataFrame, program_name: str, program: dict, size: float,
          fee_usd: Optional[float] = None) -> str:
    """Returns report.html's section 13 HTML fragment."""
    targets = program.get("profit_targets_pct") or []
    n_phases = max(len(targets), 1)
    phase_labels = [f"Phase {i+1} (+{t:g}%)" for i, t in enumerate(targets)] or ["Funded (no eval)"]

    h = [f"<h2>13 · Maven pass simulation — {program.get('label', program_name)} (${size:,.0f})</h2>",
         "<p class='muted'>This bootstraps 5,000 imaginary attempts at the challenge above from the "
         "model's own out-of-sample trades (drawn with replacement, one trade per simulated day, applying "
         "the exact same daily and max drawdown rules Maven uses) -- it does not predict future performance, "
         "it just shows how much of a pass or fail would be luck if the past out-of-sample trades kept "
         "repeating in a random order. <b>A high pass probability here does NOT mean the model has a real "
         "edge</b> -- check section 4's out-of-sample verdict for that; a lenient target can be 'passable' "
         "even for a model with no edge, just as a real edge can still fail a single attempt by bad luck.</p>"]

    if fee_usd is not None:
        h.append(f"<p class='muted'>Fee used for the cost column: <b>${fee_usd:,.2f}</b> per attempt on this "
                 f"${size:,.0f} account (Akash-confirmed 2026-09-24 program pricing, 2026-09-28 fee; re-check "
                 "if the account size changes).</p>")
    else:
        h.append("<p class='muted'>No verified per-attempt fee is on file for this program -- the cost "
                 "column is left out rather than guessed (config/prop.yaml's `fee_usd`).</p>")

    header_cells = "".join(f"<th>{lbl}</th>" for lbl in phase_labels)
    cost_header = "<th>Expected cost</th>" if fee_usd is not None else ""
    h.append(f"<table><tr><th>Risk / trade</th><th>P(pass ALL phases)</th>{header_cells}"
             f"<th>Median days to pass</th><th>Expected attempts</th>{cost_header}</tr>")
    for _, r in maven_df.iterrows():
        phase_cells = "".join(f"<td>{pct(p)}</td>" for p in r["p_pass_per_phase"])
        cost_cell = f"<td>{num(r.get('expected_cost_usd'), '${:.0f}')}</td>" if fee_usd is not None else ""
        h.append(f"<tr><td>{r['risk_pct']:g}%</td><td><b>{pct(r['p_pass_all_phases'])}</b></td>{phase_cells}"
                 f"<td>{num(r['median_days_to_pass'], '{:.0f}')}</td>"
                 f"<td>{num(r['expected_attempts_to_pass'], '{:.1f}')}</td>{cost_cell}</tr>")
    h.append("</table>")
    h.append(f"<p class='muted'>\u201cP(pass ALL phases)\u201d = probability one attempt clears every phase in "
             f"{program.get('label', program_name)} back to back. \u201cExpected attempts\u201d = on average how many "
             f"${size:,.0f} attempts it would take to pass once (1 \u00f7 pass probability) -- half of "
             "real attempts would need fewer, half more, since passing is a coin-flip-like process repeated "
             "until it lands. \u201cMedian days to pass\u201d only counts the attempts that DID pass.</p>")
    return "\n".join(h)
