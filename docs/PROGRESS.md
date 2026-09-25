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

### Phase 5 (in progress) — All sessions, session character (tickets 5.1/5.2 done; 5.3-5.6 not started)

**What's built:** `nylab/sessions.py` -- the SESSION table (SESSIONS_AND_CONTEXT.md §2) for all
11 session windows except `cbdr`, plus §3's character labels (with continuous scores -- range_rel/
er/close_loc are real columns, not just intermediate label inputs) and day types
(trend_day/reversal_day/range_day/inside_day/outside_day/normal_day). Wired into `nylab run`
right after the calendar attach step: `d` grows from 114 to 421 columns, and the run's existing
hypothesis/report result is unchanged (confirmed on Akash's real 5-year data -- purely additive,
same as Phase 4's calendar attach). `python -m nylab run` still finishes in ~30s (AT-04 budget: 90s).

**Scope cuts, disclosed (not silent):**
- `cbdr` excluded from the SESSION table entirely. Its high/low/range already exist correctly as
  DAY columns (computed from absolute timestamps because it spans the td boundary --
  `window()`'s h-relative logic can't handle that), and it isn't one of §5.1's default
  transition-matrix pairs either.
- `raids`/`first_raid`: raids against the immediately-preceding chain session's high/low plus
  pdh/pdl/pwh/pwl (6 candidate levels) -- NOT `o_mid`, which FEATURES_SPEC §3 itself calls "a
  reference, not liquidity". Stored as a count (`raids_count`) plus the earliest one's identity/
  type/time, not the full structured list §2 sketches.
- Day type's 5th label, `normal_day`, is this module's own catch-all -- §2 names
  trend_day/reversal_day/range_day/inside_day/outside_day but nothing for "none of those", and
  every trading day needs a label.

**A real naming collision, found by running against Akash's actual data, not spotted on paper
first:** v0's existing `nyam_*` day columns (nyam_open/high/low/close/hi_t/lo_t, available_at_h=10)
are actually the 07:00-10:00 NY AM KILLZONE window -- what SESSIONS_AND_CONTEXT §1 now calls
`nyam_kz`. The NEW `nyam` id in that same table is the BROADER 07:00-12:00 NY AM session, a
genuinely different window with no legacy equivalent. Emitting its raw price columns under the
natural prefix `nyam_` would have silently shadowed the existing (differently-windowed) legacy
columns -- a real look-ahead-adjacent correctness bug, not a cosmetic one, since a hypothesis
writer typing `nyam.high` expecting the 12:00 close would silently get the 10:00 one instead.
Fixed two ways: (1) the wide day-table join renames the full `nyam` session's columns to
`nyam_full_*` (`nyam_full.character`, never `nyam.character` -- writing `nyam.character` now
fails LOUDLY with "unknown column", since no such column exists under that name, rather than
silently resolving to the wrong window); (2) `attach_session_features()` also detects ANY other
such collision generically at join time (not just the ones spotted by inspection) and keeps the
pre-existing column's meaning, logging what it skipped. One more turned up this way: legacy
`lon_dir` (plain `sign(close-open)`, no dead-band) collides with this module's new `dir` (same
idea, SESSIONS_AND_CONTEXT §2's dead-banded version) -- `lon.dir` in a hypothesis therefore
resolves to the legacy, non-dead-banded value; every other session id's `dir` is the new one.
Also fixed along the way: SESSIONS_AND_CONTEXT §5.2's own example hypothesis writes
`day.has_fomc`, but Phase 4's calendar flags were joined onto `d` bare (`has_fomc`, not
`day_has_fomc`) before any dotted "day.x" convention existed -- `nylab/days.py::
attach_calendar_features` now also joins `day_`-prefixed ALIASES for those six flags (same
Series, original bare names untouched) so the dotted syntax resolves.

**Tests:** `tests/test_sessions.py` (16 tests) -- SESSION-table shape/columns, coverage of every
non-cbdr id, both collision fixes (asserted directly against the real legacy values, not just
"doesn't crash"), day-type coverage, `column_docs()`'s `available_at_h` values against §1's own
"Ends" column (including proving `nyam.character` is correctly ABSENT so it fails loudly),
character-label rule ordering (parametrized over all 6 first-match-wins cases plus the NaN-
propagation case), the sweep/break/no-raid classifier on hand-built bar arrays, and the
efficiency-ratio formula on a straight line vs. a chopping series. `pytest -q`: **103 passed**
(87 Phase 0-4 + 16 new). Also re-ran the full 5-year real-data pipeline end-to-end
(`python -m nylab run ... --tz auto`) after every change -- same hypothesis/report result
throughout, confirming Phase 5.1/5.2 didn't disturb anything upstream.

