#!/bin/bash
# ============================================================
#  OtherScope macOS 单文件打包脚本（一键）
#  双击本文件（.command）即自动在终端运行：自动检测环境 ->
#  自动安装依赖 -> 打包生成 dist/OtherScope.app（双击即运行）。
#  覆盖处理所有能想到的异常/依赖：Python 缺失、无 pip、
#  Xcode CLT 缺失、Homebrew 缺失、网络失败、磁盘不足等。
# ============================================================

# ---------- 定位源码根目录（脚本位于 build/ 子目录） ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}" || { echo "[错误] 无法进入源码目录"; read -r -p "按回车关闭..."; exit 1; }

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[1;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[OtherScope]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[警告]${NC} $*"; }
fail()  { echo -e "${RED}[错误]${NC} $*"; }

echo
info "================================================"
info " OtherScope macOS 单文件打包（双击即打包）"
info " 源码目录: ${ROOT_DIR}"
info "================================================"
echo

# ---------- 1. 检查 Xcode 命令行工具（macOS 开发必需） ----------
if ! xcode-select -p >/dev/null 2>&1; then
    info "未检测到 Xcode 命令行工具，正在引导安装..."
    xcode-select --install 2>/dev/null || true
    warn "请在弹出的窗口中点击【安装】，完成后重新双击本脚本。"
    read -r -p "按回车关闭..."
    exit 1
fi

# ---------- 2. 检查 Python ----------
PY=""
for cand in python3 python; do
    if command -v "${cand}" >/dev/null 2>&1; then PY="${cand}"; break; fi
done
if [ -z "${PY}" ]; then
    info "未检测到 Python3。尝试通过 Homebrew 安装..."
    if ! command -v brew >/dev/null 2>&1; then
        warn "未检测到 Homebrew，正在安装（约需几分钟）..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" 2>/dev/null || true
    fi
    if command -v brew >/dev/null 2>&1; then
        brew install python@3.12 2>/dev/null || true
    fi
    if command -v python3 >/dev/null 2>&1; then PY="python3"; fi
fi
if [ -z "${PY}" ]; then
    fail "Python 自动安装失败。请手动安装 Python 3.12："
    echo "  官方下载: https://www.python.org/downloads/"
    echo "  或: brew install python@3.12"
    read -r -p "按回车关闭..."
    exit 1
fi
info "使用 Python: ${PY} ($(${PY} --version 2>&1))"

# ---------- 3. 准备 pip ----------
"${PY}" -m pip --version >/dev/null 2>&1 || "${PY}" -m ensurepip --upgrade >/dev/null 2>&1 || true
"${PY}" -m pip install --upgrade pip -q 2>/dev/null || true

# ---------- 4. 创建隔离环境并安装依赖 ----------
VENV_DIR="${ROOT_DIR}/.build_venv"
info "创建隔离构建环境 ${VENV_DIR} ..."
"${PY}" -m venv "${VENV_DIR}" 2>/dev/null || true
if [ -x "${VENV_DIR}/bin/python" ]; then
    VENV_PIP="${VENV_DIR}/bin/pip"
else
    warn "venv 不可用，改用 --user 安装方式。"
    VENV_PIP="${PY} -m pip --user"
fi
"${VENV_PIP}" install --upgrade pip -q 2>/dev/null || true

info "安装依赖（PySide6/pyqtgraph/pyserial/numpy/pyinstaller）..."
if ! "${VENV_PIP}" install -r requirements.txt pyinstaller -q 2>/dev/null; then
    warn "默认源安装失败，切换清华镜像重试..."
    if ! "${VENV_PIP}" install -r requirements.txt pyinstaller -q -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null; then
        fail "依赖安装失败。请检查网络后重试，或手动执行："
        echo "  ${VENV_PIP} install -r requirements.txt pyinstaller"
        read -r -p "按回车关闭..."
        exit 1
    fi
fi
ok "依赖安装完成"

# ---------- 5. 磁盘空间检查 ----------
FREE_KB=$(df -Pk "${ROOT_DIR}" | awk 'NR==2{print $4}')
FREE_MB=$(( FREE_KB / 1024 ))
if [ "${FREE_MB}" -lt 2500 ]; then
    fail "磁盘空间不足（约 ${FREE_MB} MB，需约 2560 MB）。请清理后重试。"
    read -r -p "按回车关闭..."
    exit 1
fi

# ---------- 6. 清理旧产物并打包 ----------
info "清理旧产物并开始打包（首次约 2~5 分钟）..."
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
        fail "打包失败。可能原因：内存不足 / 磁盘不足 / 网络。完整日志见上方输出。"
        read -r -p "按回车关闭..."
        exit 1
    fi
fi

# ---------- 7. 完成 ----------
echo
info "================================================"
info " 打包完成！生成应用: ${ROOT_DIR}/dist/OtherScope.app"
info " 双击 OtherScope.app 即可运行"
info "================================================"
open "${ROOT_DIR}/dist" 2>/dev/null || true
exit 0
