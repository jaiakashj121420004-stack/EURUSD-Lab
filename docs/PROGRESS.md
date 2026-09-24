# PROGRESS.md — where the build stands

Read this first in any new session. Update it after every ticket: what's done, what's next, open
questions. See CLAUDE.md and docs/ROADMAP.md for the full plan (checkboxes there are also kept current).

## Status: Phase 1 done — package refactor, same numbers as v0

### Phase 0 — Reproduce v0: done
- `requirements.txt` + `setup.bat` at repo root (one-double-click Windows setup).
- `tests/fixtures/make_synth.py`: `--variant {clean,planted}`, `--years`, `--seed`, `--frac`.
  Generated `EURUSD_M5_synth_{clean,planted}_{2,5}y.csv` (git-ignored, regenerable).
- `tests/golden/v0/clean_5y_report/`: v0's own output on the clean fixture — the Phase 1
  regression baseline.
- AT-01 confirmed on v0/clean (no false edges). AT-02 informally confirmed via v0 on the
  planted fixture (finds the planted hypothesis, 68% hit, holds OOS).

### Phase 1 — Package refactor: done
- New `nylab/` package (see ARCHITECTURE.md layout): `config.py`, `data/{loader,timezones,quality}.py`,
  `days.py`, `hypotheses.py`, `stats.py`, `models/london_sweep_reversal.py`,
  `report/{charts,html,summary}.py`, `cache.py`, `__main__.py`.
- `python -m nylab run <csv> [--tz auto|ny+7|ny|utc|utc+N|eu] [--oos 0.3] [--out DIR]` reproduces
  v0's whole pipeline (day table → 15 hypotheses → example model → report.html) plus two things
  v0 didn't have: `summary.json` (ARCHITECTURE.md §6 schema) and a parquet cache
  (`data/cache/bars_M5.parquet`, `days.parquet`).
- `config/windows.yaml` holds the full SESSIONS_AND_CONTEXT.md §1 session table (used from Phase 5)
  plus a `legacy_aliases` block so `nylab/days.py` stays a low-risk, near-verbatim port of v0's
  `build_days()` — same column semantics, same numbers, just YAML-driven instead of a hardcoded dict.
  `config/costs.yaml`, `config/models/london_sweep_reversal.yaml`, `config/prop.yaml` (Maven, see below)
  added too.
- `nylab/data/loader.py` auto-sniffs the CSV delimiter (`sep=None`) so it accepts both the
  python-export format and MT5's tab-separated "Export Bars" format with `<DATE>`/`<TIME>` headers.
- `nylab/data/timezones.py`: `auto`/`ny+7`/`ny`/`utc(+N)`/`eu` conversion + `sanity_check()` (red
  flag if the volatility peak isn't inside 08:00–11:00 NY) — default is `ny+7` per Akash's request
  (2026-09-24): the report warns instead of asking him to pick a mode.
- `nylab/data/quality.py`: bar-interval/OHLC-integrity/duplicate/price-spike checks + per-day
  thin/gappy flags (DATA_AND_TIME.md §5, §3). Reported in `summary.json["data_quality"]`, **not**
  used to filter the day table yet (v0 didn't either — needed for exact parity).
- `nylab/days.py`: `COLUMN_DOCS` dict documents `available_at_h` for all 86 DAY columns
  (ROADMAP 1.6) — the mechanism Phase 3+ will use to structurally block look-ahead in hypotheses.
- **Regression proof:** `tests/test_nylab_phase1.py` runs `python -m nylab run` on the clean 5y
  fixture and diffs `days.csv` (all 86 columns), `trades.csv`, `hypotheses.csv` against the Phase 0
  golden files — **all match within 1e-9 (in practice: exactly)**. Also: `summary.json` schema
  check, a parquet cache round-trip, and an AT-03 look-ahead test on the `window()` helper (truncate
  bars right after a window closes; the window's columns for that day must not change).
- Bug found + fixed during this phase: `windows.yaml`'s `asia` session is stored already
  h-relative (`[-4, 0]`, per SESSIONS_AND_CONTEXT.md §1), but `days.py` initially still applied
  v0's old `-24` shift (needed only for v0's un-shifted `(20,24)` convention) — double-shifted
  Asia out of range, all-NaN. Fixed in `nylab/days.py`; regression test now covers it.
- Sanity re-run on the **planted** fixture through `nylab` (not just v0): finds the same 3
  hypotheses as v0 did, same trade count (722), same numbers — informal extra confirmation the
  port is faithful.
- `pytest -q`: **11 passed** (5 from Phase 0 + 6 new).
- `docs/ROADMAP.md` Phase 0 + Phase 1 checkboxes ticked.

## Repo changes made outside the roadmap tickets (context for the next session)

- `README.md` corrected for Cowork (not Claude Code) workflow; `docs/ARCHITECTURE.md` §1 naming
  note (repo root `eurusd-lab/`, project name "EURUSD Session Research Lab").
- Maven account rules (`config/prop.yaml`): verified from maventrading.com, not assumed. Akash
  confirmed (2026-09-24) to go with the verified numbers over what CLAUDE.md originally guessed
  (CLAUDE.md §1 still says +10%/+8% — not corrected there yet, low priority, see below). All 7
  Maven programs captured as presets with sizes/targets/drawdown type; `akash_account_size: 5000`
  set, program not yet confirmed (defaults to `standard_2step`). Phase 8's Maven pass simulator
  will let him pick one or get an EV-based recommendation.
- Git repo initialized in `eurusd-lab/` (wasn't one before); one commit per phase so far.
- Delete permission was requested and granted for `C:\Trading` this session (needed to clean up
  git/pip lock files that a locked-down connected folder can't remove on its own) — device_bash can
  now delete inside that folder for the rest of this session.

## Open questions for Akash (not blocking)

1. Which Maven program did you actually buy? CLAUDE.md's stated targets (+10%/+8%) don't match
   any verified program exactly. Not urgent — only matters once Phase 8 builds the pass simulator.
2. Still unknown until a real MT5 export: your broker's actual server-time convention. Default
   `ny+7` will be checked automatically by `sanity_check()`; only comes up if it warns.
3. Cosmetic, not blocking: CLAUDE.md §1 itself still has the old +10%/+8% text — worth a quick
   correction pass later so the doc and `config/prop.yaml` don't disagree on paper.

## Next up: Phase 2 — Replay trainer MVP

This is the user's first practical tool (usable before the rest of the research machinery).
Needs: local HTTP server + vendored `lightweight-charts` (Apache-2.0, fetched once — needs
internet somewhere, see README/CLAUDE.md §5a), date picker, day table with basic filters,
playback controls, session-box overlays, mock trading + Maven account panel, no-leak API test.
Akash's part: launching `python -m nylab replay` himself on Windows (opens his own browser) —
a server I start in the sandbox/connected-folder shell can't reach his real browser. Nothing else
needed from him to start.
