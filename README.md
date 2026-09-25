# EURUSD Session Research Lab — quick start (for Akash)

Studies EURUSD across **Asia, London, NY AM, NY PM and the Silver Bullet windows** using your own MT5
history, with a focus on how earlier sessions shape later ones. Also includes (once built) a **free replay
trainer** that jumps to any date and filters days. Read-only: nothing here can place a trade.

## What exists today vs what Claude will build

- **Exists now (v0):** `mt5_export.py` (gets your data out of MT5) and `ny_session_lab.py` (a one-shot
  NY-session report). It's a measuring script, not the agent.
- **Claude builds:** everything in `docs/ROADMAP.md` — all sessions, cross-session analysis, news from MT5's
  calendar, the replay trainer, ICT feature detection, models, the Maven pass simulator, daily automation —
  and then *operates* it as your research agent.

## Run v0 today (10 minutes)

1. Install Python 3.10+ from python.org (tick "Add python.exe to PATH").
2. MT5: log in, Tools → Options → Charts → **Max bars in chart = Unlimited**, restart MT5.
3. PowerShell in this folder:
   ```
   pip install MetaTrader5 pandas numpy matplotlib
   python mt5_export.py --years 5
   python ny_session_lab.py "EURUSD_M5_<dates>.csv"
   ```
4. Open `ny_lab_report/report.html`. Check Section 0: volatility should peak 08:00–11:00 NY. If not,
   re-run with `--tz utc` or `--tz utc+2`.

## Build the full agent with Claude (Cowork, not Claude Code)

This project is built and operated from **Claude Cowork**, with this folder connected to the session
(not from the Claude Code CLI). Claude's own shell runs in a cloud sandbox — it cannot run `MetaTrader5`
Python code or open MT5/MetaEditor, since MT5 only runs on your Windows machine. Any step that needs
MT5, MetaEditor or your browser (exporting bars, running the calendar script, launching the replay
trainer) is handed to you as exact, one-step-at-a-time PowerShell or `.bat` instructions — you never
need to write or debug code yourself.

To start (or resume) the build, open a Cowork session with this folder connected and say:
> "Read CLAUDE.md and all docs, then start Phase 0 of docs/ROADMAP.md. Stop after each phase and show me the result."

Order of phases: refactor → **replay trainer (Phase 2 — usable early)** → hypothesis ledger → news calendar
→ all sessions & cross-session analysis → replay filters v2 → ICT features & models → verification &
Maven simulator → daily automation → ongoing research.

Progress and open questions are tracked in `docs/PROGRESS.md` (created once Phase 0 starts) so any new
session can pick up exactly where the last one left off.

## Phase 4 -- economic calendar (one-time, per broker)

MT5's Python package can't read the economic calendar, only MQL5 can. `mql5/ExportCalendar.mq5` is
a **read-only** script (it never places or touches a trade) that dumps the calendar to a CSV:

1. In MT5, press **F4** to open MetaEditor.
2. File > Open > browse to `mql5/ExportCalendar.mq5` in this folder > Open.
3. Press **F7** to compile. It should compile with 0 errors (warnings are fine).
4. Back in MT5's Navigator panel (Ctrl+N), open **Scripts**, find `ExportCalendar`, and drag it onto
   any open chart (the symbol/timeframe don't matter -- it reads the calendar, not that chart's price).
5. A dialog pops up with Inputs -- the defaults (5 years back, USD+EUR, importance >= low) are fine,
   just click OK.
6. Click the **Experts** tab at the bottom of MT5 and read the two lines it prints: how many rows it
   wrote, and the earliest event date it found (that's the limit of MetaQuotes' own calendar history
   for your broker -- not a bug if it's later than 5 years back).
7. Find `calendar_export.csv` in your MT5 data folder: File > Open Data Folder > `MQL5/Files/`. Copy
   it into this project folder (`C:\Trading\eurusd-lab\`).
8. Back in PowerShell (venv active): `python -m nylab calendar-import calendar_export.csv`
9. `python -m nylab run "<your csv>.csv"` will now pick up `data/calendar.parquet` automatically and
   print how many USD/EUR rows it attached.

Calendar functions don't work inside the Strategy Tester -- step 4 must be a live chart, not a backtest.

If your broker disables MQL5 calendar access (rare), a fallback CSV with columns
`datetime_ny,currency,event,impact,actual,forecast,previous` works instead of steps 1-7.

## What the numbers mean
- **Hit vs baseline:** an idea only matters if it happens more often than on all days.
- **m / Bonferroni:** the more ideas tested, the stricter the bar — otherwise luck looks like an edge.
- **Out-of-sample:** the last 30% of days are hidden while designing; ideas that die there were luck.
- Full explanations: *Codex Formula Handbook* Part 11 and the *Strategy Development Guide*.
