# PROGRESS.md — where the build stands

Read this first in any new session. Update it after every ticket. See CLAUDE.md and
docs/ROADMAP.md for the full plan (checkboxes there are kept current too).

## Status: Phase 2 (replay trainer) done, including the gap-close pass Akash asked for. Ready for Phase 3.

### Phase 0 — done. Phase 1 — done.
See the git log for full detail; summary: v0 golden baseline captured, `nylab/` package built
(config-driven, matches v0 exactly to 1e-9), 11 tests passing after Phase 1.

### Phase 2 — Replay trainer MVP: done (see docs/ROADMAP.md for the per-ticket detail)

**What works, right now, via `python -m nylab replay`:**
- Local server (Python stdlib `http.server`, no Flask/FastAPI) + vendored `lightweight-charts`
  v4.2.0 (Apache-2.0, from npm) at `nylab/replay/static/vendor/` — genuinely offline, zero
  external requests from `index.html`.
- Date picker (jumps instantly — cache is an in-memory dict, tested at <1s per jump average),
  prev/next/random day (within the filtered list), start-time choice (17:00 prev / 02:00 / 07:00 /
  09:30), previous 10 days of HTF context auto-loaded.
- Day navigator table with live filters: date range, weekday checkboxes, "exclude thin days"
  (default on), plus two quick filters (London high/low raided in NY) as a taste of what the
  advanced DSL filter (Phase 6.1) will generalize. Presets save/load to `research/replay/presets.json`.
- Playback: step 1 bar, step 1 hour, play/pause at 4 speeds, jump-to-time. Timeframe switch
  M5/M15/H1/H4/D1, where every timeframe above M5 is a **server-side resample of only the bars
  already revealed** — proven equal to a manual resample in `test_higher_tf_matches_resample_of_revealed_bars`.
