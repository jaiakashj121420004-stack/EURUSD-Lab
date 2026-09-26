# JEV_INTEGRATION.md — should this lab use Jev (TypeSafe AI), and how?

Written 2026-09-26 after reading every doc, config, result and the ledger in this repo and
researching Jev from its vendor docs plus third-party write-ups (sources at the bottom).
Jev launched 2026-09-15, so everything below is about a model that is 11 days old.

**Verdict in one line:** Jev *can* be integrated (Python SDK, cheap API), but it is not the
missing piece. The lab has no proven edge yet, and Jev can't create one. It only makes judgments
fast and cheap, and speed and cost aren't this project's bottleneck. There is one experiment worth
running and one optional helper role. Both are specified below, and neither lets Jev near the rules
that keep you safe.

---

## 1. What Jev actually is (verified, not assumed)

| Property | Fact | Why it matters here |
|---|---|---|
| Type | "System One" decision model: text state in → typed answers out. Three question types: **Noul** (yes/no → probability), **Choice** (options → probability each), **Score** (ordered levels → distribution) | It **cannot write text or reason out loud**. It only answers questions you define in advance |
| Speed / cost | 70–500 ms per call; $0.042 per million input tokens, output free | Scoring all 1,295 days of your history costs well under $1 |
| Context | 64k tokens per request, **32k for state + longest question** | A full day of M5 bars as text won't fit comfortably. Feed it features, not bars |
| Input | Text/JSON only, no images; English best | It can't look at your charts |
| Customisation | **No fine-tuning, no LoRA** on your data | It can't learn your ICT style or your Codex definitions |
| Vendor-listed weaknesses | "weak on numeric precision and date comparison", "distracted by large irrelevant state", "affected by adversarial content" | Prices, pips and times are *exactly* numeric/date data |
| Calibration claim | "higher confidence means higher accuracy". Trained on **synthetic** data, measured on the vendor's own workflows | Nobody has independently checked it, and **never on markets**. (See §3.1) |
| Determinism | Probabilistic; option order in a Choice can move the answer; aliases (`jev-latest`) move | Must pin `jev-1.13.0` and cache every answer, or backtests aren't reproducible |
| Security | Documented prompt-injection: a fake "approval" field dropped one block probability 0.76 → 0.48 | Never let it enforce a rule that matters |
| Access | Early access via console.typesafe.ai; `pip install langchain-typesafe` or TypeSafe SDK, `TYPESAFE_API_KEY` | Needs internet + a key, so it can't live inside the offline replay trainer by default |

**Public trading use so far:** every project I found follows the pattern "Jev judges, code
executes". These include crypto market-making on Monad/Hyperliquid, a Hong Kong stock direction
classifier and an FX "auditor" that checks whether an LLM's trade call agrees with its own thesis.
**None of them publishes evidence of profit.** The one FX project hadn't made a single production
call yet. A 2026-09-20 survey found no dedicated forex project at all.

---

## 2. Where this lab stands today (the part that decides everything)

From `reports/20260925-1914/summary.json` and `research/ledger.csv`:

- **13 of 16 hypotheses are noise.** Every *directional* idea (London direction → NY, premium/
  discount, pre-NY raids, Judas 08:30, previous day) sits within a few points of the base rate.
- **The two "significant" ones (H013, H014) are about range, not direction.** They also point the
  **opposite way to their titles** (see §6.1).
- **The only model, `london_sweep_reversal` v1.0, loses money out-of-sample:** 183 OOS trades,
  expectancy **−0.23 R** after costs, 95% CI **[−0.42, −0.04]**, entirely below zero. It's labelled
  "not proven", but a CI wholly below zero on n ≥ 100 is evidence of a *negative* edge (see §6.2).

**Trader's read:** the lab is working exactly as designed. It is refusing to let you fool
yourself, and the result is "no directional edge found yet". Better tools don't fix that. Finding a
real, repeatable market behaviour does (Phase 7 models, Phase 8 robustness + Maven pass simulator).
An AI layer on top of zero edge gives you zero edge, just faster and more confidently.

---

## 3. Every way Jev could plug in, judged one by one

### 3.1 Jev as the signal ("will NY drive up today?") — ❌ not as a signal. ✅ one counted experiment

**Why not as a signal.** Jev's "calibration" means its probabilities match accuracy on the kinds of
tasks it was trained on. It has **no knowledge of EURUSD's conditional return distribution**. So
"0.68 up" is a well-formatted number that looks calibrated but isn't. The only calibration that
counts is empirical, measured on your own data. Its documented weaknesses (numbers, dates) hit
exactly what market state is made of. Its option-order sensitivity and non-determinism break the
lab's reproducibility rule.

