@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---- Detect native codepage BEFORE switching to UTF-8 (so we can pick language) ----
for /f "tokens=2 delims=:" %%a in ('chcp') do set "OLDCP=%%a"
set "OLDCP=!OLDCP: =!"
chcp 65001 >nul

REM Simplified Chinese(936) / Traditional Chinese(950) -> zh, otherwise English
set "LANG=en"
if "!OLDCP!"=="936" set "LANG=zh"
if "!OLDCP!"=="950" set "LANG=zh"

REM ===================== i18n strings =====================
if "!LANG!"=="zh" (
    set "MSG_TITLE=OtherScope Windows 打包工具"
    set "MSG_LINE============================================================="
    set "MSG_WELCOME=   OtherScope Windows 单文件打包（双击即打包）"
    set "MSG_SRCDIR=   源码目录: "
    set "MSG_PY_NOT_FOUND=[提示] 未检测到 Python，正在自动下载并安装 Python 3.12 ..."
    set "MSG_DOWNLOAD=  正在下载官方安装包 ..."
    set "MSG_INSTALL=  正在静默安装 Python（约 1~2 分钟）..."
    set "MSG_DL_FAIL=[错误] 下载失败，请检查网络后重试。"
    set "MSG_INSTALL_FAIL=[错误] 安装失败，可能被杀毒软件拦截。"
    set "MSG_PY_NOT_FOUND2=[错误] Python 安装完成，但未在预期路径找到解释器。"
    set "MSG_PY_FAIL=[错误] 未找到可用的 Python。"
    set "MSG_PY_HINT1=  可手动安装 Python 3.12 后重新双击本脚本："
    set "MSG_PY_HINT2=  下载地址: https://www.python.org/downloads/"
    set "MSG_USING_PY=[1/6] 使用 Python: "
    set "MSG_CHECK_PIP=[2/6] 检查 pip ..."
    set "MSG_PIP_INSTALL=[错误] pip 不可用，尝试安装 ..."
    set "MSG_PIP_FAIL=[错误] pip 安装失败，请把上面的报错截图反馈。可手动执行: python -m ensurepip --upgrade"
    set "MSG_DISK=[3/6] 检查磁盘空间 ..."
    set "MSG_DISK_FAIL=[错误] 可用磁盘空间不足（需约 2.5 GB）。请清理磁盘后重新运行。"
    set "MSG_INSTALL_DEPS=[4/6] 安装依赖（PySide6/pyqtgraph/pyserial/numpy/pyinstaller）..."
    set "MSG_MIRROR=[提示] 默认源安装失败，切换国内镜像重试 ..."
    set "MSG_DEPS_FAIL=[错误] 依赖安装失败。请检查网络后重试，或手动执行:"
    set "MSG_CLEAN=[5/6] 清理旧产物并开始打包（首次约 3~8 分钟）..."
    set "MSG_BUILD_FAIL=[错误] 打包失败。常见原因："
    set "MSG_BUILD_FAIL1=  - 杀毒软件拦截了构建进程（请临时关闭或允许）"
    set "MSG_BUILD_FAIL2=  - 内存不足（请关闭其他程序后重试）"
    set "MSG_BUILD_FAIL3=  - 磁盘空间不足"
    set "MSG_BUILD_FAIL_LOG=  完整日志见上方输出。"
    set "MSG_DONE=[6/6] 打包完成！"
    set "MSG_OUT=  生成文件: "
    set "MSG_OUT_HINT=  （单个文件，双击即运行；可复制到任意 Windows 电脑使用）"
    set "MSG_PRESS_KEY=按任意键关闭本窗口..."
) else (
    set "MSG_TITLE=OtherScope Windows Build Tool"
    set "MSG_LINE============================================================="
    set "MSG_WELCOME=   OtherScope Windows single-file build (double-click to build)"
    set "MSG_SRCDIR=   Source dir: "
    set "MSG_PY_NOT_FOUND=[Hint] No Python found. Downloading and installing Python 3.12 automatically ..."
    set "MSG_DOWNLOAD=  Downloading the official installer ..."
    set "MSG_INSTALL=  Installing Python silently (~1-2 min) ..."
    set "MSG_DL_FAIL=[ERROR] Download failed. Check your network and retry."
    set "MSG_INSTALL_FAIL=[ERROR] Install failed. Antivirus may be blocking it."
    set "MSG_PY_NOT_FOUND2=[ERROR] Python installed, but the interpreter was not found at the expected path."
    set "MSG_PY_FAIL=[ERROR] No usable Python found."
    set "MSG_PY_HINT1=  You may install Python 3.12 manually, then double-click this script again:"
    set "MSG_PY_HINT2=  Download: https://www.python.org/downloads/"
    set "MSG_USING_PY=[1/6] Using Python: "
    set "MSG_CHECK_PIP=[2/6] Checking pip ..."
    set "MSG_PIP_INSTALL=[ERROR] pip unavailable. Trying to install ..."
    set "MSG_PIP_FAIL=[ERROR] pip install failed. Screenshot the error above. Manual: python -m ensurepip --upgrade"
    set "MSG_DISK=[3/6] Checking disk space ..."
    set "MSG_DISK_FAIL=[ERROR] Not enough free disk space (need ~2.5 GB). Please free up space and retry."
    set "MSG_INSTALL_DEPS=[4/6] Installing deps (PySide6/pyqtgraph/pyserial/numpy/pyinstaller)..."
    set "MSG_MIRROR=[Hint] Default mirror failed. Retrying via mirror ..."
    set "MSG_DEPS_FAIL=[ERROR] Dependency install failed. Check your network, or run manually:"
    set "MSG_CLEAN=[5/6] Cleaning old artifacts and building (first run ~3-8 min)..."
    set "MSG_BUILD_FAIL=[ERROR] Build failed. Common causes:"
    set "MSG_BUILD_FAIL1=  - Antivirus blocked the build (temporarily disable or allow it)"
    set "MSG_BUILD_FAIL2=  - Out of memory (close other apps and retry)"
    set "MSG_BUILD_FAIL3=  - Not enough disk space"
    set "MSG_BUILD_FAIL_LOG=  See the log above for details."
    set "MSG_DONE=[6/6] Build finished!"
    set "MSG_OUT=  Output file: "
    set "MSG_OUT_HINT=  (Single file, double-click to run; copyable to any Windows PC.)"
    set "MSG_PRESS_KEY=Press any key to close this window..."
)

