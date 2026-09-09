#!/usr/bin/env bash
# ============================================================
#   OtherScope - Linux Auto Launcher (Hardened v8)
#   - Python version check (>=3.9), pip availability check
#   - Auto-install Python via apt/dnf/pacman/zypper
#   - Qt system lib detection + auto-install + ldconfig refresh
#   - Wayland fallback to xcb; no-DISPLAY warning
#   - Disk space check, sudo guidance, detailed error messages
# ============================================================
set -u

# ---- i18n: detect system language ----
_DETECT_LANG() {
    for _v in LANGUAGE LC_ALL LC_MESSAGES LANG; do
        eval "_val=\${$_v:-}"
        if [ -n "${_val:-}" ]; then
            case "${_val}" in
                zh*|Chinese*) echo "zh"; return ;;
            esac
            echo "en"; return
        fi
    done
    echo "en"
}
SYS_LANG="$(_DETECT_LANG)"

# _t "Chinese" "English" -> outputs based on SYS_LANG
_t() {
    if [ "${SYS_LANG}" = "zh" ]; then
        echo "$1"
    else
        echo "$2"
    fi
}

# ---- 初始化所有全局变量（防止 set -u 下未定义变量闪退）----
PY=""
PY_VER=""
PKG_MANAGER=""
SUDO_CMD=""
LAUNCH_EXIT=1
FREE_KB=0

