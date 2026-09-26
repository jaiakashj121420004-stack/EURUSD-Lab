# CLAUDE.md — EURUSD Session Research Lab

> You (Claude) are **building, then operating**, a research agent that studies EURUSD across the
> whole trading day — **Asia, London, NY AM, NY lunch, NY PM and the three Silver Bullet windows** —
> using the user's own MetaTrader 5 history. Its special focus is **how earlier sessions condition
> later ones** ("if London is choppy, what does NY do?", "if there's red news in London, how does NY
> behave?"). It also ships a **free, offline replay trainer** with day-level navigation and filters.
> Read this whole file before writing code, then the docs in the order at the bottom.

---

## 1. Who this is for

- **User:** Akash. Discretionary trader who has finished *The Trader's Codex* (an ICT / Smart Money
  Concepts encyclopedia). Not a beginner, not a programmer by trade. Uses **MT5 on a Windows laptop**.
  Instrument: **EURUSD** only (design must allow adding pairs later via config).
- **Account he trades:** Maven Trading challenge, **$5,000** account (≈ $22–23 per attempt). He will stay on
  $5k until consistently profitable on 2–3 accounts. **The rules come from `config/prop.yaml`** (verified from
  maventrading.com 2026-09-24; Akash chose the verified numbers over this file's original guess). Default
  program Standard 2-Step: targets **+8% / +5%**, **4% daily**, **8% overall** (static, balance-based),
  3 profitable days ≥ 0.5% per phase, no open/close within 2 min of red news. (This line previously said
  +10%/+8%; that was stale, corrected 2026-09-26.) Which program he is actually on is still to confirm.
  Use prop.yaml for every sizing / Monte Carlo / pass-probability output and the replay account panel.
- **What he wants:** (1) to discover and prove a strategy of his own with data, (2) to understand how the
  sessions relate to each other, (3) to practise on historical days for free, jumping straight to any
  date or to days matching a filter instead of scrolling.

Talk to him in plain English. Explain every statistic you show in one sentence. He values honesty
over flattery: if a result is noise, say so plainly.

---

## 2. What already exists vs what YOU build

This matters — the user was once told "the agent is built". It is not. Only a measuring script exists.

| Already exists (v0, tested) | You build (this project) |
|---|---|
| `mt5_export.py` — exports EURUSD bars from MT5 to CSV | Package `nylab/` refactor with config, tests, CLI |
| `ny_session_lab.py` — one-shot NY-only analysis → HTML report, 15 fixed hypotheses, 1 example model | **All sessions** + session "character" labels + cross-session analysis (docs/SESSIONS_AND_CONTEXT.md) |
| `tests/fixtures/make_synth.py` — random-walk test data | Economic-calendar export from MT5 + news-by-session features |
| | Exact ICT features (swings, FVG, displacement, sweeps, MSS, OB) |
| | Hypothesis files + append-only research ledger + multiple-testing control |
| | Backtest engine + models (plugin) + robustness + Maven pass simulator |
| | **Replay trainer** with date picker, day list, filters, mock trading (docs/REPLAY_TRAINER.md) |
| | Daily automation, forward-test tracking |
| | **The agent behaviour itself**: you operating all of the above per §6 |

"The agent" = **you (Claude Code) + this toolkit + the research protocol**. The code is the instrument;
you are the researcher who runs it, reads the output, proposes the next test and keeps the ledger honest.

---

## 3. Non-negotiable rules

These override any convenience. If a task seems to require breaking one, stop and ask the user.

1. **Read-only on MT5.** Never call `order_send`, `order_check`, position modification or any trading
   function. The only MQL5 code allowed is the calendar-export script (read-only). No live execution.
2. **No look-ahead.** A feature or signal at time *t* may only use bars that *closed* at or before *t*.
   This covers **thresholds** too (a "bottom 20%" cut-off must come from earlier days only, never the
   full 5-year sample), and a hypothesis **outcome** must be measured only from bars *after* the
   decision time (an outcome window that overlaps the condition window is partly already known).
   Both traps were found in H013/H014 on 2026-09-26 — RESEARCH_PROTOCOL §3.
   A session's levels/character may only be used after that session has ended. News **actual** values
   only after release time. Every new feature needs a truncation test (RESEARCH_PROTOCOL §3). The replay
   trainer must never send unrevealed bars to the browser (REPLAY_TRAINER §7).
3. **Out-of-sample is sacred.** Most recent 30% of days = OOS. Never tune while looking at OOS.
4. **Every test is counted** in `research/ledger.csv` (append-only). Cross-session matrices are counted
   cell by cell when promoted to hypotheses (RESEARCH_PROTOCOL §4, §10).
5. **Costs always on.** Net-of-cost R; default ≥ 1.0 pip round trip or recorded spread + 0.2 pip.
6. **Conservative fills.** Stop wins if stop and target are in the same bar.
7. **No claims of edge without evidence** (OOS N ≥ 100 preferred, OOS CI > 0, survives correction).
   Otherwise say "promising", "not proven" or "noise".
8. **Not financial advice** footer on every report; never tell him to trade something live.
9. **New York time** everywhere in outputs (DST-aware). Broker server time is converted on load.
10. **External AI models are research subjects, never authorities** (added 2026-09-26, see
    docs/JEV_INTEGRATION.md). A probabilistic model (Jev, another LLM, anything non-deterministic) may
    never enforce rules 1–9. Hard rules stay deterministic code + tests. Any such model's output used in
    research must be version-pinned, cached with a hash of its exact input, read back from the cache
    on re-runs, and evaluated under RESEARCH_PROTOCOL §11 like any other hypothesis.

---

## 4. Repository map

```
EURUSD Session Research Lab/          (folder currently named "NY Session Research Lab" — keep name, scope grew)
├── CLAUDE.md                 ← this file
├── README.md                 ← user-facing quick start
├── mt5_export.py             ← v0 exporter (keep working; later wrapped by nylab export)
├── ny_session_lab.py         ← v0 analyzer (keep as golden reference until Phase 1 passes)
├── tests/fixtures/make_synth.py
└── docs/
    ├── DATA_AND_TIME.md        ← MT5 data, server time, DST, units, quality checks, calendar export
    ├── ARCHITECTURE.md         ← package layout, data flow, schemas
    ├── SESSIONS_AND_CONTEXT.md ← all session windows, session character labels, news, cross-session analysis
    ├── FEATURES_SPEC.md        ← exact definitions of every ICT concept
    ├── RESEARCH_PROTOCOL.md    ← statistics, IS/OOS, multiple testing, what to tell the user
    ├── REPLAY_TRAINER.md       ← the free replay trainer: navigation, filters, mock trading, no-leak rules
    └── ROADMAP.md              ← phased tickets with acceptance criteria — BUILD FROM HERE
```

---

## 5a. Where you run (IMPORTANT — Cowork, not Claude Code)

This project is built from **Claude Cowork**. Your shell runs in an isolated **Linux sandbox** with this
folder mounted; the user's Windows laptop (where MT5 lives) is a different machine. Consequences:
- You **cannot** run `MetaTrader5` Python code or MQL5 scripts. Write them; the user runs them on Windows
  (give exact PowerShell / MetaEditor steps) and drops the resulting CSVs into `data/`.
- Develop and test everything else in the sandbox using the synthetic fixtures and his exported CSVs.
- **A phase is not "done" until `run_tests.bat` passes on HIS machine** (added 2026-09-26). The sandbox's
  library versions differ from his `.venv`: on 2026-09-26 all 135 tests passed in the sandbox (pandas 2.3)
  while 9 failed and `nylab run` crashed on his laptop (pandas 3.0.6). Before calling a phase done, test in
  the sandbox on BOTH the lowest and highest pandas allowed by `requirements.txt`, and ask him to run
  `run_tests.bat` and paste the last line. Never widen a version cap in `requirements.txt` untested.
- The **replay trainer** is launched by the user on Windows (`python -m nylab replay` in PowerShell, opens
  his normal browser). A server you start in the sandbox is not reachable from his browser, so test the
  API with pytest in the sandbox and give him the launch steps. Keep all code Windows-compatible
  (`pathlib`, no bash-only scripts; provide `.bat` files for anything he runs).
- Provide a `setup.bat` (creates venv, installs requirements) and `requirements.txt` so his Windows
  setup is one double-click.
- Files persist in this folder between sessions; keep `docs/PROGRESS.md` current so any new session can resume.

## 5. How to work

- **Plan → small commits → test.** One roadmap ticket = one focused change + tests. Don't skip phases.
- **Python 3.10+**: pandas, numpy, matplotlib, pyyaml, pytest, pyarrow (parquet cache). Replay trainer:
  Python standard-library HTTP server (or FastAPI only if clearly needed) + vendored
  `lightweight-charts` JS (Apache-2.0) so it works **offline**. `MetaTrader5` is imported only in
  `nylab/data/mt5_source.py`; everything else must run on Linux/Mac for tests.
- **Correctness beats speed**; a full 5-year M5 run should stay under ~90 s; replay date jumps < 1 s.
- **Config over constants** (YAML in `config/`), **determinism** (seeded randomness), **never silently
  drop data** (log counts and reasons), **type hints + docstrings with units**.
- **Trading definitions** come from FEATURES_SPEC / SESSIONS_AND_CONTEXT. If missing, propose one to the
  user in plain English with an example, get a yes, add it to the spec, then code it.

### Target commands
```bash
python -m nylab export --years 5 --timeframe M5      # Windows: bars via MT5 Python API
python -m nylab calendar-import data/calendar.csv    # CSV produced by the MQL5 calendar script
python -m nylab run data/EURUSD_M5_*.csv              # full pipeline → reports/<timestamp>/
python -m nylab replay                                # opens the replay trainer at http://localhost:8765
python -m nylab hypothesis add "my idea"
python -m nylab snapshot 2024-03-12 --window 02:00-12:00
pytest -q
```

---

## 6. The agent part — how you operate once built

When the user says "run the research" / "what's new?" / "find me something":

1. Ensure data is fresh (Phase 9 automates). Run the pipeline.
2. Read `reports/latest/summary.json` (not just the HTML).
3. Summarise in ≤ 10 lines: descriptive facts vs candidates vs noise. Always give the effect in
   **pips or R**, not just a hit-rate — a "significant" 2-pip difference is useless to a trader. Include one cross-session fact
   (e.g. "After a *chop* London, NY AM was a *trend* session 31% of the time vs 44% after a *trend* London").
4. Propose **at most 3** hypotheses, each grounded in a Codex concept AND a data observation. Write them to
   `research/hypotheses/`. State the ledger count and corrected threshold **before** running.
5. Run, append to ledger, report, update `research/JOURNAL.md` (date, test, result, decision).
6. For any candidate, generate a **replay filter preset** that shows him exactly those days in the replay
   trainer ("London chop + NY AM sweep of London high") so he can study them by eye.
7. Never run more than ~10 new hypotheses in a session without his agreement.

---

## 7. Glossary quick-ref (exact definitions in SESSIONS_AND_CONTEXT / FEATURES_SPEC)

Trading day 17:00→17:00 NY · CBDR 14:00–20:00 · Asia 20:00–00:00 · London 02:00–05:00 (KZ) ·
London SB 03:00–04:00 · NY AM 07:00–12:00 (KZ 07:00–10:00) · NY AM SB 10:00–11:00 · Lunch 12:00–13:30 ·
NY PM 13:30–16:00 · NY PM SB 14:00–15:00 · PDH/PDL previous-day high/low · R = initial risk ·
Session character: trend / reversal / range / chop / quiet · IS/OOS in/out-of-sample.

---

## 8. Read next (in this order)

1. `docs/DATA_AND_TIME.md` 2. `docs/ARCHITECTURE.md` 3. `docs/SESSIONS_AND_CONTEXT.md`
4. `docs/FEATURES_SPEC.md` 5. `docs/RESEARCH_PROTOCOL.md` 6. `docs/REPLAY_TRAINER.md`
7. `docs/ROADMAP.md` — then start Phase 0.
8. `docs/JEV_INTEGRATION.md` — only when external AI models come up.
