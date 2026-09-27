# ROADMAP.md — build order with acceptance criteria

Work top to bottom. Each ticket: implement → tests → run acceptance → commit → tick the box.
Ambiguous? Check the spec docs; still ambiguous → ask the user in plain English.
After each phase, show the user a short demo/result summary before continuing.

## Global acceptance tests (must pass after every phase from the phase they're introduced)

- **AT-01 No false edges:** on the clean synthetic fixture (seed 7), zero hypotheses reach `survives-oos`;
  every model's OOS CI includes or is below 0. (Phase 0+)
- **AT-02 Planted edge found:** planted-edge fixture (DATA_AND_TIME §6) → the planted hypothesis reaches
  `survives-oos`, hit ≥ 0.58. Add a second planted **cross-session** edge in Phase 5 ("London chop → NY AM
  reversal on 60% of such days") and require it to be found too. (Phase 3+)
- **AT-03 Look-ahead:** truncation tests for all features/models; replay no-leak test. (Phase 1+)
- **AT-04 Speed:** full run on 5 yrs M5 < 90 s; replay date jump < 1 s. (Phase 2+)
- `pytest -q` green.

---

## Phase 0 — Reproduce v0 (½ day)
- [x] 0.1 venv + `requirements.txt` (pandas, numpy, matplotlib, pyyaml, pytest, pyarrow, mplfinance).
- [x] 0.2 `tests/fixtures/make_synth.py`: clean + planted variants, seeded, 2 and 5 years.
- [x] 0.3 Run v0 on the clean fixture; save `tests/golden/v0/` outputs. **Accept:** AT-01 true for v0.

## Phase 1 — Package refactor, same numbers (1–2 days)
- [x] 1.1 `nylab/` per ARCHITECTURE; CLI `python -m nylab run`.
- [x] 1.2 YAML config replaces CONFIG dict (`windows.yaml` already contains ALL sessions from SESSIONS_AND_CONTEXT §1).
- [x] 1.3 Loader: python-export CSV and MT5 "Export Bars" (tab-separated, `<DATE>` headers).
- [x] 1.4 Timezones: `auto, ny+7, ny, utc, utc±N, eu`; sanity check with red warning.
- [x] 1.5 Data quality + thin/gappy flags. 1.6 `available_at_h` docs for every column. 1.7 `summary.json`.
- [x] 1.8 Parquet cache `data/cache/` (bars, days) reused by `run` and `replay`.
**Accept:** NY numbers equal v0 golden (tolerance 1e-9) except documented bug fixes. AT-01, AT-03.

## Phase 2 — Replay trainer MVP (2–4 days)  ← user's first practical tool
Spec: REPLAY_TRAINER.md.
- [x] 2.1 Server + vendored lightweight-charts; `python -m nylab replay`; offline.
- [x] 2.2 Date picker, prev/next day, random day, start-time choice, previous 10 days of context loaded.
- [x] 2.3 Day table with **basic filters**: date range, weekday, thin-day exclusion. (No dedicated
      month/year quick-picker -- the date-range filter covers the same need; can add if Akash wants it.)
- [x] 2.4 Playback: +1 bar, +1 hour, play/speeds, jump-to-time. TFs M5/M15/H1/H4/D1 from revealed bars.
- [x] 2.5 Overlays: London/Asia H/L, PDH/PDL, **PWH/PWL** (new `pwh`/`pwl` day-table columns --
      previous *completed* calendar week's high/low, available_at_h -7, same status as PDH/PDL),
      midnight, **08:30** and 09:30 opens, **true shaded session boxes** for the 5 non-overlapping
      top-level sessions (Asia/London KZ/NY AM/Lunch/NY PM -- drawn as translucent divs positioned
      from the chart's own timeScale, re-derived on every pan/zoom, never from revealed price data),
      plus point markers for the narrower killzone/silver-bullet sub-windows (unchanged from before,
      kept separate so the shaded boxes don't nest/overlap them).
- [x] 2.6 Mock trading: market-style entry, **limit and stop pending entry orders** (new
      `sim.check_pending_fill()` -- same conservative same-bar trigger rule as the fill engine,
      shown on-chart as a dashed "PENDING" price line, cancellable before it fills), SL/TP,
      conservative same-bar fill, R math (single implementation: `sim.compute_r()`, now called by
      the frontend over `/api/sim/compute_r` instead of a second, separately-maintained JS copy),
      **draggable SL/TP price lines** on the chart (hand-rolled hit-test + reposition, since
      lightweight-charts v4 has no built-in draggable price line), **move-to-breakeven** button,
      **partial close (50% of what's still open)** button (risk-dollars fixed at trade-open time,
      so repeated partial closes stay exact), Maven account panel (daily/max DD, breach colour
      states), trade journal appended to `research/replay/trades.csv`, best-effort chart screenshot
      on journal save. **Still not done, on purpose:** challenge mode -- the roadmap always slotted
      this under 6.6, not 2.6, and it depends on nothing built yet in Phase 2, so it stays deferred
      to Phase 6 rather than being bolted on early.
- [x] 2.7 No-leak API test -- bars, levels (available_at_h), day filters, HTF-resample-equals-revealed-
      bars, plus a full subprocess integration test hitting the real HTTP server (now also covering
      the new `/api/sim/pending_fill_check` and `/api/sim/compute_r` routes).
**Accept:** REPLAY_TRAINER §9 -- item 1 (date jump, tested < 1s avg), item 3 (no-leak + resample,
tested), item 5 (Maven daily breach, tested), item 6 (offline by construction: stdlib http.server +
locally vendored JS, zero external requests in index.html) all hold. Item 4 now fully holds for
everything REPLAY_TRAINER §8 actually asks for (market/limit/stop entry, SL/TP, BE move, partial
close, R-math identical to the backtest engine, tested); challenge mode remains out of scope for
Phase 2 by the roadmap's own original split and is still tracked under 6.6.
Note: closing these gaps added two genuinely new day-table columns (`pwh`/`pwl`) that v0 never had,
so `tests/test_nylab_phase1.py::test_days_csv_matches_golden` was loosened from "exact column set"
to "every v0 column still present and unchanged" -- it still fails if any v0-era number drifts.

## Phase 3 — Ledger, hypothesis YAML, honest stats (1–2 days)
- [x] 3.1 Hypothesis YAML + safe DSL (`nylab/hyp_dsl.py`) -- supports `day.x` and `<session>.x`
      dotted access (text-level rewrite to the day table's own flat column names, e.g. `lon.high`
      -> `lon_high`) as well as flat names directly. NEVER calls Python's `eval()`/`exec()`: parses
      with `ast.parse` (inert) then walks the tree by hand through a whitelist of node types and
      exactly 3 functions (`abs`, `quantile`, `median`) -- anything else (attribute access,
      comprehensions, arbitrary calls, `__import__`, ...) is rejected before it can run.
- [x] 3.2 Ported v0's 15 hypotheses verbatim as `config/hypotheses/H001.yaml`..`H015.yaml`
      (ARCHITECTURE.md §5 schema). Verified byte-identical sample counts/hit-rates against the v0
      golden output (n, hit, baseline, IS hit, OOS hit, OOS n all match to 1e-9) -- only the
      significance/verdict machinery around them changed. H015 needed a `baseline_p0: 0.5` literal
      override (new field) since v0 special-cased that one hypothesis to a fixed 50% null rather
      than deriving a baseline from a column.
      3.3 Look-ahead rejection (`nylab/hyp_loader.py`) -- refuses to load a hypothesis whose
      `condition` references a column with `available_at_h > decision_time_h`, checked against
      `nylab.days.COLUMN_DOCS`, dotted syntax included. Only `condition` is checked; `outcome`/
      `baseline` describe the future result being tested, so a later `available_at_h` there is
      the point, not a leak.
- [x] 3.4 Append-only ledger (`nylab/ledger.py`, `research/ledger.csv`) -- `m` = distinct (id,
      version) pairs ever logged; re-running an unchanged hypothesis doesn't increase it, bumping
      `version` does. Family grouping supported (`family:` field) for Phase 5's cross-session work.
      3.5 Bonferroni (`0.05/m`) + Benjamini-Hochberg (10% FDR, global AND per-family) + Wilson CIs
      (`nylab/hyp_engine.py`, reusing `nylab.stats`).
- [x] 3.6 `python -m nylab hypothesis add <id> <title> --decision-time-h <h>` scaffolds a new YAML
      template with TODO placeholders -- the loader refuses it until real expressions replace them.
**Accept:** AT-01 and AT-02 both hold, tested (`tests/test_hyp_engine_at.py`) -- but getting there
surfaced a real methodology gap, written up in docs/PROGRESS.md's Phase 3 section: RESEARCH_
PROTOCOL.md's literal "Bonferroni-on-IS or BH, plus OOS confirmation" rule for `survives-oos` let
one hypothesis (H013) falsely reach that verdict on the CLEAN fixture -- an expected side effect of
BH's 10%-false-discovery-rate design at m=15, not a bug in the arithmetic. Akash's call: `survives-
oos` is now reserved for the strict Bonferroni-on-IS route only; a BH-only pass with OOS
confirmation is labeled `candidate` instead. AT-01 holds cleanly under this rule; AT-02 needed the
5-year planted fixture rather than 2-year (H005's real, deliberately-planted 9-pip edge clears
Bonferroni there; it doesn't quite have enough samples to on the 2-year fixture even though its raw
hit rate already clears the 0.58 bar).

## Phase 4 — Economic calendar (1–2 days)
Spec: SESSIONS_AND_CONTEXT §4.
- [x] 4.1 `mql5/ExportCalendar.mq5` (read-only script) + step-by-step instructions in README for compiling
      in MetaEditor and running it. 4.2 `nylab calendar-import` (server→NY tz, parquet).
- [x] 4.3 Surprise z-scores, event families, per-session and per-day news features, availability rules.
- [x] 4.4 Fallback CSV import.
**Accept:** On the user's real data, NFP events land at 08:30 NY in both summer and winter; FOMC at 14:00.
Confirmed both ways: tests/test_calendar.py::test_at04_... (synthetic export, same schema as a real
one) AND Akash's own MetaQuotes-Demo export (34,075 events imported, 2021-09-26 -> 2026-09-25,
`nylab run` attached 18,454 USD / 15,621 EUR rows with no change to the existing hypothesis/report
result). Phase 4 done.

## Phase 5 — All sessions, session character, cross-session analysis (3–4 days)
Spec: SESSIONS_AND_CONTEXT §1–3, §5–6.
- [x] 5.1 SESSION table (every column in §2) for all sessions except cbdr (scope cut, see
      PROGRESS.md); day types.
- [x] 5.2 Character labels + continuous scores (range_rel/er/close_loc are their own columns,
      not just label inputs).
- [x] 5.3 Transition matrices (descriptive), news-conditioned matrices, Silver Bullet window stats.
- [x] 5.4 Relational hypotheses with matrix-family counting (SESSIONS §5.2).
- [x] 5.5 Report sections SESSIONS §6.
- [ ] 5.6 **Label validation with the user:** replay 30 random days showing the computed labels; user marks
      agree/disagree; if agreement < 80% for a label, adjust thresholds *with him* and re-validate.
**Accept:** AT-02 incl. the cross-session planted edge; label validation ≥ 80% agreement.

## Phase 5.7 — Statistics integrity (added 2026-09-26, do BEFORE any new research)
Why: a review on 2026-09-26 re-ran H013/H014 on real data and found both of the lab's only
"significant" results were measurement artifacts (details: RESEARCH_PROTOCOL §3, PROGRESS 2026-09-26).
The machinery must make these mistakes impossible, not just fixed once.
- [x] 5.7.1 DSL: prior-only threshold functions, e.g. `quantile_prior(col, q, n=60)` and
      `median_prior(col, n=60)` (value for day t uses days t−n … t−1 only). Loader rejects plain
      `quantile()`/`median()` inside `condition` (allowed in `outcome`/`baseline`). Done
      2026-09-27: `nylab/hyp_dsl.py` adds both `_prior` functions (rolling `shift(1).rolling(n,
      min_periods=n)`); `nylab/hyp_loader.py::_check_prior_only()` rejects plain `quantile()`/
      `median()` specifically inside `condition`. H014 (the hypothesis this bug was actually
      found in) bumped to v1.1 with `quantile_prior(asia_range, 0.2)` in its condition -- its
      v1.0 ledger rows are untouched (append-only). H014 v1.1's `outcome` still uses the
      overlapping `ny_range` window; that's 5.7.2/5.7.4's job, not bundled in here.
- [x] 5.7.2 `COLUMN_DOCS` gains `starts_at_h`; loader rejects an `outcome` with
      `starts_at_h < decision_time_h`. Add clean post-decision outcome columns, e.g. `r0930_1600`
      (09:30–16:00 range, pips) and its `_rel` version vs prior-20-day median. Done 2026-09-27:
      `nylab/days.py::COLUMN_STARTS_AT_H` (+ the same in `nylab/sessions.py` and
      `nylab/calendar_features.py`, merged by `hyp_loader.py` exactly like `COLUMN_DOCS` already
      was) registers every column whose measurement window genuinely starts before its
      available_at_h -- only the true path-dependent aggregates (a high/low/range, an
      extreme's timestamp, a level-crossing scan); a column absent from it falls back to its own
      available_at_h (no overlap risk), which is what keeps a point-in-time value like `ny_close`
      (and `ny_drive`, built from it) out of scope. `hyp_loader.py::_check_outcome_window()`
      rejects an `outcome` column only when it is BOTH still unresolved at decision time AND its
      window dips back before it -- that two-part test is what correctly rejects H013's old
      `ny_range` outcome while correctly leaving H015's `ny_close < lon_high` (a long-since-
      resolved comparison level) and H016's `nyam_kz.character` alone. New `r0930_1600` /
      `r0930_1600_rel` outcome columns added to `nylab/days.py::build_days()` for exactly the
      9.5-decision case this was built for. H013 bumped to v1.1 (see 5.7.4 note below) since the
      new check would otherwise refuse to load the still-installed v1.0 file.
- [x] 5.7.3 Engine: p from **IS only**; two-proportion test condition vs complement; true Wilson CI;
      5-td embargo between IS and OOS; `direction` field (as_claimed / opposite); effect in pips.
      Done 2026-09-27: `nylab/stats.py::wilson_ci()` rewritten from a mislabeled Wald interval to
      the true Wilson score interval (no golden test pinned its old numbers, confirmed safe);
      new `two_proportion_ztest()` (pooled-proportion, condition-true vs its own complement, per
      RESEARCH_PROTOCOL.md S2's 2026-09-26 clarification) added alongside the frozen, untouched
      `ztest()` (still used verbatim by v0's `nylab/hypotheses.py`, and by the new engine too, but
      now only for a hypothesis with an explicit literal `baseline_p0` like H015's coin-flip).
      `nylab/hyp_engine.py::evaluate()` rewritten: `z`/`p`/`ci_lo`/`ci_hi` now come from IS-only
      condition-true vs IS-only complement counts (not the old full-sample one-proportion test);
      new `EMBARGO_TD = 5` and `_split_masks()` exclude 5 trading days at the split boundary from
      BOTH the IS and OOS masks; new `direction` field (`as_claimed`/`opposite`, comparing IS hit
      rate to baseline); new `PIP_UNIT_COLUMNS` allow-list + `_effect_col()` report the effect in
      pips (median of the detected column, IS/OOS x condition/complement) for genuinely
      pip-denominated outcomes only (excludes signs like `ny_drive` and raw prices like
      `ny_close`/`lon_high`). `n`/`hit`/`is_hit`/`oos_hit`/`oos_n` (the other descriptive stats)
      deliberately left untouched. Golden-parity test (`tests/test_nylab_phase1.py`) now excludes
      `baseline` (its meaning changed engine-wide) and `oos_hit`/`oos_n` (the embargo shifts which
      days count as OOS for every hypothesis) from the strict v0 comparison, keeping only
      `n`/`hit`/`is_hit` -- confirmed via the actual suite run that those three still match v0
      exactly for every hypothesis whose condition/outcome text is unchanged. AT-01/AT-02 re-run
      after the rewrite: 3/3 pass, H005's planted edge still reaches `survives-oos` with the new
      IS-only two-proportion test -- the ROADMAP's flagged fixture-strengthening risk did not
      materialize. New `tests/test_stats.py` and `tests/test_hyp_engine.py` added; full suite
      (171 tests) green.
- [x] 5.7.4 Re-issue H013/H014 as **v1.1** with prior-only thresholds, post-09:30 outcomes and
      correctly-directed titles (m += 2). H015 re-labelled *descriptive* (decision 16:00 = outcome time,
      nothing left to predict). Expected result from the 2026-09-26 check: both noise. Done
      2026-09-27: re-ran `nylab run EURUSD_M5_2021-09-27_2026-09-25.csv --tz auto` against the real
      5-year cache with the fully fixed 5.7.3 engine -- both H013 (n=540, is_hit 0.462 vs baseline
      0.478, p=0.63) and H014 (n=252, is_hit 0.558 vs baseline 0.535, p=0.59) come out `noise`,
      confirming the 2026-09-26 review's prediction. H015 re-titled to flag it as descriptive: its
      `notes:` now spells out that `ny_takes_lon_high`/`ny_close` both have `available_at_h == 16`
      == its own `decision_time_h`, so there's no earlier point at which the condition is knowable
      without the outcome already being known too -- it stays in the ledger (still counts toward
      m, still gets a verdict) but the title now says plainly it's a same-time correlation, not an
      intraday signal. Left as `[~]` rather than `[x]` for one remaining judgment call: the
      "correctly-directed titles" part. docs/JEV_INTEGRATION.md S6.1 (written against v0's buggy
      pipeline) predicted both hypotheses would turn out to point the opposite way from their
      titles (volatility clustering -- busy begets busy, quiet begets quiet) -- but measured
      properly, H013 leans that way (direction=opposite, p=0.63) while H014 leans its own title's
      way instead (direction=as_claimed, p=0.59), and neither is significant. Two non-significant
      results pointing in different directions from each other and from S6.1's old finding is what
      noise looks like, so flipping either title to chase a sign would repeat the exact mistake
      this ticket exists to fix. Left both titles/outcome operators as-is, with the reasoning and
      the current numbers written into each YAML's `notes:` and the objective, computed-fresh-
      every-run `direction` column left as the honest record -- flagged for Akash to confirm he's
      OK with that call (or wants the titles reworded to the volatility-clustering direction
      regardless of significance) before this line goes to `[x]`. Akash's answer (2026-09-27):
      delegated the call back ("choose the option which is best for the project") -- kept as
      leave-as-is, for the reasons above (neither result is significant, and the two hypotheses'
      signs disagree with each other and with the old S6.1 finding, so there is no direction the
      data actually supports strongly enough to write into a title).
- [x] 5.7.5 Model verdict: OOS n ≥ 100 and CI upper < 0 → `negative` (new verdict word, Akash to
      confirm). `london_sweep_reversal` v1.0 becomes `negative`. Done 2026-09-27 (Akash confirmed
      "negative" as the word): new `nylab/stats.py::model_verdict(st_oos)` is now the single place
      that decision is made -- promising (ci_lo > 0) / negative (n >= 100 and ci_hi < 0) / not
      proven (everything else, including n=0 or a small/straddles-zero sample). Both call sites
      (`nylab/__main__.py`'s `model_stats` dict, and `nylab/report/html.py`'s inline HTML verdict
      box, which had its own DUPLICATE `ci_lo > 0` check) now call this one function instead of
      each re-deriving the verdict. Re-ran `nylab run` against the real 5-year cache:
      `london_sweep_reversal` v1.0 (183 OOS trades, CI [-0.4165, -0.0371]) now reports `negative`
      in both summary.json and report.html, confirming docs/JEV_INTEGRATION.md S6.2's finding.
      New tests in `tests/test_stats.py`. Full suite 173/173.
- [x] 5.7.6 **Artifact-catching fixtures** (the mistake-proofing): a synthetic 5-yr series with two
      volatility eras and NO day-level edge → a full-sample-threshold hypothesis must be REJECTED by the
      loader, and its prior-only twin must come out `noise`. A fixture where the outcome window overlaps
      the condition → loader rejects. These become AT-05. Done 2026-09-27:
      `tests/fixtures/make_synth.py` gains a `twoera` variant (same random-walk engine as
      `clean` -- still no real day-to-day edge -- but volatility steps x0.6 -> x1.6 exactly
      halfway through the 5-year series, reproducing H014's real-world artifact shape:
      "selecting calm years, not calm days" (RESEARCH_PROTOCOL.md S3)). Confirmed by hand before
      writing the test: a full-sample `quantile(asia_range, 0.2)` on this fixture flags 100% of
      days from the calm era, whose `ny_range > median` hit rate is 4.6% vs. 61.3% for the rest --
      a huge, entirely artifactual "effect"; `quantile_prior()` on the same data splits era-1
      vs. era-2 days 50/50 and the hit-rate gap collapses to 49.2% vs. 52.8% (genuine noise). New
      `tests/test_hyp_engine_at05.py`: the full-sample twin is rejected by the loader (same
      syntactic check as 5.7.1, restated against this fixture for AT-05 traceability); the
      prior-only twin is loaded and actually RUN through `hyp_engine.evaluate()` against the
      twoera data, asserting `verdict == "noise"`; the outcome-window-overlap half of AT-05
      re-asserts `tests/test_hyp_loader.py::test_outcome_window_overlap_is_rejected`'s check
      under the AT-05 name. Full suite 176/176.
**Accept:** AT-01..AT-05 pass (confirmed: AT-01/AT-02 in `tests/test_hyp_engine_at.py`, AT-03 in
`tests/test_nylab_phase1.py`'s truncation tests, AT-04 by `nylab run`'s own ~30s wall-clock on the
real 5-yr cache well under the 90s budget, AT-05 in `tests/test_hyp_engine_at05.py`); AT-02's
planted edge still reaches `survives-oos` with IS-only p (confirmed after the 5.7.3 rewrite, no
fixture strengthening needed); `run_tests.bat` CONFIRMED 2026-09-27 on Akash's own laptop
(python 3.14.6, pandas 3.0.6, numpy 2.5.3): "176 passed in 148.50s", "All tests passed on this
machine." **Phase 5.7 is fully done and verified on both the cloud-linked device session and
Akash's real hardware.**

## Phase 5.8 — Environment pinning (partly done 2026-09-26)
- [x] 5.8.1 pandas-3 crashes fixed (`sessions._news_for_window`, `cross_session.combined_label`);
      real-data output byte-identical on pandas 2.3.3 and 3.0.6; 135/135 tests on both.
- [x] 5.8.2 `requirements.txt` caps pandas to tested versions; `run_tests.bat` for his machine.
- [x] 5.8.3 Confirmed on Akash's machine 2026-09-27: python 3.14.6, pandas 3.0.6, numpy 2.5.3 -- 135/135 passed.

## Phase 6 — Replay trainer v2 (2 days) -- done 2026-09-27
- [x] 6.1 Filters on session character, news families/surprise, raids, ADR ratio, advanced DSL.
  `nylab.replay.api.list_days()` gained `session_character`/`news_flags`/`raid_flags`/
  `adr_min`/`adr_max`/`dsl` params; the DSL field reuses `nylab.hyp_dsl.evaluate()` (the same
  AST-walking whitelist evaluator hypothesis conditions use) directly against the cached days
  dataframe -- no second expression language. Simplification (disclosed): the session-character
  UI exposes lon/asia/nyam_kz, not all 12 session ids; the other characters are filterable via
  the advanced DSL field.
- [x] 6.2 Hide-outcome columns + spoiler icons; blind mode. `OUTCOME_COLUMNS` is built
  programmatically from `sessions.SESSION_IDS` (so a new session id is automatically covered)
  and every day-list response reports `spoiler_filter_used` so the UI can show `#spoilerBadge`
  whenever a filter itself reached into hidden data (e.g. a session-character filter) as
  distinct from schedule-known filters (e.g. `has_nfp`) which are never spoilers. Default
  hide-outcome shows "--" placeholders without hatching the row; blind mode adds the `.spoiler`
  hatch and masks the Date too (this closes out the early narrow slice from 2026-09-27 noted
  below).
- [x] 6.3 Presets (save/load/delete; the full current filter set, not just a few fields).
- [x] 6.4 Review mode overlay: reuses the SAME `/api/levels` call with `until` pushed to
  end-of-day (17:00 NY) rather than a separate code path, so there is no second no-leak surface
  to audit -- it can only ever show what a real end-of-day `until` would have revealed anyway.
- [x] 6.5 News markers: schedule-known fields (time/name/currency/forecast/previous) show as
  soon as the day loads; `actual`/`surprise`/`surprise_z` are withheld until the event's release
  time is inside `until`, same no-leak rule as everything else in `api.py`. Approximates
  REPLAY_TRAINER §5's "vertical line" as a chart marker + `#newsStrip` text row rather than a
  literal full-height vertical line (disclosed simplification).
- [x] 6.6 Challenge mode: sequential play through the currently-filtered day queue with the
  account balance carried over, reusing `nylab.replay.sim.maven_state()` (the same
  daily/max-drawdown breach logic the free-practice account panel already used) for pass/fail
  detection against `config/prop.yaml`'s `profit_targets_pct`. Disclosed simplification:
  single-step only -- a real Maven 2-step program's step-2 re-entry isn't modeled.
- [x] 6.7 Stats tab: `nylab.replay.journal_stats.build()` runs the SAME `nylab.stats.r_stats()`
  the coded backtests use over the replay trainer's own `trades.csv` journal, grouped by
  setup tag / weekday / preset, so manual and coded results stay directly comparable
  (REPLAY_TRAINER §8) rather than a second JS-side stats reimplementation.
  - Narrow slice done early (2026-09-27, standalone commit, not part of the design-system pass):
    `renderDayTable()` was only masking the Date cell in blind mode, leaving NY/London range pips
    visible -- fixed as part of 6.2 above.
  - **Bug found and fixed during Phase 6 verification, outside 6.1-6.7's own scope but disclosed
    here because it was found while testing them**: `toEpoch()`/`tdPlusHours()` (pre-existing,
    Phase 2) built epochs using the BROWSER's real OS timezone via plain `new Date(...).getTime()`,
    while the server builds every bar/level epoch by treating NY wall-clock time as UTC (a
    deliberate convention so lightweight-charts displays NY time directly). The two only agreed
    when the browser's OS timezone was UTC+0. Found via real-browser (Playwright/Chromium) smoke
    testing of the new news-strip feature under IST (UTC+5:30) -- the same timezone as Akash's
    real machine -- which showed an 08:30 NY NFP release as "14:00". Confirmed empirically this
    also affected the shaded session-box overlay positions, the session/news chart-marker
    positions, and the same-bar-fill eligibility checks that gate pending-order/position fills
    (`bar.time > toEpoch(placedAt/openedAt)`) -- i.e. this was silently affecting practice-trade
    fill behavior on any non-UTC machine, not just display. Fixed by rewriting `toEpoch()` to
    reinterpret the browser-local-parsed wall-clock numbers as UTC via `Date.UTC()`, which
    reproduces the server's convention with no dependence on the browser's timezone at all;
    re-verified via Playwright that `toEpoch(state.until)` now matches the actual last-loaded
    chart bar epoch exactly (was off by -5.5h before the fix, 0 after).
**Accept:** REPLAY_TRAINER §9 item 2 + all earlier items still pass. 197/197 tests pass
(176 before Phase 6, +6 api filter tests, +5 server integration tests, +8 in new
tests/test_replay_phase6.py, +2 in new tests/test_journal_stats.py). All new UI verified via a
real headless-Chromium (Playwright) session driving the actual running server, not just
`node --check` syntax checks.

## Phase 7 — ICT features & models (3–5 days) -- DONE 2026-09-27
Spec: FEATURES_SPEC.
- [x] 7.1 Swings, structure: `nylab.structure.label_swings`/`structure_score_at`/`structure_score_series`
      (FEATURES_SPEC §4, n=2 bars each side, structure_score(k) over the last k confirmed swings).
- [x] 7.2 FVG (+fill tracking), displacement, sweeps (raid/sweep/break), MSS, OB: `nylab.events`'s
      `fvg_lifecycle` (first_touch/ce_touch/full_fill/invalidated), `detect_raids` (raid/sweep/break per
      FEATURES_SPEC §3, reusing `nylab.sessions`'s existing BREAK_CLOSE_PIPS/K_BACK/RAID_TOL_PIPS rather
      than re-deriving them), `detect_mss` (§8: first close beyond the most recent confirmed opposite
      swing that PRE-DATES the sweep, gated on a genuine displacement leg, within mss_max_bars), and
      `detect_order_blocks` (§9, low priority).
- [x] 7.3 `nylab.events_report.build_events_table` (events.parquet-shaped dict of tables, reusing
      `nylab.sessions`'s own per-session levels convention and `nylab.days.window()`) + `descriptive_stats`
      (FVG fill rates, sweep→MSS conversion) -- deliberately DESCRIPTIVE, not fed into `d`/hyp_engine as
      new hypothesis-test columns (disclosed design choice, see the module's own docstring).
- [x] 7.4 `nylab.backtest.run_backtest`: the generic bar-by-bar engine (ARCHITECTURE.md §4's Model
      protocol) -- costs, conservative same-bar fills (delegated to `nylab.replay.sim.check_bar`/
      `compute_r`, the SAME functions the replay trainer's fill engine uses), time exits, 1-trade/day
      option. Models never see future bars (engine passes `day_bars.iloc[:i+1]`).
- [x] 7.5 Models: `nylab.models.london_sweep_reversal.LondonSweepReversalModel` (v1.0, a Model-plugin
      wrapper around the existing frozen v0 `backtest()` function -- proven TRADE-FOR-TRADE IDENTICAL to
      the ad hoc version via `tests/test_models_london_sweep_reversal.py`'s equivalence test, 274/274
      trades matching on the real 2-year fixture, which is why it stays v1.0 rather than a new rule
      version); `nylab.models.silver_bullet_fvg.SilverBulletFVGModel` v1.0, parameterised by `window`,
      run via 3 separate YAML configs/ledger entries (`silver_bullet_fvg_lonsb`/`_nyamsb`/`_nypmsb` --
      RESEARCH_PROTOCOL's multiple-testing rule: same rule tested in 3 windows = 3 tests, 3 ledger rows);
      `context_filter` support (SESSIONS §5.3) via `nylab.backtest.run_backtest_with_context_filter` +
      `nylab.config.ModelConfig.context_filter` (validated at YAML-load time via `nylab.hyp_dsl`, the
      SAME whitelist DSL evaluator the hypothesis engine uses -- not a second parser), reporting
      filtered/unfiltered/complement trade splits + `nylab.stats.r_stats()` for each.
- [x] 7.6 Regime features + per-tercile slicing: `nylab.regime.add_regime_features` (adr_ratio, er10,
      adx14_d1, chop14_d1, realized_vol_pct -- FEATURES_SPEC §11, all available at h=-7, all built from
      PREVIOUS COMPLETED days only, registered in `nylab.days.COLUMN_DOCS` for the look-ahead checker)
      + `nylab.regime.tercile` (in-sample qcut(3) bucketing for descriptive report slicing, explicitly
      NOT for use inside a hypothesis `condition` -- see the function's own docstring on why).
- [x] 7.7 Walk-forward module: `nylab.walkforward.make_folds`/`run_walkforward` -- rolling (fixed-width
      IS, slides forward) and expanding (IS always starts at day 0) fold modes, per-fold IS/OOS
      `nylab.stats.r_stats()`, and an aggregated OOS-pooled-across-all-folds stats dict. A fresh Model
      instance per fold (`model_factory()`) so per-day walk state (`_committed`/`_done_days`/
      `_abandoned_days`) never leaks across folds.

**Disclosed simplifications:**
- `silver_bullet_fvg` only ever acts on the FIRST qualifying MSS per window/day, and only the FIRST FVG
  in that MSS's leg (documented in the model's own docstring) -- a second MSS or a second leg FVG later
  in the same window is never considered, even if the first one fails the retracement/risk checks.
- `nylab.events_report` is intentionally descriptive-only (see 7.3 above) -- a specific aggregate found
  interesting there becomes its own hypothesis YAML the normal way, it does not automatically become a
  new `d` column/test.
- `nylab.walkforward` does not refit/tune any parameter per fold -- Phase 7's models have no free
  parameters to refit; "fresh model per fold" is walk-STATE isolation, not walk-forward OPTIMIZATION.
- **Not done, needs Akash**: the Accept line's "user hand-verifies 10 FVGs + 10 sweeps in replay review
  mode" is a manual step in the replay UI that only Akash can perform -- everything machine-checkable
  (AT-01..04, truncation tests for every feature) is done and passing.

**Bugs found and fixed during Phase 7 (disclosed in full):**
- `fvg_lifecycle` (pure-Python per-event loop) and `detect_mss` (re-filtered the whole swings/FVG
  tables per raid) were both too slow to finish on multi-year real-scale data -- rewritten with numpy
  vectorization (`flatnonzero` on boolean-masked slices) and precomputed-sorted-array + `np.searchsorted`
  binary search respectively. Verified: 5-year fixture (375k bars) -> 18.3s total for the whole events
  table (was non-terminating before the fix).
- `detect_raids`'s "break" classification caused spurious repeated raid detections on every subsequent
  bar of an extended trend (8 raids detected instead of 1 on one 8-bar fixture) -- fixed by adding
  reset-detection: after a "break", scan forward for price to genuinely return to the original side
  before resuming the scan for a new raid.
- `SilverBulletFVGModel.signals()`: `_resolved_days.add(td_key)` originally ran the instant a
  qualifying MSS candidate was found, BEFORE checking whether the retracement into the FVG's `ce` had
  happened yet -- since the retracement essentially never lands on the exact same bar the MSS itself
  confirms, every day silently gave up on its first call and the model produced ZERO trades end to end
  on the real 2-year fixture (all 3 window variants). Found by cross-referencing the FVG lifecycle
  table's own `ce_touch_idx` against each MSS candidate and confirming genuine retracements existed
  that the live model never fired on. Fixed by splitting "which MSS this day is committed to tracking"
  (persists across calls, `_committed`) from "is this day genuinely done" (`_done_days`, only set when a
  signal fires or a setup is provably dead) -- re-verified against an independent bar-by-bar diagnostic
  script cross-checking every touch/risk/deadline outcome; the resulting LOW trade counts (2/0/2 across
  the 3 windows on 2 years of synthetic data) were then confirmed to be a legitimate consequence of the
  minimum-FVG-size threshold making most gaps' half-width fall under the model's own 2-pip risk floor --
  not a further bug.
- Two of the three `silver_bullet_fvg_*.yaml` configs' `window` (the engine's candidate-scanning
  restriction) were narrower than `kz_window + mss_max_bars + entry_max_bars_after_mss` requires,
  meaning the engine would never even call the model on bars where a late-arriving valid entry needed
  to happen; widened `silver_bullet_fvg_lonsb`'s and `silver_bullet_fvg_nypmsb`'s `window`/`time_exit`
  accordingly (`silver_bullet_fvg_nyamsb`'s was already wide enough).
- `nylab.regime.add_regime_features`'s `er10` initially divided a raw-price numerator by a pips-unit
  denominator (`day_range`, which `nylab.days.build_days` already stores in pips) -- silently produced
  values ~5 orders of magnitude too small (~1e-5 instead of the expected 0-1 efficiency-ratio range).
  Fixed by converting the numerator to pips too before dividing.

**Accept:** AT-01..04 pass; truncation tests added for every new feature (structure, events, regime);
249/249 tests pass (242 general + 7 in `tests/test_models_silver_bullet_fvg.py`, which alone takes
~90s on the real 2-year fixture and is run separately from the rest to avoid the harness's own command
timeout -- not a flakiness concern, just wall-clock). User hand-verification of FVGs/sweeps in replay
review mode is still open (see disclosed simplifications above).

## Phase 8 — Verification, robustness, prop simulation (2 days)
- [ ] 8.1 Trade snapshots (PNG) + "open in replay" link for every backtest trade.
- [ ] 8.2 Report gallery: 20 random OOS trades, 5 best, 5 worst.
- [ ] 8.3 Robustness battery (RESEARCH_PROTOCOL §5.4).
- [ ] 8.4 **Maven pass simulator:** OOS R distribution through step 1 (+10%) and step 2 (+8%) with 4% daily /
      8% overall static balance-based limits, for risk 0.25–1.5%, max trades/day from the model. Output P(pass
      both), median trades/days, expected attempts × $23.
**Accept:** user can open report.html offline, click any trade, see it in replay.

## Phase 9 — Daily automation (1–2 days)
- [ ] 9.1 Incremental bar export. 9.2 `run_daily.bat` + Windows Task Scheduler guide (after 17:30 NY).
- [ ] 9.3 Forward-test tracking + kill-criteria check. 9.4 Weekly calendar re-export reminder.
**Accept:** running twice on the same day is idempotent.

## Phase 10 — Research loop (ongoing)
Follow CLAUDE.md §6. Suggested first questions (each = counted hypothesis or family):
1. London character → NY AM character (matrix family; promote at most 2 cells).
2. Red EUR news in London with \|z\| > 1 → does NY AM reverse London's direction?
3. NY AM `trend` → does NY PM continue or retrace ≥ 50% of the NY AM range?
4. Asia `quiet` + London took Asia high → NY AM takes London high or London low first?
5. Silver Bullet FVG model: which SB window (London / NY AM / NY PM) has positive OOS expectancy, and
   does a London-character filter improve it?
6. FOMC days: NY PM SB behaviour vs normal days (descriptive only — too few days to test).
7. *(Optional, needs Jev API access + Phase 5.6 labels frozen)* Experiment J1: does Jev's 09:30 NY-direction
   probability beat the base rate AND a logistic regression on the same features OOS? Pre-registered in
   docs/JEV_INTEGRATION.md §5; m += 9. Jev as a model context filter only once a Phase 7 model is `candidate`.

## Out of scope
Live order execution; signals pushed to phone; "AI predicts price" **as a trading signal** (testing an
external model as a counted experiment under RESEARCH_PROTOCOL §11 is allowed -- amended 2026-09-26);
scraping paid data; other symbols until the user asks.