- **Overlays (closed this pass):** London/Asia high-low lines, PDH/PDL, **PWH/PWL** (new — see
  below), midnight open, **08:30** open, 09:30 open, plus **true shaded session boxes** for the 5
  non-overlapping top-level sessions (Asia / London KZ / NY AM / Lunch / NY PM) drawn as translucent
  `<div>`s positioned from the chart's own timeScale and redrawn on every pan/zoom — purely a
  function of fixed session-hour boundaries, never of revealed price, so there's nothing to leak.
  The narrower killzone/silver-bullet sub-windows still show as point markers (kept separate so the
  boxes don't nest). Blind mode hides the day-table dates and every overlay.
- **Mock trading (closed this pass):** BUY/SELL at **market, limit, or stop**. A limit/stop order
  rests on the chart as a dashed "PENDING" price line until price trades through its entry
  (`sim.check_pending_fill()`, same conservative same-bar trigger rule as the fill engine) or you
  cancel it. Once filled: required SL, optional TP, live lot-size preview (risk % -> lots, rounded
  down to 0.01), the same conservative same-bar fill rule as the backtest engine (stop wins ties),
  **SL/TP lines you can drag directly on the chart** (hand-rolled hit-test + reposition — v4 of the
  charting library has no built-in draggable price line), a **move-to-breakeven** button, and a
  **partial-close (50% of what's still open)** button whose dollars-at-risk are fixed at trade-open
  time so repeated partial closes stay exact. The R-math (`sim.compute_r`) now has exactly one
  implementation — the frontend calls it over `/api/sim/compute_r` instead of keeping its own
  second copy in JS, closing a small drift risk that existed before.
- Maven account panel: balance, day P&L%, daily/max drawdown used vs. limit, green/amber(50%)/red(75%)
  status, breach detection — reading live from `config/prop.yaml`'s verified account data.
- Trade journal: every closed trade can be logged (setup tag, rules-followed Y/N, emotion 1-5,
  notes) to `research/replay/trades.csv`, with a best-effort PNG chart screenshot saved to
  `research/replay/shots/` (via `lightweight-charts`' own `takeScreenshot()`).
- **No-leak proof:** `tests/test_replay_api.py` (16 tests) checks 100 random (day, until) pairs for
  bars and levels never returning anything past `until`, checks every returned level's
  `available_at_h` against `nylab.days.COLUMN_DOCS` (now including `pwh`/`pwl`), cross-checks H1
  resampling against a manual pandas resample, and covers the new limit/stop pending-order logic.
  `tests/test_replay_server_integration.py` (4 tests) launches the real HTTP server as a subprocess
  and hits every route, including the two new ones (`/api/sim/pending_fill_check`,
  `/api/sim/compute_r`).
- `pytest -q`: **31 passed** (11 Phase 0/1 + 16 replay-logic + 4 server-integration).

**New in `nylab/days.py`: `pwh`/`pwl` columns.** Previous-week high/low — the max(day_high) and
min(day_low) over the previous *completed* ISO calendar week (Mon-Fri, since weekend `td`s never
exist), mapped onto every day of the following week. `available_at_h` is -7, same status as
PDH/PDL, because by the time this week starts, last week is entirely historical. This is a
genuinely new column v0 never had — not a refactor of an existing one — so
`tests/test_nylab_phase1.py::test_days_csv_matches_golden` was loosened from "the column set must
match exactly" to "every column v0's golden output had must still be present and unchanged"; it
still fails immediately if any v0-era number drifts.

**Still not done, on purpose — deferred to Phase 6 as the roadmap already planned:**
- **Challenge mode** — the roadmap always slotted this under ticket 6.6, not 2.6, and nothing it
  needs was built in Phase 2. Not bolted on early.
- Drawing tools (horizontal line, rectangle, Fibonacci/OTE) — REPLAY_TRAINER.md S6, ticket 6.x.
- Stats tab (replay trades -> expectancy/win-rate by setup/session) — REPLAY_TRAINER.md S8, ticket 6.7.
- Advanced DSL filters, hide-outcome spoiler columns, news markers, review-mode label overlay —
  all Phase 6 (6.1-6.5), and several of them depend on things that don't exist yet either way
  (session character labels are Phase 5, the news calendar is Phase 4).

None of the above block using the trainer for its main job. Everything REPLAY_TRAINER.md S9
actually asks for out of Phase 2 now holds, tested — see docs/ROADMAP.md's Phase 2 **Accept** line
for the item-by-item detail.

**Honesty note on verification:** all 31 automated tests pass, including a live subprocess hitting
the real HTTP server. What I have *not* done is watch the drag-SL/TP interaction or the shaded
boxes render in an actual browser with my own eyes — that needs a real display, which this session
doesn't have on your machine. If either looks off when you try it (a box in the wrong place, a
price line that's fiddly to grab), tell me what you see and I'll fix it directly rather than
guessing.

## How to run it

1. Build/refresh the cache from your real data: `python -m nylab run data/EURUSD_M5_....csv`
   (writes `data/cache/bars_M5.parquet` + `days.parquet`).
2. `python -m nylab replay` — opens `http://127.0.0.1:8765` in your default browser.
3. Nothing else needed; Ctrl+C in the terminal stops the server.

## Repo changes made outside the roadmap tickets

- Vendored `lightweight-charts.standalone.production.js` (v4.2.0, Apache-2.0) + its LICENSE file
  into `nylab/replay/static/vendor/` — fetched via npm in the sandbox (Akash's own machine's
  network doesn't reach unpkg/jsdelivr directly; npm's registry did work), then written into the
  connected folder. No further internet access needed to run the trainer.
- `.gitignore`: added `research/replay/{trades.csv,presets.json,drawings/,shots/}` and
  `tests/fixtures/_replay_cache/` (test-only cache) as generated/runtime state, not source.

## Open questions for Akash (not blocking)

Same three as after Phase 1 (Maven program confirmation, broker tz convention, CLAUDE.md's stale
+10%/+8% text) — nothing new this phase.

## Next up

Moving to **Phase 3 — Ledger, hypothesis YAML, honest stats** per Akash's go-ahead: hypothesis
YAML + safe DSL, porting v0's 15 hypotheses (H001-H015), look-ahead rejection by decision_time_h,
an append-only ledger with Bonferroni + Benjamini-Hochberg correction (global and per family) and
Wilson confidence intervals, and a `hypothesis add` scaffold. Acceptance target: AT-01 and AT-02 on
the single-session planted-edge fixture.

The project has 11 phases total (0 through 10): 0 Reproduce v0, 1 Package refactor, 2 Replay
trainer MVP (done), 3 Ledger/hypothesis stats (next), 4 Economic calendar, 5 All sessions + session
character, 6 Replay trainer v2 (the deferred items above land here), 7 ICT features & models,
8 Verification/robustness/prop simulation, 9 Daily automation, 10 Research loop (ongoing).
