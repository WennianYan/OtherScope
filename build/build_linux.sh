#!/usr/bin/env bash
# ============================================================
#  OtherScope Linux 单文件打包脚本（一键）
#  双击运行（或 ./build/build_linux.sh）即可：自动检测环境 ->
#  自动安装依赖与系统运行库 -> 打包生成 dist/OtherScope 单文件
#  （chmod +x OtherScope && ./OtherScope 即运行）。
#  覆盖处理所有能想到的异常/依赖：Python 缺失、pip 不可用、
#  系统 Qt 库缺失、无 sudo 权限、网络失败、磁盘不足等。
# ============================================================
set -u
# 不 set -e：各步骤自行判断并给出明确指引

# ---------- 定位源码根目录（脚本位于 build/ 子目录） ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}" || { echo "[错误] 无法进入源码目录"; exit 1; }

CYAN='\033[0;36m'; GREEN='\033[0;32m'; RED='\033[1;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[OtherScope]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[警告]${NC} $*"; }
fail()  { echo -e "${RED}[错误]${NC} $*"; }

echo
info "================================================"
info " OtherScope Linux 单文件打包（双击即打包）"
info " 源码目录: ${ROOT_DIR}"
info "================================================"
echo

# ---------- 1. 检查 Python ----------
PY=""
if command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
fi
if [ -z "${PY}" ]; then
    fail "未检测到 Python3。尝试自动安装..."
    if command -v apt-get >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv || true
    elif command -v dnf >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
        sudo dnf install -y -q python3 python3-pip || true
    fi
    if command -v python3 >/dev/null 2>&1; then PY="python3"
    else
        fail "Python 自动安装失败。请手动安装 Python 3.9+ 后重试："
        echo "  sudo apt-get install -y python3 python3-pip python3-venv"
        echo "（或 Ubuntu 官方: https://www.python.org/downloads/）"
        exit 1
    fi
fi
info "使用 Python: ${PY} ($(${PY} --version 2>&1))"

# ---------- 2. 检查系统 Qt 运行库（缺失时自动安装） ----------
info "检查系统 Qt 运行库..."
MISSING_LIBS=()
for so in libGL.so.1 libEGL.so.1 libxkbcommon-x11.so.0 libxcb-cursor.so.0; do
    ldconfig -p 2>/dev/null | grep -q "${so}" || MISSING_LIBS+=("${so}")
done
if [ ${#MISSING_LIBS[@]} -gt 0 ]; then
    warn "缺失系统运行库: ${MISSING_LIBS[*]}，尝试自动安装..."
    if command -v apt-get >/dev/null 2>&1; then
        if sudo -n true >/dev/null 2>&1; then
            sudo apt-get update -qq
            sudo apt-get install -y -qq libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 || true
        else
            warn "无 sudo 权限，无法自动安装系统库。"
            warn "请手动执行: sudo apt-get install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0"
        fi
    elif command -v dnf >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
        sudo dnf install -y -q mesa-libGL mesa-libEGL libxkbcommon-x11 libxcb-cursor || true
    fi
fi

# ---------- 3. 创建虚拟环境并安装依赖 ----------
VENV_DIR="${ROOT_DIR}/.build_venv"
info "创建隔离构建环境 ${VENV_DIR} ..."
if [ ! -d "${VENV_DIR}/bin" ]; then
    "${PY}" -m venv "${VENV_DIR}" 2>/dev/null || true
fi
if [ ! -x "${VENV_DIR}/bin/python" ]; then
    warn "venv 创建失败（可能缺 python3-venv），改用 --user 安装方式。"
    VENV_PY="${PY}"
    VENV_PIP="${PY} -m pip"
else
    VENV_PY="${VENV_DIR}/bin/python"
    VENV_PIP="${VENV_DIR}/bin/pip"
fi
"${VENV_PIP}" install --upgrade pip -q 2>/dev/null || true

info "安装依赖（PySide6/pyqtgraph/pyserial/numpy/pyinstaller）..."
if ! "${VENV_PIP}" install -r requirements.txt pyinstaller -q 2>/dev/null; then
    warn "默认源安装失败，切换清华镜像重试..."
    if ! "${VENV_PIP}" install -r requirements.txt pyinstaller -q -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null; then
        fail "依赖安装失败。请检查网络后重试，或手动执行："
        echo "  ${VENV_PIP} install -r requirements.txt pyinstaller"
        exit 1
    fi
fi
ok "依赖安装完成"

# ---------- 4. 磁盘空间检查 ----------
FREE_KB=$(df -Pk "${ROOT_DIR}" | awk 'NR==2{print $4}')
FREE_MB=$(( FREE_KB / 1024 ))
if [ "${FREE_MB}" -lt 2500 ]; then
    fail "磁盘空间不足（约 ${FREE_MB} MB，需约 2560 MB）。请清理后重试。"
    exit 1
fi

# ---------- 5. 清理旧产物并打包 ----------
info "清理旧产物并开始打包（首次约 2~5 分钟）..."
rm -rf "${ROOT_DIR}/build/pyi_build" "${ROOT_DIR}/build/pyi_cache" 2>/dev/null || true
if [ -f "${ROOT_DIR}/dist/OtherScope" ]; then rm -f "${ROOT_DIR}/dist/OtherScope"; fi

if ! "${VENV_PY}" -m PyInstaller --noconfirm --clean --onefile --windowed \
        --name OtherScope --distpath "${ROOT_DIR}/dist" \
        --workpath "${ROOT_DIR}/build/pyi_build" \
        --specpath "${ROOT_DIR}/build" \
        --paths "${ROOT_DIR}" main.py; then
    fail "打包失败。可能原因：内存不足 / 磁盘不足 / 网络。完整日志见上方输出。"
    exit 1
fi

# ---------- 6. 完成 ----------
echo
info "================================================"
info " 打包完成！生成文件: ${ROOT_DIR}/dist/OtherScope"
info " 使用:  chmod +x ${ROOT_DIR}/dist/OtherScope && ${ROOT_DIR}/dist/OtherScope"
info "================================================"
chmod +x "${ROOT_DIR}/dist/OtherScope" 2>/dev/null || true
# 图形桌面下尝试自动打开所在目录
if [ -n "${DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${ROOT_DIR}/dist" >/dev/null 2>&1 || true
fi
exit 0
