#!/usr/bin/env bash
# ============================================================
#   OtherScope - macOS Auto Launcher (Hardened v8)
#   - Xcode CLT detection + install guidance
#   - Python version check (>=3.9), rejects system Python 2.7
#   - pip availability check
#   - Homebrew auto-install (with sudo guidance)
#   - Apple Silicon / Intel path auto-detection
#   - Gatekeeper quarantine removal
#   - Disk space check, detailed error messages
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
    echo "[OtherScope] $(_t '[INFO] 已中断，正在清理...' '[INFO] Interrupted. Cleaning up...')"
    echo
    read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')" 2>/dev/null || true
    exit 130
}
trap '_on_interrupt' INT TERM HUP


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || { echo "[FATAL] Cannot enter script directory: ${SCRIPT_DIR}"; read -r -p "$(_t '按回车键...' 'Press Enter...')"; exit 1; }

info()  { echo "[OtherScope] $*"; }
ok()    { echo "[OtherScope] [OK] $*"; }
warn()  { echo "[OtherScope] [WARN] $*"; }
fail()  { echo "[OtherScope] [ERROR] $*"; }

echo
info "================================================================"
info "  $(_t 'OtherScope - macOS 全自动启动器' 'OtherScope - macOS Auto Launcher')"
info "  $(_t '工作目录' 'Workdir'): ${SCRIPT_DIR}"
info "  $(_t '架构' 'Architecture'): $(uname -m 2>/dev/null || echo unknown)"
info "  macOS: $(sw_vers -productVersion 2>/dev/null || echo unknown)"
info "================================================================"
echo

# ---- Remove Gatekeeper quarantine attribute ----
xattr -d com.apple.quarantine "${SCRIPT_DIR}/run_macos.command" 2>/dev/null || true
xattr -d com.apple.quarantine "${SCRIPT_DIR}/auto_launcher.py" 2>/dev/null || true

# ---- Pre-flight: auto_launcher.py exists ----
if [ ! -f "${SCRIPT_DIR}/auto_launcher.py" ]; then
    fail "$(_t 'auto_launcher.py 未找到' 'auto_launcher.py not found'): ${SCRIPT_DIR}"
    echo "  $(_t '请确保所有文件在同一目录下。' 'Make sure all files are in the same folder.')"
    echo
    read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
    exit 1
fi

# ---- Step 1: Xcode Command Line Tools ----
info "$(_t '[步骤 1/5] 检查 Xcode 命令行工具...' '[Step 1/5] Checking Xcode Command Line Tools...')"
if xcode-select -p >/dev/null 2>&1; then
    ok "$(_t 'Xcode CLT 已安装 (' 'Xcode CLT present (')$(xcode-select -p))."
else
    warn "$(_t '未找到 Xcode CLT，Homebrew 和 Python 编译需要它。' 'Xcode CLT not found. It is required for Homebrew and Python builds.')"
    echo "  $(_t '将弹出对话框要求安装命令行工具。' 'A dialog will appear asking you to install the Command Line Tools.')"
    echo "  $(_t '点击"安装"并等待完成，然后重新运行此脚本。' 'Click Install and wait for it to complete, then re-run this script.')"
    echo
    xcode-select --install 2>/dev/null || true
    read -r -p "$(_t '按回车键关闭（Xcode CLT 安装后重新运行）...' 'Press Enter to close (then re-run after Xcode CLT install)...')"
    exit 1
fi
echo

# ---- Step 2: Find working Python >=3.9 (not system 2.7) ----
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
                # Reject Python 2.x (macOS system default)
                if [ "${major}" -ge 3 ] && { [ "${major}" -gt 3 ] || [ "${minor}" -ge 9 ]; }; then
                    PY="${candidate}"
                    PY_VER="${out}"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

find_python
if [ -n "${PY}" ]; then
    ok "$(_t '[步骤 2/5] 找到 Python: ' '[Step 2/5] Python found: ')${PY_VER}"