**Why it's still worth one test.** It's cheap (<$1 for the full history) and falsifiable, and it
settles your question with data instead of opinion. See §5 for the protocol (Experiment J1).
**Prior expectation: noise.** Every directional hypothesis you've tested with the same information
came back noise, and Jev sees nothing your features don't.

### 3.2 Jev labelling session character (trend/chop/reversal…) — ❌

The rule-based labels are deterministic, pass truncation tests and are being validated against your
own eye (Phase 5.6, trend rule v2). Jev would bring back the subjectivity the rules removed. It would
also give different answers on re-runs and can't be tuned to your judgment (no fine-tuning). The
continuous scores (range_rel, er, close_loc) are already better statistics than any label.

### 3.3 Jev detecting ICT patterns (FVG, MSS, "clean setup") — ❌

FEATURES_SPEC defines these as exact rules on purpose, so they can be tested and truncated without
look-ahead. A model that is "weak on numeric precision" deciding whether `low_3 > high_1` is strictly
worse than one line of code.

### 3.4 Jev reading news — ❌ for now

MT5's calendar already gives importance, actual/forecast and surprise-z as numbers. Jev would only
help with *text* (e.g. "was this Fed speech hawkish?"). You have no free historical text feed, so it
can't be backtested, so it can't enter research. Maven's ±2-minute red-news rule is a timestamp
check. That's deterministic code, never a model.

### 3.5 Jev as a guardrail on Claude (block risky tool calls) — ❌ for hard rules

LangChain's AutoMode pattern uses Jev to veto risky agent actions. But your non-negotiables (no
`order_send`, append-only ledger, OOS untouched, no look-ahead) need 100% enforcement. Jev is
probabilistic and prompt-injectable (0.76 → 0.48 in a published test). Hard rules stay in code and
tests, as they are now.

### 3.6 Jev as a pre-trade filter on a model's trades (SESSIONS §5.3 "context filter") — ⏸ later

This is the most sensible *trading* use: "given the pre-entry context, should this Silver Bullet
setup be taken?" But a filter needs a model worth filtering. Filtering a negative-expectancy model
until it looks positive is textbook data-mining. **Gate:** only after a Phase 7 model reaches at
least `candidate`. Then run it as one counted filter test (same protocol as J1).

### 3.7 Jev as a discipline auditor in the replay trainer — ✅ optional, low stakes

Suppose you write your own trading plan as a checklist. Then Jev could check each logged replay trade
against it: "entered inside a killzone?", "stop beyond the sweep extreme?", "risk ≤ plan?". It would
also flag tilt patterns from your journal notes (emotion score, "revenge", "FOMO"). That is squarely
Jev's strength: judging whether text matches a stated standard. Why it's only optional:

- Claude can do the same thing, and at your volume (a handful of trades a day) Jev's speed and
  price advantage doesn't matter.
- The trainer is offline by design, so this must be off by default and fail silently without
  internet.

It **coaches**; it never gates or changes any number.

### 3.8 Jev in a future live loop — ❌ no benefit even then

EURUSD on M5 with ~1 trade/day at a prop firm doesn't need 70 ms decisions. A few seconds of Claude
latency is irrelevant, and so is Jev's speed. Live execution is out of scope anyway (rule 1).

---

## 4. The architecture, if/when Jev comes in

```
                ┌───────────────────────────────────────────────┐
                │  CLAUDE = the researcher / orchestrator         │
                │  designs hypotheses, writes code, reads         │
                │  summary.json, explains, keeps the ledger honest│
                └───────────────┬───────────────────────────────┘
                                │ runs
┌───────────────────────────────▼────────────────────────────────────┐
│  DETERMINISTIC LAB (ground truth — nylab/)                            │
│  MT5 bars + calendar → features (available_at_h) → labels → backtest │
│  → stats (Bonferroni/BH, IS/OOS) → ledger → report                   │
│  HARD RULES live here as code + tests: read-only MT5, no look-ahead, │
│  OOS sacred, costs on, Maven limits, news ±2 min                     │
└───────────────┬───────────────────────────────────┬────────────────┘
                │ state_at(td, decision_h)          │ trade + journal text
                │ (only columns with                │
                │  available_at_h ≤ decision_h,     │
                │  anonymised, as words/buckets)    │
        ┌───────▼────────┐                  ┌───────▼─────────┐
        │ JEV (J1 / 3.6) │                  │ JEV (3.7)       │
        │ a SUBJECT under│                  │ coach, optional │
        │ test, never an │                  │ never gates     │
        │ authority      │                  │                 │
        └───────┬────────┘                  └─────────────────┘
                │ probabilities → research/external/jev_cache.parquet
                │ (pinned version, sha256 key; re-runs read the cache)
                ▼
        back into the lab as ONE MORE COUNTED HYPOTHESIS / FILTER
```

