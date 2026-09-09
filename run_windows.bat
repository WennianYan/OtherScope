@echo off
REM ============================================================
REM   OtherScope Auto Launcher for Windows (Final)
REM   - Python >=3.9 check, rejects Store alias
REM   - pip availability + ensurepip fallback
REM   - Disk space check (string compare, no set /a overflow)
REM   - TEMP writable check
REM   - winget -> PowerShell direct download fallback
REM   - Registry-based Python path (no PATH refresh)
REM   - Normal exit -> auto-close; error -> keep window open
REM   - ASCII-only, CRLF, no goto inside if blocks
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   OtherScope - Windows Auto Launcher
echo   Workdir: %CD%
echo ============================================================
echo.

REM ---- Pre-flight: auto_launcher.py exists ----
if not exist "%~dp0auto_launcher.py" (
    echo [FATAL] auto_launcher.py not found in: %~dp0
    echo Make sure all files are in the same folder.
    pause
    exit /b 1
)

REM ---- Step 1: Find working Python >=3.9 ----
call :find_python
if defined PY goto python_ok

echo [Step 1/4] No working Python ^(>=3.9^) found. Installing...
echo.

REM ---- Disk space check ----
call :check_disk_space
if errorlevel 1 (
    echo [ERROR] Not enough disk space (need ~500MB free).
    echo Please free up disk space and re-run.
    pause
    exit /b 1
)

REM ---- TEMP writable check ----
if not exist "%TEMP%" (
    set "TEMP=%USERPROFILE%\AppData\Local\Temp"
    if not exist "%TEMP%" mkdir "%TEMP%" 2>nul
)
echo test > "%TEMP%\otherscope_write_test.tmp" 2>nul
if not exist "%TEMP%\otherscope_write_test.tmp" (
    echo [ERROR] TEMP not writable: %TEMP%
    pause
    exit /b 1
)
del /q "%TEMP%\otherscope_write_test.tmp" 2>nul

REM ---- Try winget ----
where winget >nul 2>nul
if errorlevel 1 goto winget_skip
echo [Step 1/4] Installing Python 3.12 via winget...
set "WINGET_OK=1"
winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements --silent
if errorlevel 1 (
    echo [WARN] winget failed. Trying direct download...
    set "WINGET_OK=0"
)
if "%WINGET_OK%"=="0" goto winget_skip
echo [Step 1/4] winget install completed.
goto install_done

:winget_skip
REM ---- PowerShell direct download ----
echo [Step 1/4] Downloading Python 3.12.7 installer...
set "INSTALLER=%TEMP%\python-3.12.7-amd64.exe"
if exist "%INSTALLER%" del /q "%INSTALLER%" 2>nul

powershell -NoProfile -Command "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%INSTALLER%' -UseBasicParsing -TimeoutSec 300 } catch { exit 1 }"
if errorlevel 1 (
    echo [ERROR] Download failed. Check internet/firewall/proxy.
    echo Please install Python manually from https://www.python.org/downloads/
    pause
    exit /b 1
)
if not exist "%INSTALLER%" (
    echo [ERROR] Installer not found after download.
    pause
    exit /b 1
)
for %%A in ("%INSTALLER%") do set "SIZE=%%~zA"
if %SIZE% LSS 1000000 (
    echo [ERROR] Installer too small (%SIZE% bytes). Corrupted download.
    del /q "%INSTALLER%" 2>nul
    pause
    exit /b 1
)

echo [Step 1/4] Running installer silently...
"%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
if errorlevel 1 (
    echo [ERROR] Installer failed (exit code !errorlevel!). Antivirus may be blocking.
    del /q "%INSTALLER%" 2>nul
    pause
    exit /b 1
)
echo [Step 1/4] Python installer completed.
del /q "%INSTALLER%" 2>nul

:install_done
REM ---- Read Python path from registry ----
set "PY_DIR="
for /f "skip=2 tokens=2,*" %%A in ('reg query "HKCU\Software\Python\PythonCore\3.12\InstallPath" /ve 2^>nul') do set "PY_DIR=%%B"
if not defined PY_DIR (
    for /f "skip=2 tokens=2,*" %%A in ('reg query "HKLM\Software\Python\PythonCore\3.12\InstallPath" /ve 2^>nul') do set "PY_DIR=%%B"
)
if not defined PY_DIR (
    for /f "skip=2 tokens=2,*" %%A in ('reg query "HKLM\Software\WOW6432Node\Python\PythonCore\3.12\InstallPath" /ve 2^>nul') do set "PY_DIR=%%B"
)

if defined PY_DIR if exist "%PY_DIR%\python.exe" (
    set "PY=%PY_DIR%\python.exe"
    for /f "delims=" %%v in ('"%PY_DIR%\python.exe" --version 2^>^&1') do set "PY_VER=%%v"
    echo !PY_VER! | findstr /i /b /c:"Python" >nul
    if errorlevel 1 (
        echo [WARN] Registry Python at "%PY_DIR%" invalid.
        set "PY="
        set "PY_VER="
    )
)
if not defined PY call :find_python