# ---- 信号 trap：任何中断都不闪退，显示信息并等待 ----
_on_interrupt() {
    echo ""
    echo "[OtherScope] $(_t "[INFO] 已中断，正在清理..." "[INFO] Interrupted. Cleaning up...")"
    echo
    read -r -p "$(_t "按回车键关闭..." "Press Enter to close...")" 2>/dev/null || true
    exit 130
}
trap '_on_interrupt' INT TERM HUP


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || { echo "[FATAL] Cannot enter script directory: ${SCRIPT_DIR}"; read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')" 2>/dev/null || true; exit 1; }

info()  { echo "[OtherScope] $*"; }
ok()    { echo "[OtherScope] [OK] $*"; }
warn()  { echo "[OtherScope] [WARN] $*"; }
fail()  { echo "[OtherScope] [ERROR] $*"; }

echo
info "================================================================"
info "  $(_t "OtherScope - Linux 全自动启动器" "OtherScope - Linux Auto Launcher")"
info "  $(_t "工作目录" "Workdir"): ${SCRIPT_DIR}"
info "================================================================"
echo

# ---- Pre-flight: auto_launcher.py exists ----
if [ ! -f "${SCRIPT_DIR}/auto_launcher.py" ]; then
    fail "$(_t "auto_launcher.py 未找到" "auto_launcher.py not found"): ${SCRIPT_DIR}"
    echo "  $(_t "请确保所有文件在同一目录下。" "Make sure all files are in the same folder.")"
    echo
    read -r -p "$(_t "按回车键关闭..." "Press Enter to close...")"
    exit 1
fi

# ---- Step 1: Find working Python >=3.9 ----
PY=""
PY_VER=""
find_python() {
    PY=""
    PY_VER=""
    local candidate out major minor
    for candidate in python3 python; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            out="$("${candidate}" --version 2>&1)"
            if echo "${out}" | grep -q '^Python [0-9]'; then
                major="$(echo "${out}" | awk '{print $2}' | cut -d. -f1)"
                minor="$(echo "${out}" | awk '{print $2}' | cut -d. -f2)"
                if [ "${major}" -ge 3 ] && { [ "${major}" -gt 3 ] || [ "${minor}" -ge 9 ]; }; then
                    PY="${candidate}"
                    PY_VER="${out}"
                    return 0
                else
                    warn "Found ${out} but need >=3.9. Will try to install newer version."
                fi
            fi
        fi
    done
    return 1
}

find_python
if [ -n "${PY}" ]; then
    ok "$(_t '[步骤 1/4] 找到 Python: ' '[Step 1/4] Python found: ')${PY_VER}"
else
    info "$(_t '[步骤 1/4] 未找到可用 Python (>=3.9)，正在自动安装...' '[Step 1/4] No working Python (>=3.9) found. Auto-installing...')"
    echo

    # Disk space check
    FREE_KB="$(df -k / | awk 'NR==2 {print $4}' 2>/dev/null || echo 0)"
    FREE_KB="${FREE_KB:-0}"
    case "${FREE_KB}" in *[!0-9]*) FREE_KB=0 ;; esac
    if [ -n "${FREE_KB:-0}" ] && [ "${FREE_KB:-0}" -lt 500000 ]; then
        fail "$(_t '磁盘空间不足（约 $((FREE_KB/1024)) MB，需要约 500MB）。' 'Not enough disk space (~$((FREE_KB/1024)) MB free, need ~500MB).')"
        echo "  $(_t '请清理磁盘空间后重新运行。' 'Please free up disk space and re-run.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi

    # Detect package manager and install
    PKG_MANAGER=""
    if command -v apt-get >/dev/null 2>&1; then
        PKG_MANAGER="apt-get"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MANAGER="pacman"
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MANAGER="zypper"
    fi

    if [ -z "${PKG_MANAGER}" ]; then
        fail "$(_t '未找到支持的包管理器（apt-get/dnf/pacman/zypper）。' 'No supported package manager found (apt-get/dnf/pacman/zypper).')"
        echo "  $(_t '请手动安装 Python 3.9+ 后重新运行。' 'Please install Python 3.9+ manually, then re-run.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi

    # Check passwordless sudo
    SUDO_CMD=""
    if [ "$(id -u 2>/dev/null || echo 0)" -eq 0 ]; then
        SUDO_CMD=""
    elif sudo -n true 2>/dev/null; then
        SUDO_CMD="sudo"
    else
        fail "$(_t '无法自动安装 Python：无免密 sudo 权限。' 'Cannot auto-install Python: no passwordless sudo.')"
        echo "  $(_t '请手动执行以下命令之一，然后重新运行此脚本：' 'Please run one of the following commands manually, then re-run this script:')"
        echo
        case "${PKG_MANAGER}" in
            apt-get) echo "    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv" ;;
            dnf)     echo "    sudo dnf install -y python3 python3-pip" ;;
            pacman)  echo "    sudo pacman -S --noconfirm python python-pip" ;;
            zypper)  echo "    sudo zypper install -y python3 python3-pip" ;;
        esac
        echo
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi

    info "$(_t '正在通过 ${PKG_MANAGER} 安装 Python（可能需要 1-3 分钟）...' 'Installing Python via ${PKG_MANAGER} (this may take 1-3 minutes)...')"
    case "${PKG_MANAGER}" in
        apt-get)
            ${SUDO_CMD} apt-get update -qq 2>&1 | tail -3 || true
            ${SUDO_CMD} apt-get install -y -qq python3 python3-pip python3-venv 2>&1 | tail -5 || true
            ;;
        dnf)
            ${SUDO_CMD} dnf install -y python3 python3-pip 2>&1 | tail -5 || true
            ;;
        pacman)
            ${SUDO_CMD} pacman -S --noconfirm python python-pip 2>&1 | tail -5 || true
            ;;
        zypper)
            ${SUDO_CMD} zypper install -y python3 python3-pip 2>&1 | tail -5 || true
            ;;
    esac

    hash -r 2>/dev/null || true || true
    find_python
    if [ -n "${PY}" ]; then
        ok "$(_t '[步骤 1/4] Python 已安装: ' '[Step 1/4] Python installed: ')${PY_VER}"
    else
        fail "$(_t 'Python 安装完成，但仍无法找到可用的 Python >=3.9。' 'Python installation completed but still cannot find working Python >=3.9.')"
        echo "  Please install Python 3.9+ manually and re-run."
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi
fi
echo "          Path: $(command -v "${PY}" 2>/dev/null || echo "${PY}")"
echo

