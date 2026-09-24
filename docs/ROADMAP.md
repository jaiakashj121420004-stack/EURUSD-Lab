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
- [ ] 0.1 venv + `requirements.txt` (pandas, numpy, matplotlib, pyyaml, pytest, pyarrow, mplfinance).
- [ ] 0.2 `tests/fixtures/make_synth.py`: clean + planted variants, seeded, 2 and 5 years.
- [ ] 0.3 Run v0 on the clean fixture; save `tests/golden/v0/` outputs. **Accept:** AT-01 true for v0.

## Phase 1 — Package refactor, same numbers (1–2 days)
- [ ] 1.1 `nylab/` per ARCHITECTURE; CLI `python -m nylab run`.
- [ ] 1.2 YAML config replaces CONFIG dict (`windows.yaml` already contains ALL sessions from SESSIONS_AND_CONTEXT §1).
- [ ] 1.3 Loader: python-export CSV and MT5 "Export Bars" (tab-separated, `<DATE>` headers).
- [ ] 1.4 Timezones: `auto, ny+7, ny, utc, utc±N, eu`; sanity check with red warning.
- [ ] 1.5 Data quality + thin/gappy flags. 1.6 `available_at_h` docs for every column. 1.7 `summary.json`.
- [ ] 1.8 Parquet cache `data/cache/` (bars, days) reused by `run` and `replay`.
**Accept:** NY numbers equal v0 golden (tolerance 1e-9) except documented bug fixes. AT-01, AT-03.

## Phase 2 — Replay trainer MVP (2–4 days)  ← user's first practical tool
Spec: REPLAY_TRAINER.md.
- [ ] 2.1 Server + vendored lightweight-charts; `python -m nylab replay`; offline.
- [ ] 2.2 Date picker, prev/next day, random day, start-time choice, previous 10 days of context loaded.
- [ ] 2.3 Day table with **basic filters**: date range, weekday, month/year, thin-day exclusion.
- [ ] 2.4 Playback: +1 bar, +1 hour, play/speeds, jump-to-time. TFs M5/M15/H1/H4/D1 from revealed bars.
- [ ] 2.5 Overlays: session boxes (all sessions), Asia/London H/L, PDH/PDL, PWH/PWL, opens.
- [ ] 2.6 Mock trading + Maven account panel + journal CSV + screenshots.
- [ ] 2.7 No-leak API test.
**Accept:** REPLAY_TRAINER §9 items 1, 3, 4, 5, 6.

## Phase 3 — Ledger, hypothesis YAML, honest stats (1–2 days)
- [ ] 3.1 Hypothesis YAML + safe DSL (supports `day.x` and `<session>.x` dotted access).
- [ ] 3.2 Port v0's 15 hypotheses (H001–H015). 3.3 Look-ahead rejection by decision_time_h.
- [ ] 3.4 Append-only ledger; `m`; families. 3.5 Bonferroni + BH (global and per family); Wilson CIs.
- [ ] 3.6 `hypothesis add` scaffold.
**Accept:** AT-01, AT-02 (single-session planted edge).

## Phase 4 — Economic calendar (1–2 days)
Spec: SESSIONS_AND_CONTEXT §4.
- [ ] 4.1 `mql5/ExportCalendar.mq5` (read-only script) + step-by-step instructions in README for compiling
      in MetaEditor and running it. 4.2 `nylab calendar-import` (server→NY tz, parquet).
- [ ] 4.3 Surprise z-scores, event families, per-session and per-day news features, availability rules.
- [ ] 4.4 Fallback CSV import.
**Accept:** On the user's real data, NFP events land at 08:30 NY in both summer and winter; FOMC at 14:00.

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