if not defined PY (
    echo.
    echo [ERROR] Python installed but could not be located.
    echo         Registry path: "%PY_DIR%"
    echo         Please open a NEW command prompt and re-run.
    pause
    exit /b 1
)

:python_ok
echo [Step 1/4] Python ready: %PY_VER%
echo          Path: %PY%
echo.

REM ---- Step 2: pip check ----
echo [Step 2/4] Checking pip...
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] pip not available. Running ensurepip...
    "%PY%" -m ensurepip --upgrade >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] ensurepip failed. pip unavailable.
        pause
        exit /b 1
    )
    "%PY%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] pip still unavailable after ensurepip.
        pause
        exit /b 1
    )
)
for /f "delims=" %%v in ('"%PY%" -m pip --version 2^>^&1') do echo          %%v
echo.

REM ---- Step 3: disk space for deps ----
call :check_disk_space
if errorlevel 1 (
    echo [WARN] Low disk space. Dependency install may fail.
    echo        Continuing anyway...
)
echo.

REM ---- Step 4: run auto-launcher ----
echo [Step 3/4] Starting dependency check and auto-launch...
echo.
"%PY%" "%~dp0auto_launcher.py"
set "LAUNCH_EXIT=%errorlevel%"

echo.
if "%LAUNCH_EXIT%"=="0" (
    echo [Step 4/4] OtherScope finished normally.
    echo          Window will close automatically in 2 seconds...
    echo.
    timeout /t 2 /nobreak >nul
    endlocal
    exit /b 0
) else (
    echo [Step 4/4] Startup failed with code %LAUNCH_EXIT%.
    echo   Scroll up for error details, or check OtherScope_crash.log.
    echo.
    echo Press any key to close this window.
    pause >nul
    endlocal
    exit /b 1
)


REM ============================================================
REM  Subroutine: find_python
REM ============================================================
:find_python
set "PY="
set "PY_VER="
set "FOUND=0"

set "OUT="
for /f "delims=" %%v in ('python --version 2^>^&1') do set "OUT=%%v"
if defined OUT if not "!OUT!"=="" (
    echo !OUT! | findstr /i /b /c:"Python" >nul
    if not errorlevel 1 (
        for /f "tokens=2 delims= " %%a in ("!OUT!") do set "VERSTR=%%a"
        for /f "tokens=1,2 delims=." %%a in ("!VERSTR!") do (
            set "MAJOR=%%a"
            set "MINOR=%%b"
        )
        if !MAJOR! geq 3 (
            if !MAJOR! gtr 3 (
                set "FOUND=1"
            ) else if !MINOR! geq 9 (
                set "FOUND=1"
            )
        )
        if "!FOUND!"=="1" (
            set "PY=python"
            set "PY_VER=!OUT!"
        ) else (
            echo [WARN] Found !OUT! but need ^>=3.9.
        )
    )
)
if "%FOUND%"=="1" goto :eof

set "OUT="
for /f "delims=" %%v in ('py -3 --version 2^>^&1') do set "OUT=%%v"
if defined OUT if not "!OUT!"=="" (
    echo !OUT! | findstr /i /b /c:"Python" >nul
    if not errorlevel 1 (
        for /f "tokens=2 delims= " %%a in ("!OUT!") do set "VERSTR=%%a"
        for /f "tokens=1,2 delims=." %%a in ("!VERSTR!") do (
            set "MAJOR=%%a"
            set "MINOR=%%b"
        )
        if !MAJOR! geq 3 (
            if !MAJOR! gtr 3 (
                set "FOUND=1"
            ) else if !MINOR! geq 9 (
                set "FOUND=1"
            )
        )
        if "!FOUND!"=="1" (
            set "PY=py -3"
            set "PY_VER=!OUT!"
        )
    )
)
goto :eof


REM ============================================================
REM  Subroutine: check_disk_space
REM  Uses string-length compare to avoid set /a 32-bit overflow.
REM ============================================================
:check_disk_space
set "FREE_RAW="
for /f "tokens=3" %%A in ('dir "%SystemDrive%\" /-c ^| findstr /i /c:"bytes free"') do set "FREE_RAW=%%A"
if not defined FREE_RAW (
    echo [WARN] Cannot determine free disk space. Continuing.
    exit /b 0
)
set "FREE_RAW=!FREE_RAW:,=!"
REM 500MB = 524288000 bytes (9 digits). >=10 digits = >=1GB, enough.
set "FREE_LEN=0"
for /L %%N in (0,1,15) do if not "!FREE_RAW:~%%N,1!"=="" set /a FREE_LEN=%%N+1
if !FREE_LEN! geq 10 exit /b 0
if !FREE_LEN! lss 9 (
    echo [WARN] Low disk space: less than 100MB free.
    exit /b 1
)
if "!FREE_RAW!" geq "524288000" (
    exit /b 0
) else (
    echo [WARN] Low disk space: less than 500MB free.
    exit /b 1
)
