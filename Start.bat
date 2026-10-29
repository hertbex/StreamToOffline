@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [StreamToOffline] Python environment is missing.
    echo Expected: %CD%\.venv\Scripts\python.exe
    echo.
    pause
    exit /b 1
)

set PYTHONUNBUFFERED=1
".venv\Scripts\python.exe" -m streamtooffline wizard
if errorlevel 1 (
    echo.
    echo [StreamToOffline] Unexpected error. See messages above.
    pause
)
endlocal
