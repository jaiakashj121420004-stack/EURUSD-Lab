@echo off
REM ROADMAP Phase 9 (9.1-9.4): daily automation -- pull new MT5 bars, re-run the research pipeline,
REM refresh the replay cache and report. Meant to run BOTH unattended, from Windows Task Scheduler
REM (see docs/DAILY_AUTOMATION.md for the exact setup steps), and by hand for a one-off check.
REM
REM No "pause" anywhere in this file: Task Scheduler runs it with no one there to press a key, and
REM a pause would just hang forever. To watch it run instead of it flashing past, open a Command
REM Prompt in this folder yourself and type "run_daily.bat" (the window then stays open afterwards
REM since it's already open, unlike double-clicking the file, which closes the window on exit).
REM
REM Safe to run more than once on the same day: mt5_export.py --append-to de-duplicates by bar
REM time, and `nylab run --dedupe-same-day` skips re-writing a ledger row for anything already
REM logged today -- ROADMAP 9's own accept test ("running twice on the same day is idempotent").

setlocal
cd /d "%~dp0"

REM Edit this line if you ever rename the export file -- everything else reads it from here.
set CSV_FILE=EURUSD_M5_2021-09-27_2026-09-25.csv

if not exist logs mkdir logs
set LOGFILE=logs\run_daily.log

REM A stable, predictable run-id/report folder per calendar day (not the usual minute-stamped
REM default) -- a same-day re-run overwrites reports\daily-YYYY-MM-DD\ with the same numbers
REM instead of piling up a new folder every retry.
for /f %%i in ('python -c "from datetime import date; print(date.today().isoformat())"') do set TODAY=%%i
set RUN_ID=daily-%TODAY%

echo. >> "%LOGFILE%"
echo ===== run_daily.bat started %date% %time% ===== >> "%LOGFILE%"

call .venv\Scripts\activate.bat >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo Could not activate .venv -- run setup.bat first. See %LOGFILE%.
    exit /b 1
)

echo [1/3] Pulling any new bars from MT5 (needs MT5 open and logged in)...
python mt5_export.py --append-to "%CSV_FILE%" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo MT5 export FAILED -- is the MT5 terminal open and logged in? See %LOGFILE% for details.
    echo ===== run_daily.bat FAILED at step 1 %date% %time% ===== >> "%LOGFILE%"
    exit /b 1
)

echo [2/3] Re-running the research pipeline (ledger, report, replay cache)...
python -m nylab run "%CSV_FILE%" --dedupe-same-day --run-id "%RUN_ID%" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo nylab run FAILED. See %LOGFILE% for details.
    echo ===== run_daily.bat FAILED at step 2 %date% %time% ===== >> "%LOGFILE%"
    exit /b 1
)

echo [3/3] Checking the economic calendar isn't going stale (ROADMAP 9.4)...
python -m nylab calendar-freshness >> "%LOGFILE%" 2>&1
python -m nylab calendar-freshness

echo.
echo Done. Report: reports\%RUN_ID%\report.html   Full log: %LOGFILE%
echo ===== run_daily.bat finished OK %date% %time% ===== >> "%LOGFILE%"
exit /b 0
