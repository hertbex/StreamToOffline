@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [StreamToOffline] Creating Python environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [StreamToOffline] Python 3 was not found. Install Python 3.11+ and try again.
        pause
        exit /b 1
    )
)

set PYTHONUNBUFFERED=1
".venv\Scripts\python.exe" -c "import streamtooffline, textual, yt_dlp, pydantic, yaml, mutagen" >nul 2>&1
if errorlevel 1 (
    echo [StreamToOffline] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -e ".[dev]" --disable-pip-version-check
    if errorlevel 1 (
        echo.
        echo [StreamToOffline] Dependency installation failed.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m streamtooffline wizard
if errorlevel 1 (
    echo.
    echo [StreamToOffline] Unexpected error. See messages above.
    pause
)
endlocal
