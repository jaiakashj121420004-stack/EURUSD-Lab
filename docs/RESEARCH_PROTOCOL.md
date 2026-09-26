# RESEARCH_PROTOCOL.md — how we avoid fooling ourselves

The single biggest risk of "an agent that finds patterns" is that it finds patterns in noise.
With 5 years of data and enough ideas, *something* always looks significant. This protocol is what
makes the output trustworthy. Formula references point to the user's *Codex Formula Handbook* (Part 11).

## 1. Splits

- **Chronological only.** Never shuffle days. Default: first 70% of td = IS, last 30% = OOS.
- **Embargo:** drop 5 td between IS and OOS (regime features use rolling windows).
- **Walk-forward (Phase 7+):** rolling windows of 12 months IS → 3 months OOS, step 3 months.
  Report each fold and the concatenated OOS equity curve. Parameters are re-chosen per fold
  *using IS only*. Walk-forward efficiency = OOS annualised R / IS annualised R.

## 2. Statistics to report

For **proportion hypotheses** (condition → outcome): N, hit rate, baseline (same outcome over all
eligible days, computed on the same split), Wilson 95% CI, z vs baseline, two-sided p, IS hit, OOS hit,
OOS N, lift = hit − baseline (percentage points).

For **models** (trades in R): N, win rate, expectancy (net), 95% CI (t-based and bootstrap 10k),
t-stat, profit factor, SQN, max drawdown in R, longest losing streak, per-year expectancy,
per-regime-tercile expectancy, cost as % of gross expectancy.

## 3. Look-ahead prevention (tests required)

- Every DAY column has `available_at_h`. The hypothesis loader rejects a hypothesis whose condition
  uses a column with `available_at_h > decision_time_h`.
- **Truncation test** for every feature and model: compute the feature/signals on the full day, then
  on the day truncated at bar i; values for bars ≤ i must be identical. Run for 50 random (td, i).
- Swing points: assert a swing at bar j is not visible to any computation before bar j + n.
- The engine asserts `exit_time > entry_time` and entry price ∈ [low, high] of the entry bar.
- **Thresholds in a `condition` use prior data only** (added 2026-09-26). A cut-off such as "Asia range
  in its bottom 20%" must be computed from days *before* the day being evaluated (rolling/expanding,
  like `range_rel`), never from a full-sample `quantile()`/`median()` that includes later days and OOS.
  Full-sample functions remain fine in `outcome`/`baseline`. Known non-compliant: H013, H014 v1.0
  (see docs/JEV_INTEGRATION.md §6.1); re-issue as v1.1 once a prior-only DSL function exists.
- **Direction check:** a verdict must say whether the effect runs the way the hypothesis *title*
  claims. A significant result in the opposite direction is reported as such, not as the title confirmed.

## 4. Multiple testing — the ledger

`research/ledger.csv` columns: `run_id, timestamp, kind (hypothesis|model), id, version, n, stat, p,
is_metric, oos_metric, verdict, notes`. Append-only.

- `m` = number of **distinct (id, version)** rows ever evaluated, including killed ones.
- Report both: **Bonferroni** (`p < 0.05/m`, strict) and **Benjamini-Hochberg** FDR 10% (lenient,
  for triage). A "candidate" needs BH; "survives-oos" needs Bonferroni-on-IS **or** BH plus an OOS
  result in the same direction with lift ≥ 3 pp (proportions) / OOS CI lower bound > 0 (models).
- Re-running an unchanged hypothesis on new data does not increase m; changing its definition does.
- Show the user `m` and the current thresholds at the top of every report.

## 5. Model-development rules

1. Write the rules in plain English first (in the model YAML `description`) — including stop,
   target, time exit, max trades per day, and what happens on news days.
2. Choose parameters from a **small, pre-declared grid** (≤ 20 combinations). Evaluate on IS only.
   Prefer parameter *plateaus* (neighbours also good) over the single best point. Record the grid
   size into the ledger as that many tests.