# ---- Step 1b: Verify pip ----
info "$(_t '[步骤 1b/4] 检查 pip...' '[Step 1b/4] Checking pip...')"
if ! "${PY}" -m pip --version >/dev/null 2>&1; then
    warn "$(_t 'pip 不可用，尝试 ensurepip...' 'pip not available. Attempting ensurepip...')"
    if ! "${PY}" -m ensurepip --upgrade >/dev/null 2>&1; then
        fail "$(_t 'ensurepip 失败，pip 不可用。' 'ensurepip failed. pip is unavailable.')"
        echo "  $(_t '请手动安装 pip（例如 sudo apt-get install python3-pip）。' 'Please install pip manually (e.g. sudo apt-get install python3-pip).')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi
fi
"${PY}" -m pip --version 2>&1 | sed 's/^/          /'
echo

# ---- Step 2: Check Qt system libs ----
info "$(_t '[步骤 2/4] 检查系统 Qt 运行库...' '[Step 2/4] Checking system Qt runtime libraries...')"

REQUIRED_LIBS=(
    "libGL.so.1"
    "libEGL.so.1"
    "libxkbcommon-x11.so.0"
    "libxkbcommon.so.0"
    "libxcb-cursor.so.0"
    "libxcb-icccm.so.4"
    "libxcb-image.so.0"
    "libxcb-keysyms.so.1"
    "libxcb-randr.so.0"
    "libxcb-render-util.so.0"
    "libxcb-shape.so.0"
    "libxcb-xinerama.so.0"
)

MISSING_LIBS=()
if command -v ldconfig >/dev/null 2>&1; then
    for so in "${REQUIRED_LIBS[@]}"; do
        if ! ldconfig -p 2>/dev/null | grep -q "${so}"; then
            MISSING_LIBS+=("${so}")
        fi
    done
else
    warn "$(_t '未找到 ldconfig，跳过系统库检查。' 'ldconfig not found; skipping system lib check.')"
fi

