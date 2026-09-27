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

## Phase 5.5 (done): report sections (SESSIONS_AND_CONTEXT.md §6)

New module `nylab/report/sessions_section.py`, wired into `nylab/report/html.py`'s `build()`
(new optional `extra_section=""` parameter, appended just before the "Files" footer -- the
old 5-argument-plus-figs call signature is unchanged for anyone calling it without the new
content) and `nylab/__main__.py`'s `cmd_run()` (built right after `charts_mod.build()`, using
the `session_tables`/`sessions_cfg`/`cal`/`H` already in scope there). Renders §6's six items
as report sections 5-10 (sections 0-4 are the existing Phase 0-4 material, unchanged):

- **5 · Session overview** -- median range/mean ER/character distribution for all 11 SESSION
  ids, plus a session x year median-range table. *Disclosed simplification:* the by-year
  breakdown is median range only, not a full character-distribution-by-year table -- §6 doesn't
  specify a shape for this, and slicing the rarer characters (Phase 5.3 already flagged `trend`
  firing on ~9/1300 asia-days) further by year would mostly be empty cells.
- **6 · Volatility heatmap** -- a new median-range-by-(NY hour x weekday) heatmap
  (`nylab.report.sessions_section.build_figs()`, composed into `figs` alongside
  `nylab.report.charts.build()`'s existing three charts), reusing the same whole-hour bucketing
  convention `charts.py` already uses.
- **7 · Cross-session transition matrices** -- renders every `nylab.cross_session`
  character/dir default pair plus the combined-label pair and the default takes-rates, with
  `DESCRIPTIVE_BANNER` shown once at the top of the section and per-row greying (n<25) as muted
  table rows, matching S5.1's own "look freely, but grey out and don't treat as a finding"
  framing.
- **8 · News impact** -- news-conditioned and news-severity reversal rates for the NY AM
  killzone, plus a news-day-vs-not comparison table. *Disclosed simplifications:* reuses
  `nyam_kz`'s own `news_high_usd`/`news_high_eur`/`news_surprise_z` columns as the single
  family-agnostic proxy for "the morning's news surprise" rather than a new bar-level scan, and
  reuses the existing `hi_t`/`lo_t` session columns split by news-day-vs-not as the stand-in for
  "time-to-high/low after 08:30/14:00 releases" rather than new release-anchored bar scanning.
  Both are named explicitly in the rendered HTML text itself, not left implicit. Skipped
  entirely (with a plain-English note) when no calendar cache is attached.
- **9 · Silver Bullet windows** -- `nylab.cross_session.silver_bullet_stats()` as a table for
  the 3 SB windows (FVG rate, reversal-character rate as the closest available proxy for
  "reaches the nearest opposite liquidity", median range).
- **10 · Relational (matrix-family) hypotheses** -- filters `H` to rows with a non-null
  `family` (currently just H016) and shows `matrix_cells` alongside the usual hit/baseline/
  Bonferroni/OOS columns, so a 36-cell promotion is visibly distinguished from an ordinary
  1-cell hypothesis rather than only counted invisibly into `m`. Required a small prerequisite
  fix in `nylab/hyp_engine.py`: the reported hypothesis rows previously dropped `family` and
  `matrix_cells` (`del r["family"], r["min_n"]`) -- changed to keep both and drop only
  `min_n`, so this table has something to read.

Confirmed on Akash's real 5-year data: all 6 new sections render with real numbers (e.g. H016
shows `family=cross_session_lon_nyamkz_character`, `matrix_cells=36`, `n=448`, hit 28.2%,
baseline 32.1%, not Bonferroni-significant, matching Phase 5.4's own numbers), the news section
renders correctly with the real calendar cache attached, and `bonferroni_alpha`/`m` are
unaffected (still 51/0.05÷51) since this phase only renders existing ledger rows, adds no new
hypotheses.

**Tests:** new `tests/test_sessions_section.py` (4 tests) -- runs a short real pipeline
(loader-equivalent synthetic bars -> `days.build_days` -> `sessions.build_all_sessions`/
`attach_session_features` -> `hyp_loader.load_all()`/`hyp_engine.evaluate()`) so the section
builder gets genuine SESSION tables and an `H` frame with a real matrix-family row, then checks:
the heatmap figure key appears when matplotlib is available, every one of the 6 new `<h2>`
section headers is present and H016's `matrix_cells=36` shows up in section 10, the news section
is skipped gracefully (with its own explanatory text) when no calendar is attached, and every
`<table>`/`<tr>` tag is properly closed. `pytest -q`: **124 passed** (120 existing + 4 new).

## Phase 5.6 (tool built -- awaiting Akash's own review): label validation

New module `nylab/label_validate.py` plus two CLI commands (`python -m nylab label-validate
build` / `... score <answers.json> --meta <meta.json>`), reusing the same parquet cache the
Phase 2 replay trainer reads (`data/cache/`) rather than re-running the pipeline.

**Sampling (`sample_days()`):** ROADMAP 5.6 says "30 random days", but a pure uniform sample
risks missing a rare label entirely -- PROGRESS.md's Phase 5.3 section already flagged
`nyam_full`'s `trend` firing on only 2/~1300 days. So sampling is stratified-then-random: first
guarantee at least one occurrence of every label that actually occurs, for each of 5 validated
sessions (asia/lon/nyam_kz/nyam_full/nypm -- a disclosed scope cut to the sessions existing
hypotheses/the example model actually condition on, not all 11 SESSION_IDS), then fill up to
`n=30` with uniform-random days. The stratified floor is never trimmed back down even if it
alone would exceed 30 (trimming it could silently drop the exact rare day it exists to protect)
-- on Akash's real data this floor fits inside 30 days with `MIN_PER_LABEL=1`, so the sample is
exactly 30, and every one of the 5 sessions' `trend` label is represented at least once.

**The review page:** `label-validate build` writes one self-contained HTML file (~30 days,
~400KB, no server/internet needed) -- each day shows a canvas candlestick chart of the full
trading day with the 5 validated sessions shaded and their computed `character` label printed
directly on the chart, plus a table with Agree/Disagree buttons and an optional note field for
every session's label and the day's `day_type`. A "Download my answers" button exports a JSON
file Akash sends back.

**Scoring (`label-validate score`):** pools agreement by the LABEL VALUE (e.g. every `reversal`
call across all 5 sessions counted together), not per-session -- SESSIONS_AND_CONTEXT S3 means
`character` to be the same qualitative idea regardless of which session produced it. `day_type`
is scored as its own family (S2, not S3). Any label under 80% agreement is flagged in the CLI
output, per ROADMAP 5.6's accept bar.

**Not yet done:** Akash hasn't reviewed the sample yet -- this ticket stays unchecked in
ROADMAP.md until he has, agreement is tabulated for real, and (per RESEARCH_PROTOCOL.md's
"session-character thresholds are frozen once validated") any threshold adjustment below 80% is
made together with him, not unilaterally.

**Tests:** `tests/test_label_validate.py` (7 tests) -- the stratified floor survives a single
planted rare-label day even when the random fill alone wouldn't have found it; the result is
deterministic for a fixed seed and has no duplicates; payload building filters bars to the
correct window and covers all 5 validated sessions; the rendered HTML has no leftover template
placeholders and embeds the right day count; and `score()`'s agreement-rate math and 80%-bar
flag, including that unanswered/missing-label rows are correctly excluded rather than counted
as disagreements. `pytest -q`: **131 passed** (124 existing + 7 new).

## Phase 5.6 (in progress): Akash's first 30-day review, scored

Akash reviewed `sample_42.html` (30 days x 5 sessions + day_type = 180 calls) and returned
`label_validation_answers.json`. `label-validate score` result:

| family | label | n | agree | passes 80%? |
|---|---|---|---|---|
| character | chop | 64 | 78.1% | **no** |
| character | normal | 21 | 61.9% | **no** |
| character | quiet | 20 | 95.0% | yes |
| character | range_both | 11 | 90.9% | yes |
| character | reversal | 26 | 80.8% | yes |
| character | trend | 8 | 100% | yes |
| day_type | inside_day | 2 | 100% | yes |
| day_type | normal_day | 8 | 62.5% | **no** |
| day_type | outside_day | 3 | 100% | yes |
| day_type | reversal_day | 6 | 100% | yes |
| day_type | trend_day | 11 | 90.9% | yes |

Rather than taking the raw agreement numbers at face value, every one of his 33 disagreements
was individually checked against that session's actual `range_rel`/`er`/`close_loc`/
`took_prev_high`/`took_prev_low`/`both_sides` values (not just the label) -- Akash asked
specifically for this rather than the tool being "ok with" his answers uncritically. Two real
findings came out of that, plus one naming issue that isn't a labeling bug at all:

1. **A genuine, recurring threshold gap (the real reason chop/normal/normal_day are under 80%):**
   at least 7 of the disagreements are the SAME shape -- a session closed at an extreme
   (`close_loc` <=0.25 or >=0.75) with a clearly outsized range (`range_rel` often 1.2-2.3x
   normal), but `er` landed in the 0.18-0.35 band, short of `trend`'s `er>=0.45` requirement --
   so it fell through to `chop` (`er<0.25`) or the `normal` catch-all instead of `trend`, even
   though the close location and range alone read as an obvious trend to a human. Examples,
   with the actual numbers: 2022-10-17 nyam_full (er=0.35, close_loc=0.95, range_rel=1.50, his
   note "trending bullish, moved 122 pips"); 2023-05-11 lon (er=0.35, close_loc=0.17,
   range_rel=1.88, "trending bearish"); 2024-06-14 lon (er=0.34, close_loc=0.05,
   range_rel=2.28(!), "trend day, full bearish"); 2025-12-29 asia (er=0.28, close_loc=0.02,
   range_rel=1.70, "trend"); 2026-05-14 nyam_kz/nyam_full (er=0.22/0.24, close_loc=0.19/0.18,
   "TRENDING" x2); 2023-06-01 nyam_kz (er=0.18, close_loc=0.94, range_rel=1.48). This is a real
   candidate for adjusting `_label_character`'s `trend` rule (`nylab/sessions.py`), not noise --
   flagged for a joint decision with Akash on the specific new threshold/rule shape (candidates:
   lower the `er>=0.45` cutoff, or add an alternate `range_rel`-driven path for trend so an
   unusually large, decisively-closed session qualifies even at moderate efficiency) before
   changing anything and re-validating.
2. **A vocabulary gap, not a math gap:** several "disagreements" turned out to describe exactly
   what `reversal` already means -- e.g. 2022-04-11 lon and 2024-05-01 lon, both correctly
   flagged `reversal` by the rule (swept both the prior extreme, closed back past 0.65/0.35),
   where Akash's own note called it "manipulation/Judas swing/turtle soup", which IS the same
   pattern in ICT terminology. No code change needed here -- worth adding that vocabulary as a
   parenthetical in the glossary so it reads as agreement rather than disagreement next round.
3. **A couple of true near-misses right at a threshold edge** (e.g. 2024-02-15 nyam_full,
   close_loc=0.48 vs reversal's 0.35 cutoff, his note "almost a reversal at the top") -- not
   wrong, just close enough to the boundary that a human and the rule can reasonably differ;
   noted but not treated as evidence for a threshold change on their own.
4. A few disagreements (2024-06-26's four sessions, 2025-01-23/2025-09-17 nyam_full/nyam_kz)
   came back with no note, so the underlying numbers were checked but the specific reasoning is
   unknown -- mostly consistent with their labels on the numbers alone (e.g. very low `er`
   really does mean chop even on a big-range day), flagged to ask Akash directly rather than
   guessed at.

**Also raised by Akash, a session-taxonomy question, not a labeling one:** he found `nyam_kz`
(07:00-10:00, the killzone) and `nyam`/`nyam_full` (07:00-12:00, the broader morning) confusing
side by side, since they mostly describe the same price action for the first three hours, and
suggested validating `nyam_kz` (7-10) plus the Silver Bullet window (10-11) instead. That's a
reasonable simplification for THIS review page specifically -- `nyam_sb` (10:00-11:00) isn't
currently in `SESSIONS_TO_VALIDATE` at all, so swapping it in for the broader `nyam` would cover
new ground rather than duplicate what `nyam_kz` already checks, at the cost of leaving 11:00-
12:00 unreviewed here (a defensible small gap: that hour isn't a Silver Bullet window and has no
existing hypothesis conditioning on it either). The underlying `nyam`/`nyam_full` SESSION table
column stays in the codebase regardless -- it's one of `nylab.cross_session`'s
`DEFAULT_PAIRS` (`lon->nyam`, `nyam->nypm`) and feeds the report's section 7 -- so this is a
review-page display choice, not a data-model change. Proposed to Akash, not yet applied.

**Decided (2026-09-25) and now implemented:**

1. **Trend rule v2** (`nylab/sessions.py::_label_character`): Akash chose the "separate path"
   option over simply lowering the `er>=0.45` cutoff. Added `trend_range = (range_rel>=1.4) &
   (close_loc<=0.20 or >=0.80)`, OR'd with the original `trend_er` path. Thresholds were set from
   his own flagged examples, not picked blind: lowest observed `range_rel` among his 6 flagged
   trend-shaped disagreements was 1.48 (used 1.4, a little headroom), loosest observed
   `close_loc` was 0.17/0.94 (used 0.20/0.80, a bit tighter than the 0.25/0.75 the original path
   uses, since "strongly extreme" was his own wording and this path has no `er` gate to balance
   it). Verified against the real data after rebuilding the cache (`nylab run ...` -- the day
   cache holds pre-computed labels and doesn't pick up a code change until re-run): 5 of his 6
   flagged examples now correctly read `trend` (2024-06-14 lon, 2023-05-11 lon, 2025-12-29 asia,
   2022-10-17 nyam_full, 2023-06-01 nyam_kz). The 6th (2026-05-14) still doesn't -- checked its
   actual numbers and its `range_rel` is only 0.94-1.26, genuinely not an unusually wide session
   by this measure, so it's a legitimate near-miss rather than a rule failure. Added two guard
   cases to `tests/test_sessions.py` confirming the new path requires BOTH conditions together
   (large range alone, or extreme close alone, must NOT trigger `trend`) so it doesn't over-fire.
2. **Session-set swap** (`nylab/label_validate.py::SESSIONS_TO_VALIDATE`): dropped the broad
   `nyam` (7:00-10:00... actually 7-12) session, keeping `nyam_kz` (7-10) and adding `nyam_sb`
   (10-11, Silver Bullet) as its own row -- both already existed as full `SESSION_IDS`, so this
   was a one-line swap, no new session-window math needed.

Full test suite (131 tests) passes after both changes. Cache rebuilt from the raw CSV via
`nylab run` (required -- the parquet cache holds pre-computed character labels from the old
rule and silently going stale is a real trap here) and a fresh 30-day review sample regenerated:
`research/label_validation/sample_42.html` / `sample_42_meta.json` now reflect the new
`asia / lon / nyam_kz / nyam_sb / nypm` session set and the new trend rule. **Not yet done:**
Akash's second review pass over this fresh sample -- needed before 5.6's checkbox flips (ticket's
own accept criteria: >=80% agreement).

**`lon_ny_gap` added (2026-09-25):** Akash picked option 1 (a proper named session, full
first-class treatment) over the lighter descriptive-only alternative for his "observe the time
in between sessions, especially London to NY" request. Added as a genuinely new session id --
window 5.0-7.0 (the untracked stretch between `lon`'s 05:00 close and `nyam_kz`'s 07:00 start) --
wired in everywhere the other 11 session ids are:
- `config/windows.yaml` (`lon_ny_gap: [5, 7]`) and `docs/SESSIONS_AND_CONTEXT.md`'s S1 table.
- `nylab/sessions.py`'s `SESSION_IDS` (now 12) and `_PREV_IN_CHAIN` (predecessor = `lon`, same as
  `nyam`/`nyam_kz`/`nyam_sb`/`lon_close` already use). Deliberately NOT inserted into the
  `asia->lon->nyam->lunch->nypm` chain itself -- `nyam`'s own predecessor stays `lon`, unchanged,
  so this addition can't silently redefine what an already-frozen raid feature means.
- `nylab/cross_session.py`'s `DEFAULT_PAIRS` -- added `(lon, lon_ny_gap)` and
  `(lon_ny_gap, nyam_kz)` so the character/direction transition matrices actually cover the
  London-to-NY handoff, which was the point of the request.
- `nylab/label_validate.py`'s `SESSIONS_TO_VALIDATE` -- added, so Akash can review its character
  calls too.
- `nylab/report/sessions_section.py` needed no changes -- section 5's table and the heatmap
  already iterate `SESSION_IDS` generically.
No new thresholds or rule logic here, just a new window reusing the exact same character/day-type
machinery every other session already goes through -- so no separate "which numbers" decision was
needed the way the trend-rule change was. Verified against real data after rebuilding the cache:
1295 days, `lon_ny_gap_character` distribution is sensible (chop 49%, normal 16%, reversal 16%,
trend 12%, quiet 7% -- not degenerate), median range ~18 pips. Full test suite (135 tests) passes.
Fresh review sample regenerated (now 34 days -- the stratified floor grew by one to cover
`lon_ny_gap`'s own rare labels) with all 6 sessions: `asia / lon / lon_ny_gap / nyam_kz /
nyam_sb / nypm`.

## 2026-09-26 — Jev (TypeSafe AI) assessment + review findings (docs only, no code changed)

Akash asked whether a Claude + Jev agent would be the strongest combination. Full answer:
docs/JEV_INTEGRATION.md. Short: Jev can be integrated but adds ~nothing until the lab has an edge;
one cheap pre-registered experiment (J1) and an optional replay "discipline coach" role are specified.
Rule/doc changes made (each cross-checked against existing rules): CLAUDE.md rule 10 + Maven numbers
now sourced from prop.yaml; RESEARCH_PROTOCOL §3 prior-only thresholds + direction check, new §11;
ROADMAP out-of-scope wording + Phase 10 question 7. Found while reviewing (need Akash's OK before
code changes, since fixes bump m):
- H013/H014 are significant in the OPPOSITE direction to their titles (volatility clustering), and
  their `quantile()`/`median()` thresholds use the full 5-year sample incl. OOS -> re-issue as v1.1
  with a prior-only DSL threshold and correct titles; make verdicts direction-aware.
- `london_sweep_reversal` v1.0 OOS CI [-0.42, -0.04] (n=183) is wholly negative but labelled
  "not proven" by `__main__.py` -> needs a "negative edge" verdict word (Akash to choose).

## 2026-09-26 (second pass) — independent audit of the Phase 0–5 build, verified on real data

Asked by Akash to check the work so far with quality/realism/fail-proofing in mind. Everything below
was re-run, not read off the reports.

**Reproducibility: good.** Re-running `nylab run` on his 5-yr CSV in a fresh sandbox reproduced
`reports/20260925-1914` exactly (max difference 1e-16). The DSL safety, ledger, no-leak replay
tests and code structure are solid work.

**Showstopper, now fixed:** his `.venv` has pandas 3.0.6. On it `nylab run` crashed on real data
(`idxmax ... all NA values`) and 9 tests failed; they only passed in the sandbox on pandas 2.3.
So the pipeline had never run successfully on his own laptop. Fixed two spots (see ROADMAP 5.8),
verified 135/135 on both pandas 2.3.3 and 3.0.6 and a byte-identical real-data report on both.
`requirements.txt` now caps versions; `run_tests.bat` added; CLAUDE.md §5a now requires his-machine
test passes before a phase is "done".

**Both "significant" hypotheses were artifacts (checked twice: numbers, then code):**
- H014 (quiet Asia → NY range): the 20th-percentile cut-off was computed over all 5 years incl. OOS.
  It flagged 47% of 2024 days and 3% of 2022 days, so it was picking calm years. With a prior-60-day
  cut-off: IS lift +2 to +5 pp, p 0.3–0.6 → noise.
- H013 (ADR used >80% by 09:30 → NY range): the outcome `ny_range` spans 07:00–16:00, overlapping
  the 07:00–09:30 part of the condition. With the outcome measured 09:30–16:00 only: IS +6 pp
  (p 0.06), OOS +2 pp (p 0.67), median 43 vs 41 pips → noise.
- What IS real (descriptive, not an entry signal): plain volatility persistence. If yesterday's
  09:30–16:00 range was above its prior-60 median, today's is above too 55% vs 39% (IS, z=4.8) and
  51% vs 40% (OOS, z=2.2). Useful for sizing/targets and as a counted context filter in Phase 7.

**Other engine issues (fix in ROADMAP 5.7):** p-values use IS+OOS combined (should be IS only);
one-sample test vs a baseline that contains the condition days (use condition vs complement);
`wilson_ci` is really the Wald formula; the 5-td embargo in RESEARCH_PROTOCOL §1 isn't implemented;
H015 is concurrent (decision 16:00 = outcome time), so descriptive, not predictive; the example model
(OOS CI [−0.42, −0.04], n=183) is labelled "not proven" though it is significantly negative.

**Realism notes for later (not blocking):** bars come from MetaQuotes-Demo, where `spread_pts` is 0 on
52% of bars, so the 1.0-pip cost floor does all the work. Before Phase 8's pass simulator, get
Maven's real EURUSD spread + commission (MT5 Specification window on his Maven login, or a week of
Maven bars with spread), and add a news-bar cost multiplier around 08:30/10:00/14:00 releases.

**`nyam_sb` widened to 10:00-12:00 (2026-09-26):** after seeing the fresh 6-session review
page, Akash noticed 11:00-12:00 looked uncovered on it -- not actually true in the underlying
model (that hour was always inside the broad `nyam` session, plus `lon_close`), but true on the
review page specifically, since `nyam` isn't shown there (dropped in the nyam_kz/nyam_sb swap).
Rather than adding a third small session to patch the display, he chose to just widen `nyam_sb`
itself from 10-11 to 10-12 in `config/windows.yaml` -- one-line config change, no code touched
since every consumer (`sessions.py`, `cross_session.py`, `label_validate.py`) reads the window
bounds from `cfg.sessions()` generically. Flagged for him (not silently absorbed): this makes
`nyam_sb` a 2-hour window, no longer the strict 1-hour ICT "Silver Bullet" concept -- more
accurately "NY AM killzone's second half" now, Silver Bullet included. Documented in
`docs/SESSIONS_AND_CONTEXT.md`'s S1 table. Cache rebuilt, review sample regenerated (still 34
days), full suite (135 tests) still passes -- no test hardcoded `nyam_sb`'s real bounds.

## Next up

0. Akash: double-click `run_tests.bat` and paste the last line (confirms the pandas-3 fix on his laptop).
1. ROADMAP 5.7 (statistics integrity) before any new hypothesis or model — needs his OK since it
   bumps m and changes verdicts.
2. Send Akash the fresh review page (6 sessions, `nyam_sb` now 10:00-12:00) and score his second
   pass once he returns it -- this is what decides whether 5.6's checkbox flips (ticket's own
   accept criteria: >=80% agreement).

The project has 11 phases total (0 through 10): 0 Reproduce v0 (done), 1 Package refactor (done),
2 Replay trainer MVP (done), 3 Ledger/hypothesis stats (done), 4 Economic calendar (done), 5 All
sessions + session character (in progress -- 5.1-5.5 done, 5.6 in progress: trend rule v2,
nyam_kz/nyam_sb swap, and the new lon_ny_gap session all implemented and tested, fresh 6-session
review sample generated, second review round pending), 6 Replay trainer v2, 7 ICT features &
models, 8 Verification/robustness/prop simulation, 9 Daily automation, 10 Research loop
(ongoing).

## 2026-09-27 (round 4 scored) -- independent-judge review of Akash's round-4 answers

91 rows answered, 14 disagreements (77 agree). Raw tally: chop 22/30 (73.3%, FAILS the 80% bar),
reversal 16/19 (84.2%), trend 14/15 (93.3%), range_both 4/5, quiet 9/9, day_type families all
>=80% (n too small on several to mean much -- outside_day n=1, reversal_day n=2). Wilson 95% CI
(not Wald, per Akash's own scoring rule) on chop: [0.556, 0.858] -- the point estimate is under
80%, but the interval comfortably straddles it at n=30; not confident evidence the true rate is
below 80%, just a nudge that needs more data, not a rewrite.

Scored as an INDEPENDENT JUDGE, not a tally -- every one of the 14 disagreements was re-derived
by hand from the raw cached range_rel/er/close_loc (sessions) or day_high/day_low/pdh/pdl
(day_type) and, where a raid/sweep flag was in question, from the actual price levels
(not trusted from the pipeline), same method as round 2's TASK A:

- **Rule verified correct, Akash likely missed something (5):** 2023-05-08 lon_ny_gap
  (reversal; took_prev_low confirmed by 12.9 pips), 2023-08-17 lon (reversal; took_prev_high
  confirmed by 12.2 pips), 2023-08-17 nyam_kz (chop; er=0.16, close_loc=0.492 dead center --
  doesn't fit "Trend" by the rule's own definition), 2025-07-31 nyam_sb (chop; range_rel=1.413
  is large but close_loc=0.535 is dead center -- big range isn't the same thing as trend),
  **2026-06-10 nyam_sb (range_both; Akash said "DIDNT TAKE THE PREV SESSION'S HIGH" -- checked
  by hand: nyam_sb's high (1.15670) DID clear lon's high (1.15586) by 8.4 pips, a clean, visible
  margin, not a rounding artifact. His raid-flag claim was wrong, not the pipeline.**
- **Known "reversal overrides near-trend" priority tension, another instance (1):** 2023-08-17
  nyam_sb -- er=0.448, just 0.002 short of trend_er's 0.45 line, AND took both prev high and low
  (both_sides=True) with close_loc=0.207 -- reversal's own condition also fires here
  (took_high & close_loc<=0.35), and reversal has priority. Correct per the frozen rule as
  written; same design tension flagged in round 2 (reversal always wins even at a near-zero
  margin), still Akash's call whether that priority order is right, not a bug to silently fix.
- **Exact-boundary case, day_type (1):** 2023-08-17 -- close_loc computes to EXACTLY 0.2500,
  landing precisely on trend_day's own cutoff. Akash called it "consolidation day." Not wrong
  per the rule (trend_day's own condition is `<=0.25`, satisfied by equality), but about as
  razor-thin as a boundary case gets -- worth deciding whether trend_day's edge should be
  inclusive or not, independent of any threshold VALUE change.
- **Akash uncertain himself, not a confident override (3):** 2023-05-09 nyam_kz ("downtrend?",
  er=0.243 just 0.007 from chop's 0.25 line but close_loc=0.501 dead center -- doesn't support a
  clean "downtrend" story), 2025-06-16 lon ("I might agree, I am confused" -- close_loc=0.822 is
  extreme but range_rel=1.303 misses trend_range's 1.4 line by 0.097), 2025-06-16 lon_ny_gap
  (same note reused, but this session's own numbers -- er=0.12, range_rel=0.625 -- aren't close
  to any boundary at all; likely spillover from the lon comment on the same day, not a separate
  complaint).
- **Recurring "extreme close_loc / big range, but chop by an er or range_rel margin" shape (4
  new instances this round):** 2024-06-13 nyam_kz (trend fired via trend_range -- range_rel=1.51,
  close_loc=0.192 -- despite er=0.047, an extremely inefficient path; Akash disagreed the other
  way, calling it "chop"), 2025-07-31 nyam_kz (chop; close_loc=0.12 is extreme but range_rel=1.25
  misses 1.4), 2026-05-22 lon_ny_gap (chop; close_loc=0.172 extreme but range_rel=0.785, far
  under 1.4), and the strongest single data point yet: **2026-03-23 nyam_kz** -- range_rel=2.663
  (a genuinely huge range), close_loc=0.74 (0.01 short of trend_er's 0.75 line, 0.06 short of
  trend_range's 0.80 line), er=0.244 (0.006 short of chop's own 0.25 line) -- a session missing
  "trend" on three separate near-boundary margins simultaneously. Combined with round 2's one
  prior instance of the same shape, this is now 5 total occurrences across two rounds --
  crossing Akash's own stated bar ("propose a threshold change only with >=3 same-shape cases").
  **Not touched yet** -- per RESEARCH_PROTOCOL.md's frozen-thresholds rule and Akash's own
  scoring instructions ("verify against the full 5-year distribution, never on the same days
  used to find the pattern -- generate a fresh sample with a different seed"), this needs a
  dedicated fresh-sample verification pass before any of trend_range/trend_er/chop's numbers
  move, not a same-round edit. Flagged for Akash's decision on whether to run that next.

No thresholds in `nylab/sessions.py` were changed. `research/label_validation/
label_validation_answers_r4.json` holds Akash's raw answers (gitignored, matches existing
`research/label_validation/` pattern).


## 2026-09-27 (later) — label-validation round 4: <15 days, "normal" dropped from review

Akash, on seeing round 3 land at 34 days instead of the promised <20: "i want it to have less
than 15 days of testing and i think normal should be removed." Two changes:

1. **Greedy set-cover floor** (`_stratified_floor_greedy`) replaces the old independent-per-
   requirement floor for the curated strategy: same "every occurring label gets >=1 reviewed
   day" guarantee, but exploits real overlap (one day can satisfy several session/label
   requirements at once) -- 7 days instead of 28 on the real 5-year cache, verified by a
   brute-force test confirming 7 really is the minimum, not just what greedy happened to find.
   `sample_days()` (rounds 1-2, `--strategy random`) is untouched.
2. **"normal"/"normal_day" dropped from the floor requirement and never rendered as a
   reviewable row** -- Akash has said plainly he can't judge the catch-all ("normal is not
   well defined imo"). The glossary still explains what they mean; they're just annotated as
   not shown for review. A curated-fill candidate whose every label is "normal"/"normal_day"
   is filtered out before selection so no slot is wasted on a day with nothing to review.

New defaults: `--n 14 --seed 44`. Verified on the real cache: floor=7, final=14 days, 91 real
reviewable rows, zero wasted (all-normal) days, zero "normal"/"normal_day" answer keys baked
into the generated page. 142/142 tests pass. `sample_44.html` sent to Akash for round 4.


## 2026-09-27 — design system approved + label-validation round 3 (curated near-threshold sampling)

**Design system approved.** `design/preview.html` (rejected once earlier, rebuilt, now approved by
Akash) is the single "Porcelain" (light, default) / "Espresso" (dark) neumorphism+glass system.
`docs/DESIGN_SYSTEM.md` §3 rewritten from the old "3 undecided palette directions" placeholder to
the actual approved tokens (pulled from `design/preview.html`, not hand-copied). `nylab/
label_validate.py`'s label-validation review page is the first real (non-preview) surface restyled
to it: same CSS custom properties, `.elev-raised`/`.elev-inset` shadow pairs on the header/day
cards/zoom buttons/Agree-Disagree buttons/bottom bar/note inputs, the same `localStorage`-backed
theme toggle pattern. All of label-validate's exporter-facing DOM hooks (`.ans`, `.sel-agree`,
`.sel-disagree`, `.zoombtn`, `.active`, `.lbl`, `#bar`, `#progress`, `downloadAnswers`) kept exactly
as-is -- only CSS/rendering changed, `score()`'s contract with the page didn't.

**Label-validation round 3: curated near-threshold sampling replaces random fill.** Akash found
rounds 1-2's random days "tiring and time consuming" and specifically flagged that day_type's
inside/outside/reversal calls are hard to eyeball without seeing yesterday's actual range. Two
changes land together (ROADMAP 5.6, still open -- this is groundwork, not the round itself):

- `sample_days_curated()` (new, default strategy): keeps the existing stratified rare-label floor
  verbatim, but fills the remainder by ranking candidate days by distance to the frozen numeric
  thresholds in `sessions.py`'s `_label_character`/`_day_type` rule cascades (mirrored as local
  constants in `label_validate.py`, not imported -- `sessions.py` stays untouched) instead of
  uniform-random selection. A day earns a place if ANY of its labels sits close to flipping across
  a rule boundary -- exactly the ambiguous case where Akash's own judgment adds information, versus
  the "obviously normal"/"obviously trend" days a random sample mostly wastes his time on. Runs over
  the FULL cached 5-year day table every time, never restricted to a previous round or to days he's
  already flagged (would be a form of look-ahead into which round produced disagreements). Old
  `sample_days()` (uniform-random fill) kept unchanged and available via `--strategy random`, for
  reproducing rounds 1-2.
- `build_payload()` now also emits the raw range_rel/er/close_loc (session) and day-level
  close_loc/day_high/day_low/pdh/pdl feature values; the review page shows them as muted text under
  each label, and draws dashed PDH/PDL reference lines on the full-day chart so day_type calls don't
  need mental math (session-zoom views don't get the lines -- their window is usually much narrower
  than the day's own range, so the lines would mostly clip off-canvas there).
- CLI default changed to `--n 20 --seed 43 --strategy curated` (rounds 1-2 used `--n 30/34 --seed 42
  --strategy random`, still reproducible via the flag).

**Verified:** 142/142 tests pass (135 before this work + 7 new, covering the curated sampler, its
boundary-distance helpers, and that its fill genuinely sits closer to a threshold than the random
fill on the same fixture/seed). `python -m nylab label-validate build --n 20 --seed 43` ran against
the real 5-year cache and wrote `research/label_validation/sample_43.html` (+ its `_meta.json`) --
34 days (the stratified floor alone is 34; the curated fill only adds days once it's below `n`, same
"floor never trimmed down" behaviour as before).

**Self-caught bug, fixed before this reached Akash:** an intermediate commit (`6494885`, message: "Restyle label-validation review page...") actually reverted the restyle/feature-values/PDH-PDL work that was already sitting correctly in the prior commit (`7331acf`) -- the file it produced matched its own commit message in words only, not in diff. Caught by re-reading the actual committed file and the already-generated `sample_43.html` before delivery (both still had the old dark/gold template, zero theme toggle), not by trusting the commit message or the build summary. Fixed in `21c8aaa` by restoring `nylab/label_validate.py` to `7331acf`'s version verbatim; 142/142 tests re-confirmed green, and `sample_43.html` was deleted and regenerated from the corrected code before being sent to Akash.

**Known limitations / judgment calls (disclosed, not hidden):** the boundary-distance score treats
every threshold in a rule's AND/OR cascade as its own independent candidate line and takes the
row's minimum distance across all of them, rather than modelling each branch's exact AND/OR
structure -- a closer model would need the underlying price series `label_validate.py` doesn't have
access to (only the cached `days` table's aggregated columns). Distances are raw, not IQR-normalized
(range_rel/er/close_loc are all already unit-free ratios in a similar O(1) range on the real data,
so this doesn't let one feature dominate in practice, and it's easier to sanity-check by eye).
PDH/PDL reference lines only render on the full-day zoom, not per-session zooms. Not started this
round: ROADMAP 5.7 (statistics integrity) and Akash actually scoring round 3 once he's reviewed it.
