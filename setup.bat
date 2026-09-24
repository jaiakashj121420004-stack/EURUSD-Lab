@echo off
REM EURUSD Session Research Lab -- one-time Windows setup.
REM Double-click this file, or run it from PowerShell/CMD in this folder.

echo Creating virtual environment (.venv) ...
python -m venv .venv
if errorlevel 1 (
    echo.
    echo Could not create the virtual environment. Make sure Python 3.10+ is installed
    echo from python.org with "Add python.exe to PATH" ticked, then run this script again.
    pause
    exit /b 1
)

echo Installing packages into .venv ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package install failed -- check the messages above.
    pause
    exit /b 1
)

echo.
echo Done. From now on, open PowerShell in this folder and run:
echo     .venv\Scripts\activate
echo before any "python mt5_export.py" / "python -m nylab ..." command.
pause