if [ ${#MISSING_LIBS[@]} -gt 0 ]; then
    warn "$(_t '缺少系统库: ' 'Missing system libs: ')${MISSING_LIBS[*]}"

    # Try auto-install if we have a package manager and sudo
    CAN_INSTALL=0
    if [ "$(id -u 2>/dev/null || echo 0)" -eq 0 ] || sudo -n true 2>/dev/null; then
        CAN_INSTALL=1
    fi

    if [ "${CAN_INSTALL}" -eq 1 ] && [ -n "${PKG_MANAGER:-}" ]; then
        SUDO_CMD=""
        [ "$(id -u 2>/dev/null || echo 0)" -ne 0 ] && SUDO_CMD="sudo"
        info "$(_t '正在通过 ${PKG_MANAGER} 自动安装缺失的系统库...' 'Auto-installing missing system libs via ${PKG_MANAGER}...')"
        case "${PKG_MANAGER}" in
            apt-get)
                ${SUDO_CMD} apt-get install -y -qq \
                    libgl1 libegl1 libxkbcommon-x11-0 libxkbcommon0 \
                    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
                    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 2>&1 | tail -5 || true
                ;;
            dnf)
                ${SUDO_CMD} dnf install -y \
                    mesa-libGL mesa-libEGL libxkbcommon-x11 libxkbcommon \
                    libxcb-cursor libxcb-icccm libxcb-image libxcb-keysyms \
                    libxcb-randr libxcb-render-util libxcb-shape libxcb-xinerama 2>&1 | tail -5 || true
                ;;
            pacman)
                ${SUDO_CMD} pacman -S --noconfirm \
                    mesa libxkbcommon xcb-util-cursor xcb-util-icccm \
                    xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm 2>&1 | tail -5 || true
                ;;
            zypper)
                ${SUDO_CMD} zypper install -y \
                    Mesa-libGL1 Mesa-libEGL1 libxkbcommon-x11-0 libxkbcommon0 \
                    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 2>&1 | tail -5 || true
                ;;
        esac
        # Refresh ldconfig cache
        ${SUDO_CMD} ldconfig 2>/dev/null || true
        hash -r 2>/dev/null || true || true

        # Re-check
        STILL_MISSING=()
        for so in "${MISSING_LIBS[@]}"; do
            if ! ldconfig -p 2>/dev/null | grep -q "${so}"; then
                STILL_MISSING+=("${so}")
            fi
        done
        if [ ${#STILL_MISSING[@]} -gt 0 ]; then
            warn "$(_t '安装后仍缺失: ' 'Still missing after install: ')${STILL_MISSING[*]}"
            warn "$(_t 'GUI 可能启动失败，继续运行...' 'GUI may fail to start. Continuing anyway...')"
        else
            ok "$(_t '所有系统库已安装。' 'All system libs now present.')"
        fi
    else
        warn "$(_t '无法自动安装（无支持的包管理器或无免密 sudo）。' 'Cannot auto-install (no supported package manager or no passwordless sudo).')"
        echo "  $(_t '请手动安装以下库，然后重新运行：' 'Please install the following libraries manually, then re-run:')"
        echo
        echo "    Debian/Ubuntu: sudo apt-get install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0"
        echo "    Fedora/RHEL:   sudo dnf install -y mesa-libGL mesa-libEGL libxkbcommon-x11 libxcb-cursor"
        echo "    Arch:           sudo pacman -S mesa libxkbcommon xcb-util-cursor"
        echo
    fi
else
    ok "$(_t '所有必需的系统库已存在。' 'All required system libs present.')"
fi
echo

# ---- Wayland / DISPLAY handling ----
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    info "$(_t '检测到 Wayland，为兼容性设置 QT_QPA_PLATFORM=xcb。' 'Wayland detected. Setting QT_QPA_PLATFORM=xcb for compatibility.')"
    export QT_QPA_PLATFORM=xcb
fi
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    warn "$(_t '未检测到图形界面（DISPLAY 和 WAYLAND_DISPLAY 均为空）。' 'No graphical display detected (DISPLAY and WAYLAND_DISPLAY are empty).')"
    warn "$(_t 'OtherScope 需要图形环境，GUI 很可能启动失败。' 'OtherScope requires a graphical environment. GUI will likely fail.')"
    echo
fi

# ---- Step 3: Disk space for pip deps ----
FREE_KB="$(df -k . | awk 'NR==2 {print $4}' 2>/dev/null || echo 0)"
FREE_KB="${FREE_KB:-0}"
case "${FREE_KB}" in *[!0-9]*) FREE_KB=0 ;; esac
if [ -n "${FREE_KB:-0}" ] && [ "${FREE_KB:-0}" -lt 300000 ]; then
    warn "$(_t '磁盘空间不足（约 $((FREE_KB/1024)) MB），依赖安装可能失败。' 'Low disk space (~$((FREE_KB/1024)) MB free). Dependency install may fail.')"
fi

# ---- Step 4: Run auto-launcher ----
info "$(_t '[步骤 3/4] 启动 Python 自动启动器（升级 pip -> 安装依赖 -> 带重试启动）...' '[Step 3/4] Starting Python auto-launcher (pip upgrade -> deps -> launch with retry)...')"
echo
"${PY}" "${SCRIPT_DIR}/auto_launcher.py"
LAUNCH_EXIT=$?

echo
if [ "${LAUNCH_EXIT}" -eq 0 ]; then
    ok "$(_t '[步骤 4/4] OtherScope 已正常退出。' '[Step 4/4] OtherScope finished normally.')"
    echo "          $(_t '窗口将在 2 秒后自动关闭...' 'Window will close automatically in 2 seconds...')"
    echo
    sleep 2
    exit 0
else
    fail "$(_t '启动失败，退出码 ' 'Startup failed with code ')${LAUNCH_EXIT}."
    echo "  $(_t '向上滚动查看错误详情，或查看本目录下的 OtherScope_crash.log。' 'Scroll up for error details, or check OtherScope_crash.log in this folder.')"
    echo
    read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')" 2>/dev/null || true
    exit 1
fi
