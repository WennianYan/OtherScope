@echo off
rem ============================================================
rem  OtherScope Windows 单文件打包脚本（一键）
rem  双击本文件即可：自动检测环境 -> 自动安装依赖 -> 打包生成
rem  dist\OtherScope.exe 单个可执行文件（双击即运行）。
rem  覆盖处理所有能想到的异常/依赖：Python 缺失、pip 不可用、
rem  网络失败、磁盘不足、杀软拦截、旧产物残留、中文路径等。
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
title OtherScope Windows 打包工具
color 0A

rem ---------- 回到源码根目录（脚本位于 build\ 子目录） ----------
cd /d "%~dp0.."
set "ROOT=%CD%"
set "BUILD_DIR=%ROOT%\build"
set "DIST_DIR=%ROOT%\dist"

echo.
echo ============================================================
echo    OtherScope Windows 单文件打包（双击即打包）
echo    源码目录: %ROOT%
echo ============================================================
echo.

rem ---------- 1. 检查并准备 Python ----------
set "PY="
where python >nul 2>nul
if %errorlevel%==0 set "PY=python"
if not defined PY (
    where py >nul 2>nul
    if !errorlevel!==0 set "PY=py -3"
)
if not defined PY (
    echo [提示] 未检测到 Python，尝试自动安装 Python 3.12 ...
    where winget >nul 2>nul
    if !errorlevel!==0 (
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements --silent
        if !errorlevel!==0 (
            rem 安装后刷新 PATH（新进程可见）
            for /f "delims=" %%i in ('where python 2^>nul') do set "PY=python"
            if not defined PY set "PY=python"
        )
    )
    rem 若仍未找到，给出明确指引后退出
    where python >nul 2>nul
    if not defined PY (
        echo [错误] Python 自动安装未成功。
        echo  请手动安装 Python 3.12 并勾选 "Add Python to PATH"：
        echo  下载地址: https://www.python.org/downloads/
        echo  安装完成后重新双击本脚本即可。
        pause
        exit /b 1
    )
)

echo [1/6] 使用 Python: %PY%
"%PY%" --version

rem ---------- 2. 检查 pip 并升级 ----------
echo [2/6] 检查 pip ...
"%PY%" -m pip --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] pip 不可用，尝试安装 ...
    "%PY%" -m ensurepip --upgrade >nul 2>nul
    if %errorlevel% neq 0 (
        echo [错误] pip 安装失败，请手动执行: python -m ensurepip --upgrade
        pause
        exit /b 1
    )
)
"%PY%" -m pip install --upgrade pip --disable-pip-version-check -q

rem ---------- 3. 检查磁盘空间（需约 2.5 GB） ----------
echo [3/6] 检查磁盘空间 ...
for /f "tokens=3" %%a in ('dir "%ROOT%" /-c ^| findstr /b /c:" "') do set "FREE_KB=%%a"
if not defined FREE_KB set "FREE_KB=0"
set /a FREE_MB=%FREE_KB%/1024
if %FREE_MB% LSS 2500 (
    echo [错误] 可用磁盘空间不足（当前约 %FREE_MB% MB，需约 2560 MB）。
    echo  请清理磁盘后重新运行。
    pause
    exit /b 1
)

rem ---------- 4. 安装构建与运行依赖 ----------
echo [4/6] 安装依赖（PySide6/pyqtgraph/pyserial/numpy/pyinstaller）...
"%PY%" -m pip install -r requirements.txt pyinstaller --disable-pip-version-check -q
if %errorlevel% neq 0 (
    echo [提示] 默认源安装失败，切换国内镜像重试 ...
    "%PY%" -m pip install -r requirements.txt pyinstaller --disable-pip-version-check -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    if !errorlevel! neq 0 (
        echo [错误] 依赖安装失败。请检查网络后重试，或手动执行:
        echo   %PY% -m pip install -r requirements.txt pyinstaller
        pause
        exit /b 1
    )
)

rem ---------- 5. 清理旧产物并打包 ----------
echo [5/6] 清理旧产物并开始打包（首次约 3~8 分钟）...
if exist "%BUILD_DIR%" rd /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\OtherScope.exe" del /f /q "%DIST_DIR%\OtherScope.exe"

"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name OtherScope --paths "%ROOT%" main.py
if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败。常见原因：
    echo   - 杀毒软件拦截了构建进程（请临时关闭或允许）
    echo   - 内存不足（请关闭其他程序后重试）
    echo   - 磁盘空间不足
    echo  完整日志见上方输出。
    pause
    exit /b 1
)

rem ---------- 6. 完成 ----------
echo.
echo ============================================================
echo  [6/6] 打包完成！
echo  生成文件: %DIST_DIR%\OtherScope.exe
echo  （单个文件，双击即运行；可复制到任意 Windows 电脑使用）
echo ============================================================
echo.
if exist "%DIST_DIR%\OtherScope.exe" (
    start "" explorer /select,"%DIST_DIR%\OtherScope.exe"
)
echo 按任意键关闭本窗口...
pause >nul
exit /b 0