3. Run OOS once. If it fails, you may change the idea — but that's a new version, counted in m.
4. **Robustness battery** before any "promising" verdict:
   - cost ×1.5 and ×2 → still positive?
   - entry delayed by 1 bar → still positive?
   - each year separately → no single year contributes > 50% of total R?
   - remove the best 5% of trades → still positive?
   - Monte Carlo 10k shuffles → 95th-percentile max drawdown in R, probability of a 20-trade
     losing stretch; use for sizing advice (Formula Handbook 4.x).
   - thin/gappy days excluded vs included → similar?
5. Minimum evidence: OOS ≥ 100 trades preferred; 30–99 → "not proven — insufficient OOS sample".

## 6. Descriptive stats are not signals

Things like "the NY high forms between 09:30–10:30 on 38% of days" are **context**, not edges. They
are allowed in reports without significance testing, but must be labelled "descriptive". They
become hypotheses only when phrased as *condition known at decision time → future outcome*.

## 7. Forward test

A model that survives OOS + robustness goes to **forward test**: the pipeline runs daily on new
data (Phase 9) and appends `forward` trades to `research/forward/<model>.csv` without refitting.
After ≥ 30 forward trades compare with OOS expectancy (within the OOS CI = consistent). Only then
would the user consider demo execution — which is outside this project's scope.

## 8. Kill criteria (write them before forward testing)

Default: kill if rolling-30 expectancy < 0 for two consecutive non-overlapping windows AND the regime
tercile distribution is similar to IS. Log `killed` with reason in the ledger and JOURNAL.

## 9. What to say to the user

- Lead with the verdict word, then one sentence of evidence, then the next step.
  e.g. "**Noise.** The pre-NY London-high raid predicted a down drive 54% of the time vs 53% on all
  days (z = 0.4). Next: test it as a *filter* on the sweep-reversal model instead of as a signal."
- Never present a p-value without saying how many tests have been run.
- Always offer the chart snapshots so he can see the trades.

## 10. Cross-session research (the combinatorial trap)

With 6 sessions × 6 character labels × news states, there are thousands of "if X then Y" combinations —
guaranteed dozens of spectacular flukes. Rules (details in SESSIONS_AND_CONTEXT §5):
- Matrices are descriptive; cells with n < 25 are greyed and never promoted.
- Promoting a cell counts the **whole matrix** as tested (m += rows × cols), as a named family.
- BH within the family + global Bonferroni; OOS confirmation required; lift ≥ 5 pp for label outcomes.
- Prefer using session context as a **filter on a model** (one test per filter) over predicting direction.
- Session-character thresholds are frozen once validated (ROADMAP 5.6). Changing them = new version of
  every dependent hypothesis.


## 11. External AI models (Jev, LLMs) as research subjects (added 2026-09-26)

An external model's opinion is treated as one more hypothesis/filter, never as ground truth.
Full rationale and the first pre-registered experiment (J1): docs/JEV_INTEGRATION.md.
1. **State = only information available at decision time**: build it from DAY/SESSION columns with
   `available_at_h ≤ decision_time_h` (reuse COLUMN_DOCS); never raw future bars.
2. **Anonymise** against memorisation: no dates/years, no absolute prices (pips vs day open, ADR
   multiples), no raw news actuals (surprise buckets only).
3. **Pin and cache**: exact model version (never a moving alias), response cached keyed by
   sha256(state + schema + option order + version); pipeline runs read the cache only.
4. **Control option order** (ask in ≥ 2 orders, average, report the gap) for Choice-type outputs.
5. **Beat a dumb baseline**: base rate AND a logistic regression on the same features, on OOS Brier /
   log-loss; plot a reliability curve to test any "calibrated" claim directly.
6. **Count everything**: each (question wording × threshold) is one ledger test, chosen on IS only;
   OOS runs once. Same Bonferroni / OOS / robustness bars as §4–§5.
7. **Never gates execution or enforces a rule** (CLAUDE.md rule 10).
