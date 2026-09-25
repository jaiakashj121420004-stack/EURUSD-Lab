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
- [ ] 5.1 SESSION table (every column in §2) for all sessions; day types.
- [ ] 5.2 Character labels + continuous scores.
- [ ] 5.3 Transition matrices (descriptive), news-conditioned matrices, Silver Bullet window stats.
- [ ] 5.4 Relational hypotheses with matrix-family counting (SESSIONS §5.2).
- [ ] 5.5 Report sections SESSIONS §6.
- [ ] 5.6 **Label validation with the user:** replay 30 random days showing the computed labels; user marks
      agree/disagree; if agreement < 80% for a label, adjust thresholds *with him* and re-validate.
**Accept:** AT-02 incl. the cross-session planted edge; label validation ≥ 80% agreement.

## Phase 6 — Replay trainer v2 (2 days)
- [ ] 6.1 Filters on session character, news families/surprise, raids, ADR ratio, advanced DSL.
- [ ] 6.2 Hide-outcome columns + spoiler icons; blind mode. 6.3 Presets (save/load; agent-generated).
- [ ] 6.4 Review mode overlay of computed events/labels. 6.5 News markers (actual revealed at release).
- [ ] 6.6 Challenge mode (sequence of filtered days, Maven rules). 6.7 Stats tab.
**Accept:** REPLAY_TRAINER §9 item 2 + all earlier items still pass.

## Phase 7 — ICT features & models (3–5 days)
Spec: FEATURES_SPEC.
- [ ] 7.1 Swings, structure; 7.2 FVG (+fill tracking), displacement, sweeps (raid/sweep/break), MSS, OB.
- [ ] 7.3 `events.parquet` + descriptive event stats per session (FVG fill rates, sweep→MSS conversion).
- [ ] 7.4 Backtest engine (bar-by-bar, costs, conservative fills, time exits, 1 trade/day option).
- [ ] 7.5 Models: `london_sweep_reversal` (v0 rules, v1.0); `silver_bullet_fvg` v1.0 parameterised by window
      so the **same rules** can be run in London SB, NY AM SB and NY PM SB (3 separate ledger entries);
      `context_filter` support (SESSIONS §5.3).
- [ ] 7.6 Regime features + per-tercile slicing. 7.7 Walk-forward module.
**Accept:** AT-01..04; truncation tests for every feature; user hand-verifies 10 FVGs + 10 sweeps in replay review mode.

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

## Out of scope
Live order execution; signals pushed to phone; "AI predicts price"; scraping paid data; other symbols
until the user asks.
