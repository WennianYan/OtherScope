#!/bin/bash
# ============================================================
#  OtherScope macOS 单文件打包脚本
#  双击本文件（.command）即自动在终端运行：自动检测环境 ->
#  自动安装依赖 -> 打包生成 dist/OtherScope.app（双击即运行）。
#  覆盖处理所有能想到的异常/依赖：Python 缺失、无 pip、
#  Xcode CLT 缺失、Homebrew 缺失、网络失败、磁盘不足等。
#  提示随系统语言：中文系统->中文，其余->英文。
# ============================================================

# ---------- 语言检测：中文(zh*) -> 中文，否则英文 ----------
_LANG_RAW="${LC_ALL:-${LC_MESSAGES:-${LANG:-C}}}"
case "$_LANG_RAW" in
    zh*|zh_*) IS_ZH=1 ;;
    *) IS_ZH=0 ;;
esac
if [ "$IS_ZH" = "1" ]; then
    T_ERR="[错误]"; T_OK="[OK]"; T_WARN="[警告]"
    M_NO_SRCDIR="无法进入源码目录"
    M_PRESS="按回车关闭..."
    M_BANNER=" OtherScope macOS 单文件打包（双击即打包）"
    M_SRCDIR=" 源码目录: "
    M_XCODE="未检测到 Xcode 命令行工具，正在引导安装..."
    M_XCODE_HINT="请在弹出的窗口中点击【安装】，完成后重新双击本脚本。"
    M_PY_MISS="未检测到 Python3。尝试通过 Homebrew 安装..."
    M_BREW_MISS="未检测到 Homebrew，正在安装（约需几分钟）..."
    M_PY_FAIL="Python 自动安装失败。请手动安装 Python 3.12："
    M_PY_FAIL2="或: brew install python@3.12"
    M_USING_PY="使用 Python: "
    M_VENV="创建隔离构建环境 "
    M_VENV_FALLBACK="venv 不可用，改用 --user 安装方式。"
    M_DEPS="安装依赖（PySide6/pyqtgraph/pyserial/numpy/pyinstaller）..."
    M_MIRROR="默认源安装失败，切换国内镜像重试..."
    M_DEPS_FAIL="依赖安装失败。请检查网络后重试，或手动执行："
    M_DEPS_OK="依赖安装完成"
    M_DISK_FAIL="磁盘空间不足（需约 2.5 GB）。请清理后重试。"
    M_CLEAN="清理旧产物并开始打包（首次约 2~5 分钟）..."
    M_BUILD_FAIL="打包失败。可能原因：内存不足 / 磁盘不足 / 网络。完整日志见上方输出。"
    M_DONE=" 打包完成！生成应用: "
    M_DONE_HINT=" 双击 OtherScope.app 即可运行"
else
    T_ERR="[ERROR]"; T_OK="[OK]"; T_WARN="[WARN]"
    M_NO_SRCDIR="cannot enter source directory"
    M_PRESS="Press Enter to close..."
    M_BANNER=" OtherScope macOS single-file build (double-click to build)"
    M_SRCDIR=" Source dir: "
    M_XCODE="Xcode Command Line Tools not found, prompting to install..."
    M_XCODE_HINT="Click [Install] in the popup, then double-click this script again."
    M_PY_MISS="No Python3 found. Installing via Homebrew..."
    M_BREW_MISS="Homebrew not found, installing (may take a few minutes)..."
    M_PY_FAIL="Python auto-install failed. Install Python 3.12 manually:"
    M_PY_FAIL2="or: brew install python@3.12"
    M_USING_PY="Using Python: "
    M_VENV="Creating isolated build env "
    M_VENV_FALLBACK="venv unavailable, falling back to --user."
    M_DEPS="Installing deps (PySide6/pyqtgraph/pyserial/numpy/pyinstaller)..."
    M_MIRROR="Default mirror failed, retrying via mirror..."
    M_DEPS_FAIL="Deps install failed. Check network, or run manually:"
    M_DEPS_OK="Deps installed."
    M_DISK_FAIL="Not enough disk space (need ~2.5 GB). Free up space and retry."
    M_CLEAN="Cleaning old artifacts and building (first run ~2-5 min)..."
    M_BUILD_FAIL="Build failed. Causes: memory / disk / network. See log above."
    M_DONE=" Build done! App: "
    M_DONE_HINT=" Double-click OtherScope.app to run"
fi

