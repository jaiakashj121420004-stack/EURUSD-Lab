# PROGRESS.md — where the build stands

Read this first in any new session. Update it after every ticket. See CLAUDE.md and
docs/ROADMAP.md for the full plan (checkboxes there are kept current too).

## Status: Phase 4 (economic calendar) done and confirmed on Akash's real MT5 calendar export (34,075 events, 2021-09-26 -> 2026-09-25, 18,454 USD / 15,621 EUR). Ready for Phase 5.

Akash has not yet run the replay trainer himself (no MT5 export/import done yet either) -- his
call: keep building through the phases on the automated tests alone, and he'll sit down and look
at everything (replay trainer included) once more of the pipeline exists. So: I keep running and
rigorously honoring every test I write (he was explicit about this), and don't wait on his manual
review to keep moving. Nothing here has been eyeballed by him yet -- flagged wherever it matters.

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

### Phase 3 — Ledger, hypothesis YAML, honest stats: done

**What's new:**
- `nylab/hyp_dsl.py` -- the safe condition/outcome/baseline evaluator. Never calls `eval()`/
  `exec()`: parses with `ast.parse` (parsing alone runs nothing) then walks the tree by hand
  through a whitelist (comparisons, `and`/`or`/`not`, `+-*/`, and exactly 3 functions -- `abs`,
  `quantile`, `median`). Dotted convenience syntax (`lon.high`, `day.open`) is a text-level
  rewrite to the day table's own column names BEFORE parsing, so `a.__class__`-style attribute
  tricks never reach an actual `ast.Attribute` node -- they just become a nonsense flat name
  that fails as "unknown column" at evaluate time. 16 tests, including a battery of rejected
  strings (`__import__`, `os.system`, `lambda`, list comprehensions, `open(...)`, `eval(...)`).
- `config/hypotheses/H001.yaml`..`H015.yaml` -- v0's 15 hypotheses, ported. Verified their
  sample counts and hit rates match the v0 golden output exactly (n, hit, baseline, IS/OOS hit,
  OOS n all within 1e-9) -- only the significance/verdict layer around them is new.
