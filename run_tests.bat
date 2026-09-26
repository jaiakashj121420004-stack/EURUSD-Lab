@echo off
REM Runs the full test suite in YOUR Windows .venv -- the environment that actually matters.
REM (Tests passing in Claude's cloud sandbox is not enough: on 2026-09-26 they passed there on
REM pandas 2.3 but 9 failed here on pandas 3.0.6, and `nylab run` crashed.)
call .venv\Scripts\activate.bat
python -c "import sys, pandas, numpy; print('python', sys.version.split()[0], '| pandas', pandas.__version__, '| numpy', numpy.__version__)"
python -m pytest -q
if errorlevel 1 (
    echo.
    echo SOME TESTS FAILED -- copy the messages above to Claude before running any research.
) else (
    echo.
    echo All tests passed on this machine.
)
pause