Division of labour: **Claude thinks, the lab measures, Jev is measured.** Jev only gets promoted
from "subject" to "feature" through the same IS → OOS → Bonferroni → robustness path as any idea
of yours.

Practical wiring (Windows-side, per CLAUDE.md §5a — Claude's cloud sandbox can't reach the
TypeSafe API):
- `nylab/external/jev_client.py`: the only file that imports the TypeSafe SDK (same isolation
  pattern as `mt5_source.py`). Reads `TYPESAFE_API_KEY` from the environment; `.env` git-ignored.
- `nylab/external/state_text.py`: builds the text state from the DAY/SESSION tables, filtering
  columns by `COLUMN_DOCS[col] ≤ decision_h` (reuses the existing look-ahead machinery).
- `python -m nylab jev-score --experiment J1` → writes the cache. `nylab run` reads the cache
  only. That keeps the core pipeline and its tests fully offline and deterministic.
- `jev_score.bat` for you to double-click.

---

## 5. Experiment J1 — "Does Jev know anything about NY direction that the lab's features don't?"

Pre-registered here, **before** any data is seen. Changing any of it after results arrive = new version.

- **Question:** at 09:30 NY, Choice `ny_drive` ∈ {up, down} (same outcome as H001–H012).
- **State:** only DAY/SESSION columns with `available_at_h ≤ 9.5`, expressed as words and buckets
  (e.g. "London: range 1.8× normal, closed near its low, took the Asia high then reversed; no
  red USD news yet; 08:30 CPI released, surprise large-positive").
- **Anonymisation (memorisation control):** no dates, no year, no weekday-date pairs, no absolute
  prices (pips relative to the day's open / ADR multiples only), no raw news actuals (surprise
  bucket only). Jev may sit on a base model that saw 2021–2026 market history.
- **Option-order control:** ask twice, once as {up, down} and once as {down, up}, and average. The
  gap between the two runs is reported as Jev's own instability.
- **Baselines Jev must beat on OOS:** (a) the base rate; (b) a plain logistic regression on the
  *same* features. If Jev doesn't beat (b), it adds nothing a spreadsheet can't.
- **Metrics:** Brier score and log-loss vs both baselines. Also a **reliability curve**: when Jev
  says 0.70, does "up" happen ~70% of the time? That tests the calibration claim head-on. Plus hit
  rate when P ≥ threshold.
- **Degrees of freedom (all counted in the ledger):** ≤ 3 question wordings × ≤ 3 thresholds
  {0.55, 0.60, 0.65}, picked on IS only → m += 9. OOS run once.
- **Pass bar:** same as everything else: Bonferroni-on-IS + OOS same direction + beats the
  logistic baseline on OOS Brier. Otherwise the verdict is `noise` and Jev is dropped from signal
  research. Total cost ≈ $1.
- **Preconditions:** Jev API access; Phase 5.6 labels frozen (the state uses them).

---

## 6. Issues found in the lab while doing this review (independent of Jev)

Each of these was checked twice: once from the numbers in the report, once in the code.

### 6.1 H013/H014 "survived" in the opposite direction to their titles, with a full-sample threshold

- **H014** "Asia range in bottom 20% → NY range *above* median": hit **32%** vs baseline 50%.
  So a quiet Asia is followed by a *below*-median NY on ~68% of days. **H013** "ADR used >80% by
  09:30 → NY range *below* median": hit **39%** vs 50%. So a heavy early day is followed by a
  *larger* NY. Both are the same real phenomenon, **volatility clustering**: quiet begets quiet,
  busy begets busy. `hyp_engine.py` checks that IS and OOS agree with *each other*, not with the
  title's claim. That's why a refuted title shows as `survives-oos`/`candidate`.
- **Threshold look-ahead:** `quantile(asia_range, 0.2)` and `median(ny_range)` in the DSL are
  computed over **all five years, including OOS**. On 2022-01-03 at midnight you could not have
  known the 2021–2026 20th percentile. EURUSD volatility also shifted across these years, so a
  full-sample cut-off partly selects calm *eras* rather than calm *days*. That inflates the result.
- **Trading value if it survives the fix:** it's a *when* filter, not a *which way* signal. Skip
  or size down on quiet-Asia days, where targets are less likely to be reached. That's useful for a
  Maven account (fewer low-range days means less chop), but it's not an entry.
- **To do (needs Akash's OK, it bumps m):** add a prior-only threshold function to the DSL (e.g.
  `quantile_prior(col, q, 60)` over the previous 60 td, like `range_rel` already does). Re-issue
  H013/H014 as v1.1 with correctly-directed titles. Make the verdict record the direction relative
  to the claim.

### 6.2 A significantly negative model is labelled "not proven"

`nylab/__main__.py` sets model verdicts as `"promising" if ci_lo > 0 else "not proven"`. With 183
OOS trades and CI [−0.42, −0.04], the honest word is "negative edge", not "not proven" (which the
protocol reserves for small samples). **To do (Akash's call on the word):** add a verdict for
"OOS n ≥ 100 and CI upper < 0". Note that flipping the model isn't a free edge either: the 2R
target, the stop placement and costs aren't symmetric. Any "sweep continuation" idea is a new,
counted Phase 7 model.

### 6.3 CLAUDE.md still said Maven targets +10%/+8%

`config/prop.yaml` (verified from maventrading.com on 2026-09-24, and you chose the verified
numbers that day) has Standard 2-Step at **8% / 5%**, 4% daily, 8% max, static balance-based,
3 profitable days ≥ 0.5% per phase, no trading ±2 min of red news. CLAUDE.md now points to
prop.yaml instead of repeating numbers. Which Maven program you're actually on is still open.

---

## 7. Rule changes made on 2026-09-26 (each checked twice against the existing rules for conflicts)

1. **CLAUDE.md §3, new rule 10:** external/probabilistic AI models are research *subjects*,
   never enforcers of rules 1–9. Any output used in research is version-pinned and cached, and is
   evaluated under RESEARCH_PROTOCOL §11. *Checked:* strengthens rules 2, 3, 4 and 7. Relaxes none.
2. **CLAUDE.md §1:** Maven numbers now come from `config/prop.yaml` (fixes the stale 10%/8%).
   *Checked:* matches your 2026-09-24 decision recorded in prop.yaml's header.
3. **RESEARCH_PROTOCOL §3:** thresholds inside a hypothesis condition must come from prior data
   only (no full-sample quantile/median). *Checked:* this is rule 2 (no look-ahead) and rule 3 (OOS
   sacred) applied to thresholds. H013/H014 are now flagged non-compliant until re-issued (§6.1).
4. **RESEARCH_PROTOCOL §11 (new):** the protocol for testing external AI models (J1's shape,
   generalised). *Checked:* every step maps onto an existing rule (ledger counting, IS/OOS,
   Bonferroni, costs).
5. **ROADMAP "Out of scope":** "AI predicts price" now reads "AI predicts price **as a trading
   signal**; testing it as a counted experiment under RESEARCH_PROTOCOL §11 is allowed". Phase 10
   gains J1 as optional question 7. *Checked:* live execution, phone signals and scraping stay out
   of scope, unchanged.

Not changed, on purpose: rule 1 (read-only MT5, no live execution). Nothing here comes close to
justifying execution.

---

## 8. What actually moves you toward a funded account (priority order)

1. Finish **Phase 5.6**: your second label review (the page is ready).
2. **Fix §6.1** (prior-only thresholds, correctly-directed H013/H014 v1.1). Volatility clustering
   is the one real, reproducible effect the lab has found so far, and it should be measured cleanly.
3. **Phase 7**: `silver_bullet_fvg` in the three SB windows, with session context and the
   volatility filter as counted context filters.
4. **Phase 8**: robustness battery + Maven pass simulator. Only this tells you whether an edge
   survives a 4% daily / 8% max account.
5. *Then* J1, and 3.6 if a model reaches `candidate`. Jev's cost to try is near zero, so trying it
   late loses nothing.

*Not financial advice. Nothing here recommends trading anything live.*

---

## Sources
- TypeSafe — Introducing System One Models & Jev: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- TypeSafe docs — Models (limits, pinning, no fine-tuning): https://docs.typesafe.ai/models
- Wikipedia — Jev (AI model): https://en.wikipedia.org/wiki/Jev_(AI_model)
- LangChain — Building a harness with Jev: https://www.langchain.com/blog/building-a-harness-with-jev
- Wavect — Jev AI review (vendor limitations register): https://wavect.io/blog/jev-ai-decision-model-review/
- Langfuse — Using Jev for evals: https://langfuse.com/blog/2026-09-18-using-typesafes-jev-for-evals
- VentureBeat — prompt injection can influence Jev: https://venturebeat.com/security/companies-are-putting-jev-in-charge-of-ai-agent-decisions-and-prompt-injection-can-influence-the-verdict
- Jev finance & trading projects survey (2026-09-20): https://gist.github.com/drillan/6916b16e8ea31a8ec36c8f59d6483150
- DEV — JEV-assisted LLM trading (FX auditor): https://dev.to/nodefiend/jev-assisted-llm-trading-ofa
- jarrodwatts/jev-trader: https://github.com/jarrodwatts/jev-trader