- `nylab/hyp_loader.py` -- loads the YAML, validates every expression against the DSL's
  whitelist, and REFUSES to load a hypothesis whose `condition` uses a column not yet known by
  its `decision_time_h` (checked against `nylab.days.COLUMN_DOCS`, dotted syntax included). 8
  tests, including one confirming the dotted form is checked exactly like the flat form (so
  dotted syntax can't be used to sneak a too-late column past the loader).
- `nylab/ledger.py` -- the append-only `research/ledger.csv`, `m` (distinct id+version pairs
  ever logged -- re-running unchanged doesn't inflate it, bumping version does), Bonferroni
  alpha, and a from-scratch Benjamini-Hochberg step-up implementation (checked against a
  hand-computed textbook example). 8 tests.
- `nylab/hyp_engine.py` -- runs the loaded hypotheses against the day table, computing the same
  Wilson CI / z-test stats as before, now via Bonferroni AND BH (global + per-family), and
  assigning RESEARCH_PROTOCOL.md §9's actual verdict vocabulary (`noise`/`weak`/`candidate`/
  `survives-oos`/`not proven`) instead of v0's two-way `bonferroni_sig`/`oos_holds` flags.
- `python -m nylab hypothesis add H016 "..." --decision-time-h 9.5` scaffolds a new YAML with
  TODO placeholders that the loader will refuse until they're filled in with real expressions.
- `python -m nylab run` now runs entirely through this pipeline and appends to
  `research/ledger.csv` on every run (pass `--ledger-path` to point elsewhere, e.g. for tests).

**A methodology finding worth recording (this is exactly the kind of thing RESEARCH_PROTOCOL.md
exists to catch, so it's written up in full rather than quietly patched):** RESEARCH_PROTOCOL.md
§4 reads as "`survives-oos` needs Bonferroni-on-IS OR BH, plus an OOS result confirming it." I
implemented that literally, then ran AT-01 (docs/ROADMAP.md's own global test: on the clean/
no-edge fixture, zero hypotheses may reach `survives-oos`) against it -- and it failed. One of
the 15 old hypotheses (H013, about ADR usage) got flagged as a confirmed finding on data that
has NO real edge by construction. Cause: BH is deliberately lenient -- at its 10% false-discovery
rate setting across 15 tests, roughly 1-in-10 null hypotheses are EXPECTED to pass it by chance,
and this run's random seed happened to produce exactly one that also had its IS and OOS halves
agree by coincidence. That's not a bug in the arithmetic; it's BH doing exactly what a 10% FDR
setting promises. Brought this to Akash; his call (recommended, and what's now built): `survives-
oos` is reserved for the STRICT Bonferroni-on-IS route only. A BH-only pass, even with OOS
confirmation, is labeled `candidate` -- worth a second look, not a proven finding. AT-01 now
holds cleanly under this rule (`tests/test_hyp_engine_at.py`). AT-02 (the planted-edge fixture)
needed the 5-year fixture rather than 2-year: H005's real, deliberately-planted edge clears
Bonferroni on 5 years of data; on 2 years it doesn't have quite enough samples to, even though
its raw hit rate (0.73) already clears the 0.58 bar on its own. Both are now tested.

**Test count:** 66 passed (was 31 after Phase 2's gap-close; +16 DSL, +8 loader, +8 ledger, +3
AT-01/AT-02 acceptance).

**Not done, correctly out of scope for Phase 3:** walk-forward validation (Phase 7+), the
robustness battery (cost sensitivity, entry-delay, per-year, Monte Carlo -- RESEARCH_PROTOCOL
§5.4, applies to MODELS not hypotheses, Phase 7+), forward testing (§7, Phase 9+), kill criteria
enforcement (§8, needs a running forward test to kill). None of these apply yet -- there's no
model survives-oos to subject them to.

## Open questions for Akash (not blocking)

Same three as after Phase 1 (Maven program confirmation, broker tz convention, CLAUDE.md's stale
+10%/+8% text) — nothing new this phase.

### Phase 4 — Economic calendar: code done, tests pass, real-broker confirmation pending

**What was built:**
- `mql5/ExportCalendar.mq5` — read-only MQL5 script (Print()s progress + earliest-event-found;
  never touches trades). Chunks `CalendarValueHistory()` by year, writes `calendar_export.csv` with
  `time_server,currency,event_id,event_name,importance,actual,forecast,previous,revised_previous,
  unit,multiplier` (MetaQuotes' `LONG_MIN`-as-"not set" and the ×1e6 fixed-point encoding both
  handled). README.md's new "Phase 4" section is the exact compile-and-run walkthrough (MetaEditor
  F7, drag onto a live chart — calendar functions don't work in the Strategy Tester).
- `nylab/calendar_io.py` — `load()` auto-detects the MQL5-export schema vs. the 4.4 fallback schema
  (`datetime_ny,currency,event,impact,actual,forecast,previous`) by column names and dispatches.
  Server→NY conversion reuses `nylab.data.timezones.to_new_york()` with the SAME `--tz` mode
  `nylab run` used for the price bars — the whole point of SESSIONS_AND_CONTEXT §4 is that the
  calendar and the bars must agree on what "NY time" means. `save()`/`load_cache()` — parquet, same
  pattern as `nylab.cache`.
- `nylab/calendar_features.py` — `classify_family()` (regex families: NFP/CPI/FOMC/ECB/PMI/GDP/
  retail_sales/claims/speech, ordered so FOMC beats the generic "speech" catch-all).
  `compute_surprise()` adds `surprise` (actual-forecast) and `surprise_z` (surprise / stdev of that
  SAME event's PRIOR releases only, via `.shift(1).expanding()` — never sees its own or a future
  release; NaN until ≥8 prior releases exist, matching SESSIONS_AND_CONTEXT §4's rule literally).
  `build_day_flags()` produces, per trading day: `has_nfp/has_cpi/has_fomc/has_ecb` (any currency,
  scheduled that day), `red_usd_0830`/`red_eur_london` (high-importance USD at 08:00–09:00 NY / EUR
  inside the London KZ window), and per-session (asia/lon/preny/nyam/ny) `_usd_cnt`/`_usd_maxz`/
  `_eur_cnt`/`_eur_maxz` for high-importance events actually inside that window.
- **Look-ahead, wired the same way as every other DAY column:** `calendar_features.column_docs()`
  returns `available_at_h` for every column it can produce — the "is X scheduled today" flags get
  -7 (known at the trading day's open, same status as PDH/PDL, since MT5's calendar knows the
  schedule days ahead), the per-session count/max|z| columns get that session's own `_high` column's
  `available_at_h` (0/5/9.5/10/16) since they depend on that window's actual releases. This dict is
  `.update()`-ed into `nylab.days.COLUMN_DOCS` at import time, so `nylab.hyp_loader`'s Phase 3
  look-ahead check (the one that already rejects a hypothesis condition using a too-late column)
  covers calendar columns automatically — nothing new to maintain in two places.
- `nylab.days.attach_calendar_features(d, calendar, sessions_cfg)` — one call that joins all of the
  above onto the DAY table. Wired into `nylab run` as an **additive, optional** step: if
  `data/calendar.parquet` exists (default path, override with `--calendar`), it's attached and the
  run prints the USD/EUR row counts; if not, `nylab run` prints a one-line notice and continues
  exactly as before — Phase 3's hypotheses/report/tests are unaffected either way.
- `python -m nylab calendar-import <csv> [--tz ny+7] [--out data/calendar.parquet]` — new CLI
  subcommand (was a "not built yet" stub), prints the imported date range and per-currency counts.

**Accept, split into what's provable now vs. what needs Akash's own data:**
- **AT-04 (code-provable now):** `test_at04_nfp_and_fomc_land_at_expected_ny_hour` builds a
  synthetic export the same way `ExportCalendar.mq5` writes a real one (server-time strings, the
  same CSV columns) with an NFP release in January and one in July, and a FOMC release in each —
  asserts both NFP rows land at 08:30 NY and both FOMC rows at 14:00 NY, i.e. exactly the Roadmap's
  Accept line, under the "ny+7" broker-clock convention (a CONSTANT offset, since a "NY close"
  broker's clock tracks US DST right along with New York — that constancy is the thing being
  tested, not a loophole around it; `nylab.data.timezones.sanity_check`, already proven in Phase 0/1
  against the real price bars, is the independent check that "ny+7" is the RIGHT mode for Akash's
  broker in the first place).
- **21 tests in `tests/test_calendar.py`** (schema auto-detection both ways, rejection of an
  unrecognized schema, all 9 event-family regexes incl. the ECB-before-"speech" ordering, the
  surprise-z min-prior-count and no-future-leak guarantee, day-flag scheduling + per-session window
  boundaries including the exclusive-upper-bound edge case, and the COLUMN_DOCS registration).
  `pytest -q`: **87 passed** (66 Phase 0–3 + 21 new).
- **Confirmed on Akash's real data (2026-09-25):** compiled and ran `ExportCalendar.mq5` on his
  MetaQuotes-Demo account (34,475 rows written, earliest event 2021-09-26 -- matches his 5-year
  price history almost exactly). Hit one real bug doing this: MQL5's `FileOpen(..., FILE_ANSI, ...)`
  writes the CSV in Windows' ANSI codepage, not UTF-8, and an event name with a non-ASCII
  character crashed `pd.read_csv`'s default utf-8 read. Fixed in `nylab/calendar_io.py` with a
  utf-8 -> cp1252 -> latin-1 fallback chain (latin-1 never raises, so import can't hard-crash on
  an encoding it doesn't recognize). After the fix: `nylab calendar-import` loaded 34,075 events
  (18,454 USD / 15,621 EUR -- the small drop from 34,475 is dedup + blank-row filtering doing its
  job), and `nylab run` printed "attached news features from data/calendar.parquet" and produced
  the identical hypothesis/report result as before -- confirming the attach step is genuinely
  additive, not just additive in theory.

**Design choices worth flagging:**
- `surprise_z = surprise / stdev(prior surprises)` is NOT demeaned (no `- mean` term) — that's
  SESSIONS_AND_CONTEXT §4's formula exactly as written, not an oversight. It means a currency/event
  whose surprises are typically small-but-nonzero can still show a "large" z on an unremarkable
  release; that's a property of the spec's chosen formula, not a bug, and it's called out here in
  case Akash wants demeaning added later (a 1-line change: `(surprise - prior_mean) / prior_std`).
- High-importance is `importance >= 3` (MQL5's own 0–3 scale, 3=high) for every "red"/session-count
  column. The day-level `has_nfp`/`has_cpi`/`has_fomc`/`has_ecb` flags do NOT filter by importance —
  they fire on ANY release matching that family's name regex, on the theory that "is a rate decision
  happening today" is binary regardless of how MetaQuotes ranked its importance that particular time.

## Next up

Moving to **Phase 5 — all sessions, session character, cross-session analysis** (SESSIONS_AND_CONTEXT.md
full session table + the relational/cross-session layer). This is a pure-Python phase -- no
Windows/MT5 steps expected until we're back to something export- or replay-related.

The project has 11 phases total (0 through 10): 0 Reproduce v0 (done), 1 Package refactor (done),
2 Replay trainer MVP (done), 3 Ledger/hypothesis stats (done), 4 Economic calendar (done), 5 All
sessions + session character (next), 6 Replay trainer v2, 7 ICT features & models, 8 Verification/
robustness/prop simulation, 9 Daily automation, 10 Research loop (ongoing).
