# PROGRESS.md — where the build stands

Read this first in any new session. Update it after every ticket: what's done, what's next, open
questions. See CLAUDE.md and docs/ROADMAP.md for the full plan.

## Status: Phase 0 — Reproduce v0

| Ticket | Status | Notes |
|---|---|---|
| 0.1 requirements.txt + setup.bat | done | `requirements.txt` (MetaTrader5, pandas, numpy, matplotlib, pyyaml, pytest, pyarrow, mplfinance) + `setup.bat` (creates `.venv`, installs requirements) added at repo root. Akash runs `setup.bat` once on Windows. |
| 0.2 `tests/fixtures/make_synth.py` clean + planted, seeded, 2y/5y | done | Rewritten with `--variant {clean,planted}`, `--years`, `--seed`, `--frac`. Planted variant forces a down-drive on 09:30→16:00 NY on `frac` (default 60%) of days where the pre-NY window (07:00–09:30) raids the London KZ high — matches DATA_AND_TIME.md §6. Generated: `EURUSD_M5_synth_{clean,planted}_{2,5}y.csv` in `tests/fixtures/` (git-ignore these, they're regenerable). 5 sanity tests in `tests/test_synth_fixtures.py`, all passing. |
| 0.3 Run v0 on the clean fixture; save golden outputs | done | `tests/golden/v0/clean_5y_report/` (`report.html`, `days.csv`, `hypotheses.csv`, `trades.csv`) — this is the Phase 1 regression baseline (nylab's numbers must match within 1e-9). |
| AT-01 (no false edges) on v0/clean | **pass** | v0 on the clean 5y fixture: "Hypotheses passing Bonferroni AND out-of-sample: none"; example model OOS E = −0.375R, CI [−0.55, −0.20] (fully below 0). |
| AT-02 (planted edge found) — informal check with v0 | **pass** (informal) | v0 on the planted 5y fixture found exactly the planted hypothesis: "Pre-NY (07-09:30) raids London high only → NY drive down", hit 67.9% IS / 67.9% OOS (n=159) — well above the 58% bar. This is v0 finding it, not yet nylab (that's the real AT-02 gate once nylab's hypothesis engine exists in Phase 3) — recorded here as evidence the fixture itself is sound. |

## Repo changes made outside the roadmap tickets (context for the next session)

- `README.md` rewritten: corrected "open in Claude Code" → Cowork workflow instructions; added a note
  that `docs/PROGRESS.md` (this file) tracks resume state.
- `docs/ARCHITECTURE.md` §1: annotated the old "NY Session Research Lab" folder-name reference for
  clarity (repo root is `eurusd-lab/`, project name is "EURUSD Session Research Lab").
- Maven account rules verified from maventrading.com (not assumed): Standard 2-Step is 8%/5% profit
  targets (not the +10%/+8% CLAUDE.md currently states — flagged, not yet corrected in CLAUDE.md,
  see Open questions), 8% max DD static/balance-based, 4% daily DD reset at 00:00 UTC. Full table of
  all 7 Maven programs (1-step/2-step/3-step/instant/mini/OMO/BNPL) given to Akash in chat. Plan:
  Phase 8's `config/prop.yaml` will hold all of them as presets; user picks one OR the simulator
  recommends the best-EV one from the model's actual OOS R distribution — not decided for him now.
- Timezone: simplified per Akash's request — no more multi-mode `--tz` decision for him. Default
  is "ny+7" (NY-close convention) with the DATA_AND_TIME.md §2 sanity check (peak volatility must
  land 08:00–11:00 NY) as a red-flag warning if his broker turns out to use a different convention.
  Report OUTPUT is always NY time regardless (CLAUDE.md §3.9, unchanged).
- A stray `.venv` (failed venv attempt, couldn't be deleted — no delete permission granted yet in
  this connected folder) was renamed to `.venv_unused_ignore/` rather than left as `.venv`. Harmless;
  can be cleaned up later if delete permission is granted.

## Open questions for Akash (not blocking — noted for later)

1. CLAUDE.md §1 says Maven step targets are **+10%/+8%**; the verified Standard 2-Step numbers are
   **8%/5%**. Which account did you actually buy — Standard 2-Step, OMO 2-Step (6%/8%), or something
   else? Not urgent: Phase 8 will support all of them as presets, so this only matters when we get
   there.
2. Still unknown until we see a real MT5 export: your broker's actual server-time convention. Default
   assumption (ny+7) will be checked automatically by the sanity test in Phase 1; only comes up if it
   fails.

## Next up: Phase 1 — Package refactor, same numbers

Refactor v0's two scripts into the `nylab/` package per ARCHITECTURE.md, using YAML config instead of
the CONFIG dict, and confirm its output matches the Phase 0 golden files (`tests/golden/v0/clean_5y_report/`)
within 1e-9 tolerance. Nothing needed from Akash for this phase — runs entirely against the synthetic
fixtures already in `tests/fixtures/`.