title !MSG_TITLE!
color 0A

REM ---------- Go back to source root (this script lives in build\) ----------
cd /d "%~dp0.."
set "ROOT=%CD%"
REM PyInstaller intermediates go to a temp dir (NOT this script's own folder), output to dist\
set "BUILD_DIR=%TEMP%\OtherScope_build"
set "DIST_DIR=%ROOT%\dist"

echo.
echo !MSG_LINE!
echo !MSG_WELCOME!
echo !MSG_SRCDIR!!ROOT!
echo !MSG_LINE!
echo.

REM ---------- 1. Prepare Python ----------
REM Find a real python.exe, skipping the Microsoft Store stub under WindowsApps
set "PY="
for /f "delims=" %%v in ('where python.exe 2^>nul') do (
    echo %%v | findstr /i /c:"WindowsApps" >nul
    if errorlevel 1 (
        set "PY=%%v"
        goto found_py
    )
)

REM No real Python found - download & silently install the official Python 3.12.7
echo !MSG_PY_NOT_FOUND!
echo.
echo !MSG_DOWNLOAD!
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%TEMP%\py_installer.exe' -UseBasicParsing"
if errorlevel 1 (
    echo !MSG_DL_FAIL!
    echo !MSG_PY_HINT1!
    echo !MSG_PY_HINT2!
    pause
    exit /b 1
)
echo !MSG_INSTALL!
"%TEMP%\py_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
if errorlevel 1 (
    echo !MSG_INSTALL_FAIL!
    echo !MSG_PY_HINT1!
    echo !MSG_PY_HINT2!
    pause
    exit /b 1
)
del "%TEMP%\py_installer.exe" >nul 2>nul

REM Resolve to the well-known per-user install path (PATH is not required)
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" (
    echo !MSG_PY_NOT_FOUND2!
    echo !MSG_PY_HINT1!
    echo !MSG_PY_HINT2!
    pause
    exit /b 1
)

:found_py
echo !MSG_USING_PY!!PY!
"%PY%" --version
if errorlevel 1 (
    echo !MSG_PY_FAIL!
    pause
    exit /b 1
)

REM ---------- 2. Check / upgrade pip ----------
echo !MSG_CHECK_PIP!
"%PY%" -m pip --version
if !errorlevel! neq 0 (
    echo !MSG_PIP_INSTALL!
    "%PY%" -m ensurepip --upgrade
    if !errorlevel! neq 0 (
        echo.
        echo !MSG_PIP_FAIL!
        pause
        exit /b 1
    )
)
"%PY%" -m pip install --upgrade pip --disable-pip-version-check -q

REM ---------- 3. Disk space (~2.5 GB needed), language-independent ----------
echo !MSG_DISK!
powershell -NoProfile -Command "$q=(Split-Path '!ROOT!' -Qualifier).TrimEnd(':'); $f=(Get-PSDrive $q).Free; if($f -lt 2684354560){exit 1}"
if errorlevel 1 (
    echo.
    echo !MSG_DISK_FAIL!
    pause
    exit /b 1
)

REM ---------- 4. Install build & runtime deps ----------
echo !MSG_INSTALL_DEPS!
"%PY%" -m pip install -r requirements.txt pyinstaller --disable-pip-version-check -q
if %errorlevel% neq 0 (
    echo !MSG_MIRROR!
    "%PY%" -m pip install -r requirements.txt pyinstaller --disable-pip-version-check -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    if !errorlevel! neq 0 (
        echo !MSG_DEPS_FAIL!
        echo   "%PY%" -m pip install -r requirements.txt pyinstaller
        pause
        exit /b 1
    )
)

REM ---------- 5. Clean old artifacts & build ----------
echo !MSG_CLEAN!
if exist "%BUILD_DIR%" rd /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\OtherScope.exe" del /f /q "%DIST_DIR%\OtherScope.exe"

"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name OtherScope --paths "%ROOT%" --workpath "%BUILD_DIR%" --distpath "%DIST_DIR%" main.py
if %errorlevel% neq 0 (
    echo.
    echo !MSG_BUILD_FAIL!
    echo !MSG_BUILD_FAIL1!
    echo !MSG_BUILD_FAIL2!
    echo !MSG_BUILD_FAIL3!
    echo !MSG_BUILD_FAIL_LOG!
    pause
    exit /b 1
)

REM ---------- 6. Done ----------
echo.
echo !MSG_LINE!
echo  !MSG_DONE!
echo  !MSG_OUT!!DIST_DIR%\OtherScope.exe
echo  !MSG_OUT_HINT!
echo !MSG_LINE!
echo.
if exist "%DIST_DIR%\OtherScope.exe" (
    start "" explorer /select,"%DIST_DIR%\OtherScope.exe"
)
echo !MSG_PRESS_KEY!
pause >nul
endlocal
exit /b 0
