@echo off
REM OtherScope launcher for Windows
REM Usage: double-click this file, or run from cmd: run_windows.bat

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.9+ and add it to PATH.
    pause
    exit /b 1
)

python launcher.py
endlocal
