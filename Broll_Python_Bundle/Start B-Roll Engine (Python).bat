@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if not %errorlevel% equ 0 (
        echo Python 3.10 or newer was not found.
        echo Install Python from https://www.python.org/downloads/windows/
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".runtime\Scripts\python.exe" (
    echo First run: creating the app environment...
    %PYTHON% -m venv .runtime
    if %errorlevel% neq 0 (
        echo Could not create the Python environment.
        pause
        exit /b 1
    )
    echo First run: installing dependencies...
    ".runtime\Scripts\python.exe" -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo Could not install dependencies. Check your internet connection.
        pause
        exit /b 1
    )
)

echo Starting B-Roll Engine...
".runtime\Scripts\python.exe" -m streamlit run app.py --server.headless false --server.address localhost --browser.gatherUsageStats false
pause