# ---------- 定位源码根目录（脚本位于 build/ 子目录） ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}" || { echo "${T_ERR} ${M_NO_SRCDIR}"; read -r -p "$M_PRESS"; exit 1; }

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[1;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[OtherScope]${NC} $*"; }
ok()    { echo -e "${GREEN}${T_OK}${NC} $*"; }
warn()  { echo -e "${YELLOW}${T_WARN}${NC} $*"; }
fail()  { echo -e "${RED}${T_ERR}${NC} $*"; }

echo
info "================================================"
info "$M_BANNER"
info "$M_SRCDIR${ROOT_DIR}"
info "================================================"
echo

# ---------- 1. 检查 Xcode 命令行工具（macOS 开发必需） ----------
if ! xcode-select -p >/dev/null 2>&1; then
    info "$M_XCODE"
    xcode-select --install 2>/dev/null || true
    warn "$M_XCODE_HINT"
    read -r -p "$M_PRESS"
    exit 1
fi

# ---------- 2. 检查 Python ----------
PY=""
for cand in python3 python; do
    if command -v "${cand}" >/dev/null 2>&1; then PY="${cand}"; break; fi
done
if [ -z "${PY}" ]; then
    info "$M_PY_MISS"
    if ! command -v brew >/dev/null 2>&1; then
        warn "$M_BREW_MISS"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" 2>/dev/null || true
    fi
    if command -v brew >/dev/null 2>&1; then
        brew install python@3.12 2>/dev/null || true
    fi
    if command -v python3 >/dev/null 2>&1; then PY="python3"; fi
fi
if [ -z "${PY}" ]; then
    fail "$M_PY_FAIL"
    echo "  官方下载: https://www.python.org/downloads/"
    echo "  $M_PY_FAIL2"
    read -r -p "$M_PRESS"
    exit 1
fi
info "$M_USING_PY${PY} ($(${PY} --version 2>&1))"

# ---------- 3. 准备 pip ----------
"${PY}" -m pip --version >/dev/null 2>&1 || "${PY}" -m ensurepip --upgrade >/dev/null 2>&1 || true
"${PY}" -m pip install --upgrade pip -q 2>/dev/null || true

# ---------- 4. 创建隔离环境并安装依赖 ----------
VENV_DIR="${ROOT_DIR}/.build_venv"
info "$M_VENV${VENV_DIR} ..."
"${PY}" -m venv "${VENV_DIR}" 2>/dev/null || true
if [ -x "${VENV_DIR}/bin/python" ]; then
    VENV_PIP="${VENV_DIR}/bin/pip"
else
    warn "$M_VENV_FALLBACK"
    VENV_PIP="${PY} -m pip --user"
fi
"${VENV_PIP}" install --upgrade pip -q 2>/dev/null || true

info "$M_DEPS"
if ! "${VENV_PIP}" install -r requirements.txt pyinstaller -q 2>/dev/null; then
    warn "$M_MIRROR"
    if ! "${VENV_PIP}" install -r requirements.txt pyinstaller -q -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null; then
        fail "$M_DEPS_FAIL"
        echo "  ${VENV_PIP} install -r requirements.txt pyinstaller"
        read -r -p "$M_PRESS"
        exit 1
    fi
fi
ok "$M_DEPS_OK"

# ---------- 5. 磁盘空间检查 ----------
FREE_KB=$(df -Pk "${ROOT_DIR}" | awk 'NR==2{print $4}')
FREE_MB=$(( FREE_KB / 1024 ))
if [ "${FREE_MB}" -lt 2500 ]; then
    fail "$M_DISK_FAIL"
    read -r -p "$M_PRESS"
    exit 1
fi

# ---------- 6. 清理旧产物并打包 ----------
info "$M_CLEAN"
rm -rf "${ROOT_DIR}/build/pyi_build" "${ROOT_DIR}/build/pyi_cache" 2>/dev/null || true
if [ -d "${ROOT_DIR}/dist/OtherScope.app" ]; then rm -rf "${ROOT_DIR}/dist/OtherScope.app"; fi

if ! "${VENV_PIP}" runpy -m PyInstaller --noconfirm --clean --onefile --windowed \
        --name OtherScope --distpath "${ROOT_DIR}/dist" \
        --workpath "${ROOT_DIR}/build/pyi_build" \
        --specpath "${ROOT_DIR}/build" \
        --paths "${ROOT_DIR}" main.py 2>/dev/null; then
    # 上一条为兼容 --user 下的 runpy；失败则回退到直接模块调用
    if ! "${VENV_PIP}" install -q -e . 2>/dev/null; then :; fi
    if ! "${PY}" -m PyInstaller --noconfirm --clean --onefile --windowed \
            --name OtherScope --distpath "${ROOT_DIR}/dist" \
            --workpath "${ROOT_DIR}/build/pyi_build" \
            --specpath "${ROOT_DIR}/build" \
            --paths "${ROOT_DIR}" main.py; then
        fail "$M_BUILD_FAIL"
        read -r -p "$M_PRESS"
        exit 1
    fi
fi

# ---------- 7. 完成 ----------
echo
info "================================================"
info "$M_DONE${ROOT_DIR}/dist/OtherScope.app"
info "$M_DONE_HINT"
info "================================================"
open "${ROOT_DIR}/dist" 2>/dev/null || true
exit 0
