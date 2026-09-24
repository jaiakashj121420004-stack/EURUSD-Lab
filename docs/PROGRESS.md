# PROGRESS.md — where the build stands

Read this first in any new session. Update it after every ticket. See CLAUDE.md and
docs/ROADMAP.md for the full plan (checkboxes there are kept current too).

## Status: Phase 2 (replay trainer) mostly done -- two tickets partial, flagged below

### Phase 0 — done. Phase 1 — done.
See the git log for full detail; summary: v0 golden baseline captured, `nylab/` package built
(config-driven, matches v0 exactly to 1e-9), 11 tests passing after Phase 1.

### Phase 2 — Replay trainer MVP: mostly done (see docs/ROADMAP.md for the per-ticket detail)

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
- Overlays: London/Asia high-low lines, PDH/PDL, midnight open, 09:30 open, small session-start
  markers (label + time) for every session in SESSIONS_AND_CONTEXT.md §1. Blind mode hides the
  day-table dates and the overlay lines.
- Mock trading: BUY/SELL at market (fills at the last revealed bar's close — conservative, no
  peeking), required SL, optional TP, live lot-size preview (risk % → lots, rounded down to 0.01),
  the **same conservative same-bar fill rule** as the backtest engine (stop wins ties) implemented
  once in `nylab/replay/sim.py` and called by both the API and (indirectly) tested against the
  engine's R formula.
- Maven account panel: balance, day P&L%, daily/max drawdown used vs. limit, green/amber(50%)/red(75%)
  status, breach detection — reading live from `config/prop.yaml`'s verified account data.
- Trade journal: every closed trade can be logged (setup tag, rules-followed Y/N, emotion 1-5,
  notes) to `research/replay/trades.csv`, with a best-effort PNG chart screenshot saved to
  `research/replay/shots/` (via `lightweight-charts`' own `takeScreenshot()`).
- **No-leak proof:** `tests/test_replay_api.py` (11 tests) checks 100 random (day, until) pairs for
  bars and levels never returning anything past `until`, checks every returned level's
  `available_at_h` against `nylab.days.COLUMN_DOCS`, and cross-checks H1 resampling against a
  manual pandas resample. `tests/test_replay_server_integration.py` (3 tests) actually launches
  the real HTTP server as a subprocess and hits every route, including the static files.
- `pytest -q`: **25 passed** (11 Phase 0/1 + 11 replay-logic + 3 server-integration).

**What's explicitly NOT done yet (flagged in docs/ROADMAP.md, not silently skipped):**
- Session **boxes** (shaded rectangles) — used small text markers instead; `lightweight-charts`
  v4's free tier makes true shaded boxes more work than the markers, and markers convey the same
  information (where each session starts). Can upgrade later if Akash wants the visual boxes.
- **PWH/PWL** (previous week high/low) overlay — not built because `nylab/days.py` doesn't compute
  a weekly high/low column *at all* yet (FEATURES_SPEC.md §1 lists it as a TODO, not something v0
  had). Needs a small days.py addition before the overlay can exist.
- **08:30 open** line — the data exists (`o0830` is in `COLUMN_DOCS`), just wasn't added to the
  overlay list. Trivial to add.
- Order types beyond "market, fills at last close": no limit/stop pending orders, no drag-to-move
  SL/TP, no move-to-breakeven button, no partial close (25/50/75%), no Challenge mode. REPLAY_TRAINER.md
  S9 acceptance item 4 ("a full mock trade — limit entry, SL, TP, BE move, partial — produces the
  same R as the engine") is therefore only **partially** verified: the R-math itself is proven
  identical to the engine's formula (`test_full_mock_trade_matches_engine_r_math`), but the
  limit/BE/partial *mechanics* aren't implemented, so that specific acceptance item isn't fully met.
- Drawing tools (horizontal line, rectangle, Fibonacci/OTE) — REPLAY_TRAINER.md §6, not started.
- Stats tab (replay trades → expectancy/win-rate by setup/session) — REPLAY_TRAINER.md §8, not started.

None of the above block using the trainer for its main job (picking a day, watching it unfold bar
by bar, taking a practice trade, seeing the R and the account impact) — they're refinements listed
in Phase 6 of the roadmap anyway (filters v2, BE/partial, challenge mode, review-mode overlays,
drawing tools, stats tab). Flagging them now rather than checking boxes that aren't fully true.

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

Two paths, Akash's call:
(a) Close the Phase 2 gaps above (PWH/PWL column + overlay, 08:30 line, session boxes, limit/BE/
    partial trading, challenge mode, drawing tools, stats tab) before moving on, or
(b) Move to Phase 3 (hypothesis YAML + DSL + ledger + Bonferroni/BH) now and come back to the
    replay trainer's remaining polish in Phase 6 as originally scheduled, since the roadmap already
    plans a "Replay trainer v2" phase for exactly this list.
Recommended: (b) — the roadmap already schedules this cleanup as Phase 6, and Phase 3 (the honest-
stats ledger) is more valuable to build next than trainer polish.
