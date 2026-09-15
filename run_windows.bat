@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---- Detect system language ----
set "LANG=en"
for /f "tokens=2 delims=:" %%a in ('chcp') do set "CODEPAGE=%%a"
set "CODEPAGE=!CODEPAGE: =!"
if "!CODEPAGE!"=="936" set "LANG=zh"
if "!CODEPAGE!"=="950" set "LANG=zh"
if "!CODEPAGE!"=="932" set "LANG=ja"

REM ---- i18n strings ----
if "!LANG!"=="zh" (
    set "MSG_TITLE=OtherScope - Windows 全自动启动器"
    set "MSG_SEP============================================================="
    set "MSG_NO_SCRIPT=[错误] auto_launcher.py 未找到！"
    set "MSG_NO_PY=未找到 Python，正在安装 Python 3.12..."
    set "MSG_DOWNLOAD=正在下载 Python 安装包..."
    set "MSG_INSTALL=正在安装 Python..."
    set "MSG_FOUND=已找到 Python: "
    set "MSG_START=正在启动 OtherScope..."
    set "MSG_FAIL=启动失败，错误码: "
    set "MSG_OK=OtherScope 正常退出。"
    set "MSG_DL_FAIL=[错误] 下载失败，请检查网络连接。"
    set "MSG_INSTALL_FAIL=[错误] 安装失败，可能被杀毒软件拦截。"
    set "MSG_PY_NOT_FOUND=[错误] Python 已安装但未在预期路径找到。"
    set "MSG_RERUN=请重新运行或手动安装 Python。"
    set "MSG_END=程序异常结束，按任意键关闭。"
) else (
    set "MSG_TITLE=OtherScope - Windows Auto Launcher"
    set "MSG_SEP============================================================="
    set "MSG_NO_SCRIPT=[ERROR] auto_launcher.py not found!"
    set "MSG_NO_PY=No Python found. Installing Python 3.12..."
    set "MSG_DOWNLOAD=Downloading Python installer..."
    set "MSG_INSTALL=Installing Python..."
    set "MSG_FOUND=Python found: "
    set "MSG_START=Starting OtherScope..."
    set "MSG_FAIL=Startup failed with code "
    set "MSG_OK=OtherScope finished normally."
    set "MSG_DL_FAIL=[ERROR] Download failed. Check internet connection."
    set "MSG_INSTALL_FAIL=[ERROR] Install failed. Antivirus may be blocking."
    set "MSG_PY_NOT_FOUND=[ERROR] Python installed but not found at expected path."
    set "MSG_RERUN=Please run again or install Python manually."
    set "MSG_END=Program ended with error. Press any key to close."
)

echo !MSG_SEP!
echo   !MSG_TITLE!
echo !MSG_SEP!
echo.

if not exist "%~dp0auto_launcher.py" goto no_script

REM ---- Find real Python (not Store alias) ----
set "PY="
for /f "delims=" %%v in ('where python.exe 2^>nul') do (
    echo %%v | findstr /i /c:"WindowsApps" >nul
    if errorlevel 1 (
        set "PY=%%v"
        goto found_py
    )
)

REM ---- No real Python found - install it ----
echo !MSG_NO_PY!
echo.

echo !MSG_DOWNLOAD!
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%TEMP%\py_installer.exe' -UseBasicParsing"
if errorlevel 1 goto dl_failed

echo !MSG_INSTALL!
"%TEMP%\py_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
if errorlevel 1 goto install_failed
del "%TEMP%\py_installer.exe" >nul 2>nul

REM Use default install path
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" goto py_not_found

:found_py
echo !MSG_FOUND!!PY!
echo.

REM ---- Run auto_launcher ----
echo !MSG_START!
echo.
"%PY%" "%~dp0auto_launcher.py"
set "RC=!errorlevel!"

echo.
if "!RC!"=="0" goto normal_end
echo !MSG_FAIL!!RC!
pause
goto error_end

:normal_end
echo !MSG_OK!
timeout /t 2 /nobreak >nul
endlocal
exit /b 0

:no_script
echo !MSG_NO_SCRIPT!
pause
goto error_end

:dl_failed
echo !MSG_DL_FAIL!
pause
goto error_end

:install_failed
echo !MSG_INSTALL_FAIL!
pause
goto error_end

:py_not_found
echo !MSG_PY_NOT_FOUND!
echo !MSG_RERUN!
pause
goto error_end

:error_end
echo.
echo !MSG_SEP!
echo   !MSG_END!
echo !MSG_SEP!
pause
endlocal
exit /b 1