else
    info "$(_t '[步骤 2/5] 未找到可用 Python (>=3.9)，将通过 Homebrew 安装...' '[Step 2/5] No working Python (>=3.9) found. Will install via Homebrew...')"
    echo

    # Disk space check
    FREE_KB="$(df -k / | awk 'NR==2 {print $4}' 2>/dev/null || echo 0)"
    FREE_KB="${FREE_KB:-0}"
    case "${FREE_KB}" in *[!0-9]*) FREE_KB=0 ;; esac
    if [ -n "${FREE_KB:-0}" ] && [ "${FREE_KB:-0}" -lt 2000000 ]; then
        fail "$(_t '磁盘空间不足（约 $((FREE_KB/1024)) MB，Homebrew+Python 需要约 2GB）。' 'Not enough disk space (~$((FREE_KB/1024)) MB free, need ~2GB for Homebrew+Python).')"
        echo "  $(_t '请清理磁盘空间后重新运行。' 'Please free up disk space and re-run.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi

    # ---- Install Homebrew if missing ----
    if ! command -v brew >/dev/null 2>&1; then
        info "$(_t '未找到 Homebrew，正在安装（可能需要 5-10 分钟）...' 'Homebrew not found. Installing Homebrew (this may take 5-10 minutes)...')"
        echo "  $(_t '注意：Homebrew 安装可能需要输入 sudo 密码。' 'Note: Homebrew install may ask for your sudo password.')"
        echo "  $(_t '如果提示，请输入 Mac 登录密码（输入时不会显示）。' 'If it does, enter your Mac login password (it will not be shown).')"
        echo

        # Check if we can do passwordless sudo
        if ! sudo -n true 2>/dev/null; then
            warn "$(_t '无免密 sudo，Homebrew 安装将提示输入密码。' 'Passwordless sudo not available. Homebrew install will prompt for password.')"
            echo "  $(_t '这是正常的 - 请在提示时输入密码。' 'This is normal - please enter your password when prompted.')"
            echo
        fi

        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [ $? -ne 0 ]; then
            fail "$(_t 'Homebrew 安装失败。' 'Homebrew installation failed.')"
            echo "  $(_t '可能原因：网络问题、代理、或取消了密码提示。' 'Possible causes: network issue, proxy, or cancelled password prompt.')"
            echo "  $(_t '请从 https://brew.sh 手动安装 Homebrew 后重新运行。' 'Please install Homebrew manually from https://brew.sh and re-run.')"
            read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
            exit 1
        fi

        # Add brew to PATH for this session (Apple Silicon vs Intel)
        if [ -x /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
        elif [ -x /usr/local/bin/brew ]; then
            eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null || true
        fi
        # Fallback: manually add brew bin to PATH if eval failed
        if ! command -v brew >/dev/null 2>&1; then
            if [ -d /opt/homebrew/bin ]; then export PATH="/opt/homebrew/bin:${PATH}"; fi
            if [ -d /usr/local/bin ]; then export PATH="/usr/local/bin:${PATH}"; fi
            hash -r 2>/dev/null || true || true
        fi
    fi

    if ! command -v brew >/dev/null 2>&1; then
        fail "$(_t '安装后 Homebrew 仍不可用。' 'Homebrew still not available after install.')"
        echo "  $(_t '请打开新的终端窗口并重新运行此脚本。' 'Please open a new Terminal window and re-run this script.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi
    ok "$(_t 'Homebrew 已就绪: ' 'Homebrew ready: ')$(brew --version | head -1)"

    # ---- Install Python via Homebrew ----
    info "$(_t '正在通过 Homebrew 安装 Python 3.12（可能需要 2-5 分钟）...' 'Installing Python 3.12 via Homebrew (this may take 2-5 minutes)...')"
    brew install python@3.12 2>&1 | tail -5
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        fail "$(_t 'brew install python@3.12 失败。' 'brew install python@3.12 failed.')"
        echo "  $(_t '可能原因：网络问题、依赖冲突、或权限不足。' 'Possible causes: network issue, dependency conflict, or insufficient permissions.')"
        echo "  $(_t '尝试运行：brew update && brew doctor，然后重新运行。' 'Try running: brew update && brew doctor, then re-run this script.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi

    # Add Homebrew Python to PATH
    if [ -d /opt/homebrew/opt/python@3.12/libexec/bin ]; then
        export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:/opt/homebrew/bin:${PATH}"
    elif [ -d /usr/local/opt/python@3.12/libexec/bin ]; then
        export PATH="/usr/local/opt/python@3.12/libexec/bin:/usr/local/bin:${PATH}"
    fi
    hash -r 2>/dev/null || true || true

    find_python
    if [ -n "${PY}" ]; then
        ok "$(_t '[步骤 2/5] Python 已安装: ' '[Step 2/5] Python installed: ')${PY_VER}"
    else
        fail "$(_t 'Python 安装完成，但仍无法找到可用的 Python >=3.9。' 'Python installation completed but still cannot find working Python >=3.9.')"
        echo "  $(_t '请打开新的终端窗口重新运行，或手动安装 Python。' 'Please open a new Terminal window and re-run, or install Python manually.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi
fi
echo "          Path: $(command -v "${PY}" 2>/dev/null || echo "${PY}")"
echo

# ---- Step 2b: Verify pip ----
info "$(_t '[步骤 2b/5] 检查 pip...' '[Step 2b/5] Checking pip...')"
if ! "${PY}" -m pip --version >/dev/null 2>&1; then
    warn "$(_t 'pip 不可用，尝试 ensurepip...' 'pip not available. Attempting ensurepip...')"
    if ! "${PY}" -m ensurepip --upgrade >/dev/null 2>&1; then
        fail "$(_t 'ensurepip 失败，pip 不可用。' 'ensurepip failed. pip is unavailable.')"
        echo "  $(_t '请重新安装 Python 或手动安装 pip。' 'Please reinstall Python or install pip manually.')"
        read -r -p "$(_t '按回车键关闭...' 'Press Enter to close...')"
        exit 1
    fi
fi
"${PY}" -m pip --version 2>&1 | sed 's/^/          /'
echo

# ---- Step 3: Disk space for pip deps ----
info "$(_t '[步骤 3/5] 检查磁盘空间...' '[Step 3/5] Checking disk space...')"
FREE_KB="$(df -k . | awk 'NR==2 {print $4}' 2>/dev/null || echo 0)"
FREE_KB="${FREE_KB:-0}"
case "${FREE_KB}" in *[!0-9]*) FREE_KB=0 ;; esac
if [ -n "${FREE_KB:-0}" ] && [ "${FREE_KB:-0}" -lt 500000 ]; then
    warn "$(_t '磁盘空间不足（约 $((FREE_KB/1024)) MB），依赖安装可能失败。' 'Low disk space (~$((FREE_KB/1024)) MB free). Dependency install may fail.')"
else
    ok "$(_t '磁盘空间正常（约 $((FREE_KB/1024)) MB）。' 'Disk space OK (~$((FREE_KB/1024)) MB free).')"
fi
echo

# ---- Step 4: Run auto-launcher ----
info "$(_t '[步骤 4/5] 启动 Python 自动启动器（升级 pip -> 安装依赖 -> 带重试启动）...' '[Step 4/5] Starting Python auto-launcher (pip upgrade -> deps -> launch with retry)...')"
echo
"${PY}" "${SCRIPT_DIR}/auto_launcher.py"
LAUNCH_EXIT=$?

echo
if [ "${LAUNCH_EXIT}" -eq 0 ]; then
    ok "$(_t '[步骤 5/5] OtherScope 已正常退出。' '[Step 5/5] OtherScope finished normally.')"
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