**Not started yet (at that point):** 5.3 (transition matrices, news-conditioned matrices,
Silver Bullet window stats), 5.4 (relational hypotheses + matrix-family multiple-testing
counting), 5.5 (report sections), 5.6 (label validation with Akash on 30 replay days -- needs
his own participation, can't be done without him).

### Phase 5.3 (done) — descriptive cross-session layer

**What's built:** `nylab/cross_session.py` (SESSIONS_AND_CONTEXT.md S5.1) -- generic, reusable
machinery, not a fixed report:
- `character_transition_matrix(a, b)` / a `dir` version: P(B's label | A's label), with count,
  conditional %, the unconditional % of that B label (for comparison), Wilson 95% CI, and a
  `greyed` flag when the A-row has fewer than 25 days (S5.1's own cutoff) -- generic over ANY
  categorical pair, so it also drives `run_default_character_matrices()`/`run_default_dir_
  matrices()` across S5.1's default pairs (asia->lon, lon->nyam, nyam->nypm, lon->nypm) plus the
  combined (asia+lon)->nyam pair via a new `combined_label()` helper.
- `takes_rate()` / `run_default_takes()`: "does session B's window trade beyond session A's
  high/low", reusing `nylab.days.first_cross` (the exact same conservative rule the DAY table's
  existing `ny_takes_lon_high`-style columns use) generalized to any A/B pair instead of the
  handful hardcoded since Phase 1.
- `news_conditioned_rate()` (rows: none/USD/EUR/both had high-impact news) and
  `news_severity_rate()` (rows: no event / event, low |z| / event, high |z|) -- both take any
  boolean outcome Series, so they cover S5.1's "red EUR news -> NY AM reversal rate" example
  directly.
- `continuation_rate()` ("NY AM trend -> NY PM continues vs reverses", optionally conditioned)
  and `directional_take_rate()` ("Asia quiet + London trend -> NY AM takes London's extreme in
  the SAME direction") -- the other two example rows S5.1 explicitly asked for.
- `silver_bullet_stats()`: per Silver Bullet window (lon_sb/nyam_sb/nypm_sb), FVG-formation
  rate, reversal-character rate, median range.
- Every function/result carries `DESCRIPTIVE_BANNER` in spirit (S5.1: looking is free, nothing
  here is significance-tested) -- rendering it into report.html is 5.5, not yet built.

**A disclosed simplification:** S6 item 5 asks how often price "reaches the nearest opposite
liquidity" inside a Silver Bullet window -- that phrase doesn't reduce to one of this module's
existing primitives without inventing a specific liquidity-selection rule the spec doesn't state,
so `silver_bullet_stats()` reports the session's own `reversal`-character rate as the closest
available proxy (a reversal, by construction, means price traded through one side and closed
back the other way) and says so in its docstring rather than silently standing in for the exact
phrase.

**An observation, not a bug, worth flagging before 5.6:** running the default character
matrices against Akash's real 5-year data shows the `trend` label firing VERY rarely for the
broader NY AM (`nyam`, i.e. `nyam_full`) window (2 out of ~1,300 days) and for Asia (9 days) --
`chop` and `reversal` dominate instead. The rule (`er >= 0.45` and closing near an extreme) is
exactly S3's stated default threshold; it just may be tuned for a narrower/shorter window than a
5-hour session. This is precisely what ticket 5.6's replay validation with Akash is for, so no
threshold was changed here -- flagging it now so it's not a surprise when we get to 5.6.

**Tests:** `tests/test_cross_session.py` (10 tests) -- matrix counts/greying/NaN-dropping/empty-
input, both news-bucket functions, continuation rate's flat-A exclusion and conditioning, the
directional-take-rate's direction matching, Silver Bullet stats' shape, and `takes_rate()`
against a real (small synthetic) bar series to exercise the actual `first_cross` machinery, not
just a mocked one. `pytest -q`: **113 passed** (103 existing + 10 new), no regressions.

### Phase 5.4 (done) — relational hypotheses with matrix-family counting

**What's built:** SESSIONS_AND_CONTEXT.md S5.2's rule -- "once you pick a cell because it
looked extreme, you must count every cell of that matrix as tested" -- as real machinery, not
just a comment:
- `nylab/hyp_loader.py`'s `Hypothesis` dataclass gained an optional `matrix_shape: (rows, cols)`
  field, parsed from a YAML `matrix_shape: [rows, cols]` key and validated (both positive ints)
  at load time, same as every other field.
- `nylab/ledger.py` gained a `matrix_cells` column (default 1 for an ordinary hypothesis) and
  `distinct_m()` now SUMS that weight over distinct (id, version) pairs instead of just
  counting pairs -- a hypothesis with `matrix_shape: [6, 6]` contributes 36 to `m`, not 1.
  `research/ledger.csv` predates this (Akash's own real ledger has 45 rows from Phases 3-4, all
  12-column, no matrix_cells) -- `append()` migrates it in place, exactly once, the first time
  a new row is appended (adds `matrix_cells=1` to every existing row, changing no other value),
  so his real ledger will pick this up automatically the next time he runs `nylab run` for real.
  `distinct_m()` also tolerates reading a not-yet-migrated file directly (defaults to weight 1).
- `nylab/hyp_engine.py` uses the same weighting when computing `m`/`bonferroni_alpha` and when
  writing each hypothesis's own `matrix_cells` back to its ledger row.
- **A fix this surfaced, not planned up front:** `lon.character`-style SESSION-table columns
  only existed in `nylab.days.COLUMN_DOCS` once `nylab.sessions.column_docs()` had been merged
  in, which previously only happened inside `nylab run`'s own `cmd_run()` -- too late for a
  hypothesis loaded in isolation (a test, `nylab hypothesis add`, anything that doesn't go
  through the full CLI). Moved the merge to `nylab/hyp_loader.py`'s own import time instead
  (no circular import: sessions.py imports FROM days.py, hyp_loader.py importing sessions.py is
  a one-way dependency) -- every path that touches a hypothesis file already imports hyp_loader
  first, so the registration is now unconditional rather than order-dependent.
- **New hypothesis:** `config/hypotheses/H016.yaml` -- SESSIONS_AND_CONTEXT S5.2's own worked
  example ("London chop -> NY AM KZ reversal"), promoted from the lon->nyam_kz CHARACTER
  transition matrix (6x6=36 cells). Confirmed on Akash's real data: `ledger_total_tests` (the
  report's name for `m`) goes from 15 to 51 (15 + 36) the moment H016 is loaded, and
  `bonferroni_alpha` moves from 0.05/15 to 0.05/51 accordingly -- exactly the stricter bar the
  spec intends. H016 itself did not reach `survives-oos` on the real data (p=0.123, well short).

**Test-suite ripple, expected and fixed, not a regression:** four Phase 1/3 tests hardcoded
"15 hypotheses" as a golden invariant (`test_load_all_loads_the_15_ported_hypotheses`,
`test_hypotheses_csv_matches_golden`, `test_summary_json_written`, and the three AT tests'
shared `m == 15` check). Updated each to expect 16 hypotheses / m=51, while keeping the actual
v0-parity assertions (the first 15 rows' numbers still matching v0's golden fixture exactly) --
adding a real 16th hypothesis is Phase 5.4 working as intended, not something to hide from the
golden tests. The AT-01/AT-02 fixtures also needed the session-table attach step added to their
own `_build_days()` helper (mirroring `cmd_run`'s real pipeline), since H016's condition needs
`lon_character` to actually exist in the day table being evaluated, not just be registered in
COLUMN_DOCS.

**Tests:** added `test_matrix_shape_*` (3, in `tests/test_hyp_loader.py`) and 4 ledger tests
(`tests/test_ledger.py`) for the weighting/migration/persistence behavior specifically.
`pytest -q`: **120 passed** (113 existing/updated + 7 new), full `nylab run` re-confirmed on
Akash's real 5-year data (~18-47s depending on machine load, still well under AT-04's 90s).

## Next up

Continuing **Phase 5**: 5.5 (report sections, SESSIONS §6) is next, then 5.6 (label validation
with Akash on 30 replay days -- needs his own participation).

The project has 11 phases total (0 through 10): 0 Reproduce v0 (done), 1 Package refactor (done),
2 Replay trainer MVP (done), 3 Ledger/hypothesis stats (done), 4 Economic calendar (done), 5 All
sessions + session character (in progress -- 5.1/5.2/5.3/5.4 done), 6 Replay trainer v2, 7 ICT
features & models, 8 Verification/robustness/prop simulation, 9 Daily automation, 10 Research
loop (ongoing).
