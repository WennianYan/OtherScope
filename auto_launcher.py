# -*- coding: utf-8 -*-
"""OtherScope Auto Launcher (cross-platform, i18n, Hardened v9).

Responsibilities:
1. Check Python version compatibility (>=3.9).
2. Check main.py existence.
3. Upgrade pip (with timeout).
4. Auto-install / upgrade all dependencies, fallback to mirror on failure,
   verify with a fresh subprocess after install.
5. Loop-launch main.py until normal exit (code 0); retry up to 5 times.
6. All user-facing messages follow system language (zh/en).
7. Never crash silently: always show error and wait for keypress.

Called by run_windows.bat / run_linux.sh / run_macos.command.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time

# ============================================================
#  i18n: detect system language and provide bilingual messages
# ============================================================
def _detect_language() -> str:
    """Detect system UI language. Returns 'zh' for Chinese, 'en' otherwise."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            if val.lower().startswith(("zh", "chinese")):
                return "zh"
            return "en"
    # Windows: try to detect via registry if no env vars
    if sys.platform == "win32":
        try:
            import ctypes
            # GetUserDefaultUILanguage
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # 0x0804 = zh-CN, 0x0C04 = zh-HK, 0x0404 = zh-TW, 0x1004 = zh-SG
            if lang_id in (0x0804, 0x0C04, 0x0404, 0x1004, 0x7C04):
                return "zh"
        except Exception:
            pass
    return "en"


_LANG = _detect_language()


def _t(zh: str, en: str) -> str:
    """Return Chinese or English message based on detected language."""
    return zh if _LANG == "zh" else en


# ============================================================
#  Constants
# ============================================================
REQUIREMENTS = [
    ("PySide6", "PySide6>=6.8", (6, 8)),
    ("pyqtgraph", "pyqtgraph>=0.14.0", (0, 14, 0)),
    ("serial", "pyserial>=3.5", (3, 5)),
    ("numpy", "numpy>=1.25", (1, 25)),
]

MIRROR_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
MAX_LAUNCH_RETRIES = 5
RETRY_DELAY_SEC = 3
MAX_DEP_RETRIES = 2
PIP_UPGRADE_TIMEOUT = 180
PIP_INSTALL_TIMEOUT = 600
DEPS_VERIFY_TIMEOUT = 120
MIN_FREE_SPACE_MB = 500


# ============================================================
#  Helpers
# ============================================================
def _sep(char: str = "=", width: int = 60) -> None:
    print(char * width)


def _status(step_zh: str, step_en: str, msg_zh: str, msg_en: str) -> None:
    step = step_zh if _LANG == "zh" else step_en
    msg = msg_zh if _LANG == "zh" else msg_en
    print(f"[{step}] {msg}", flush=True)


def _parse_version(ver_str: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", ver_str)
    return tuple(int(p) for p in parts) if parts else (0,)


def _get_installed_version(import_name: str) -> tuple[int, ...] | None:
    try:
        import importlib
        mod = importlib.import_module(import_name)
        ver = getattr(mod, "__version__", None) or getattr(mod, "VERSION", None)
        if ver is None:
            return None
        return _parse_version(str(ver))
    except Exception:
        return None


# ============================================================
#  Pre-flight checks
# ============================================================
def _check_disk_space() -> bool:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        usage = shutil.disk_usage(script_dir)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < MIN_FREE_SPACE_MB:
            print(_t(
                f"  [WARN] 磁盘空间不足: 约 {free_mb} MB 可用（建议至少 {MIN_FREE_SPACE_MB} MB）",
                f"  [WARN] Low disk space: ~{free_mb} MB free (recommend at least {MIN_FREE_SPACE_MB} MB)",
            ), flush=True)
            print(_t(
                "         依赖安装可能失败，请清理磁盘后重试。",
                "         Dependency install may fail. Free up disk space and retry.",
            ), flush=True)
            return False
        print(_t(
            f"  磁盘空间: 约 {free_mb} MB 可用",
            f"  Disk space: ~{free_mb} MB free",
        ), flush=True)
        return True
    except Exception as exc:
        print(_t(
            f"  [WARN] 无法检查磁盘空间: {exc}",
            f"  [WARN] Cannot check disk space: {exc}",
        ), flush=True)
        return True


def _check_python_version() -> bool:
    if sys.version_info < (3, 9):
        print(_t(
            f"  [ERROR] Python 版本过低: {sys.version.split()[0]}，需要 >= 3.9",
            f"  [ERROR] Python too old: {sys.version.split()[0]}, need >= 3.9",
        ), flush=True)
        print(_t(
            "         请升级 Python 后重试。",
            "         Please upgrade Python and retry.",
        ), flush=True)
        return False
    return True


# ============================================================
#  Dependency management
# ============================================================
def _needs_install() -> list[str]:
    import importlib
    needed: list[str] = []
    for import_name, pip_spec, min_ver in REQUIREMENTS:
        try:
            importlib.import_module(import_name)
        except ImportError:
            needed.append(pip_spec)
            continue
        if min_ver is not None:
            installed = _get_installed_version(import_name)
            if installed is not None and installed < min_ver:
                print(_t(
                    f"  -> {import_name} 版本 {'.'.join(map(str, installed))} "
                    f"< 要求 {'.'.join(map(str, min_ver))}，将升级",
                    f"  -> {import_name} {'.'.join(map(str, installed))} "
                    f"< required {'.'.join(map(str, min_ver))}, will upgrade",
                ), flush=True)
                needed.append(pip_spec)
    return needed


def _verify_deps_subprocess() -> list[str]:
    check_code = (
        "import importlib, re, sys\n"
        "reqs = " + repr([(n, s, list(v)) for n, s, v in REQUIREMENTS]) + "\n"
        "def pv(s):\n"
        "    parts = re.findall(r'\\d+', str(s))\n"
        "    return tuple(int(p) for p in parts) if parts else (0,)\n"
        "missing = []\n"
        "for name, spec, minv in reqs:\n"
        "    try:\n"
        "        m = importlib.import_module(name)\n"
        "        ver = getattr(m, '__version__', None) or getattr(m, 'VERSION', None)\n"
        "        if ver and minv and pv(ver) < tuple(minv):\n"
        "            missing.append(spec)\n"
        "    except Exception:\n"
        "        missing.append(spec)\n"
        "print('|'.join(missing))\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", check_code],
            capture_output=True, text=True, timeout=DEPS_VERIFY_TIMEOUT,
        )
        output = result.stdout.strip()
        if output:
            return [s for s in output.split("|") if s]
        return []
    except subprocess.TimeoutExpired:
        print(_t(
            "  [WARN] 依赖验证子进程超时，保守判定为仍需安装",
            "  [WARN] Dependency verify subprocess timed out, conservatively need install",
        ), flush=True)
        return [spec for _, spec, _ in REQUIREMENTS]
    except Exception:
        return [spec for _, spec, _ in REQUIREMENTS]


def _run_pip(args: list[str], use_mirror: bool = False) -> int:
    cmd = [sys.executable, "-m", "pip", "install", *args, "--disable-pip-version-check"]
    if use_mirror:
        cmd += ["-i", MIRROR_URL]
    print(_t(f"  命令: {' '.join(cmd)}", f"  Command: {' '.join(cmd)}"), flush=True)
    print(_t(f"  超时: {PIP_INSTALL_TIMEOUT} 秒", f"  Timeout: {PIP_INSTALL_TIMEOUT}s"), flush=True)
    try:
        result = subprocess.run(cmd, check=False, timeout=PIP_INSTALL_TIMEOUT)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(_t(
            f"  [ERROR] pip 安装超时（{PIP_INSTALL_TIMEOUT} 秒）",
            f"  [ERROR] pip install timed out ({PIP_INSTALL_TIMEOUT}s)",
        ), flush=True)
        print(_t(
            "         可能原因：网络慢、镜像不可用、或包太大。",
            "         Possible: slow network, mirror unavailable, or package too large.",
        ), flush=True)
        return -2
    except Exception as exc:
        print(_t(f"  pip 执行异常: {exc}", f"  pip execution error: {exc}"), flush=True)
        return -1


def ensure_dependencies() -> bool:
    _status("步骤 2/4", "Step 2/4", "检查依赖...", "Checking dependencies...")
    needed = _needs_install()
    if not needed:
        _status("步骤 2/4", "Step 2/4", "所有依赖已就绪，无需安装。", "All dependencies ready, no install needed.")
        return True

    print(_t(
        f"  需要安装 / 升级: {' '.join(needed)}",
        f"  Need to install / upgrade: {' '.join(needed)}",
    ), flush=True)

    _check_disk_space()
    print()

    for attempt in range(1, MAX_DEP_RETRIES + 1):
        _status("步骤 2/4", "Step 2/4",
                f"安装依赖（第 {attempt}/{MAX_DEP_RETRIES} 次尝试）...",
                f"Installing dependencies (attempt {attempt}/{MAX_DEP_RETRIES})...")
        rc = _run_pip(needed, use_mirror=(attempt > 1))
        if rc == 0:
            print(_t("  验证安装结果（子进程）...", "  Verifying install (subprocess)..."), flush=True)
            still_needed = _verify_deps_subprocess()
            if not still_needed:
                _status("步骤 2/4", "Step 2/4", "依赖安装成功，全部就绪。", "Dependencies installed successfully.")
                return True
            print(_t(
                f"  安装后仍有缺失（子进程验证）: {' '.join(still_needed)}",
                f"  Still missing after install (subprocess verify): {' '.join(still_needed)}",
            ), flush=True)
            needed = still_needed
        elif rc == -2:
            if attempt < MAX_DEP_RETRIES:
                print(_t("  将切换国内镜像重试...", "  Switching to mirror and retrying..."), flush=True)
                time.sleep(2)
        else:
            print(_t(f"  pip 返回错误码 {rc}", f"  pip returned error code {rc}"), flush=True)
            if attempt < MAX_DEP_RETRIES:
                print(_t("  将切换国内镜像重试...", "  Switching to mirror and retrying..."), flush=True)
                time.sleep(1)

    _status("步骤 2/4", "Step 2/4",
            "依赖安装失败，请检查网络连接后重试。",
            "Dependency install failed. Check network connection and retry.")
    print(_t("  可能原因：", "  Possible causes:"), flush=True)
    print(_t("    1. 网络连接不稳定或被防火墙拦截", "    1. Unstable network or firewall blocking"), flush=True)
    print(_t("    2. pip 源不可用（已尝试默认源和清华镜像）", "    2. pip source unavailable (tried default + Tsinghua mirror)"), flush=True)
    print(_t("    3. 磁盘空间不足", "    3. Low disk space"), flush=True)
    print(_t("    4. Python 环境损坏", "    4. Corrupted Python environment"), flush=True)
    return False


def upgrade_pip() -> None:
    _status("步骤 1/4", "Step 1/4", "升级 pip...", "Upgrading pip...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip",
             "--disable-pip-version-check", "-q"],
            check=False, timeout=PIP_UPGRADE_TIMEOUT,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(_t(
                f"  [WARN] pip 升级返回码 {result.returncode}，继续使用当前版本",
                f"  [WARN] pip upgrade returned {result.returncode}, using current version",
            ), flush=True)
            if result.stderr:
                last_err = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
                if last_err:
                    print(f"         {last_err}", flush=True)
    except subprocess.TimeoutExpired:
        print(_t(
            f"  [WARN] pip 升级超时（{PIP_UPGRADE_TIMEOUT} 秒），继续使用当前版本",
            f"  [WARN] pip upgrade timed out ({PIP_UPGRADE_TIMEOUT}s), using current version",
        ), flush=True)
    except Exception as exc:
        print(_t(
            f"  [WARN] pip 升级异常: {exc}，继续使用当前版本",
            f"  [WARN] pip upgrade error: {exc}, using current version",
        ), flush=True)
    print(_t("  pip 升级完成（或已是最新版）。", "  pip upgrade done (or already latest)."), flush=True)


# ============================================================
#  Launch main.py
# ============================================================
def launch_main() -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_py = os.path.join(script_dir, "main.py")

    if not os.path.exists(main_py):
        print(_t(
            f"  [FATAL] main.py 不存在: {main_py}",
            f"  [FATAL] main.py not found: {main_py}",
        ), flush=True)
        print(_t(
            "         请确保所有文件在同一目录下。",
            "         Make sure all files are in the same folder.",
        ), flush=True)
        return -3

    env = os.environ.copy()
    env["OTHERSCOPE_AUTO_LAUNCH"] = "1"
    try:
        proc = subprocess.run([sys.executable, main_py], env=env, cwd=script_dir)
        return proc.returncode
    except FileNotFoundError:
        print(_t(
            f"  [FATAL] Python 解释器不存在: {sys.executable}",
            f"  [FATAL] Python interpreter not found: {sys.executable}",
        ), flush=True)
        return -4
    except Exception as exc:
        print(_t(f"  启动异常: {exc}", f"  Launch error: {exc}"), flush=True)
        return -1


def _read_crash_log() -> str:
    crash_log = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "OtherScope_crash.log")
    if not os.path.exists(crash_log):
        return ""
    try:
        with open(crash_log, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        if not content:
            return ""
        last_lines = content.splitlines()[-15:]
        return "\n".join(f"  {line}" for line in last_lines)
    except PermissionError:
        return _t("  [WARN] 崩溃日志无读取权限", "  [WARN] Cannot read crash log (permission denied)")
    except Exception as exc:
        return _t(f"  [WARN] 读取崩溃日志失败: {exc}", f"  [WARN] Failed to read crash log: {exc}")


# ============================================================
#  Main
# ============================================================
def main() -> int:
    _sep()
    print(_t("  OtherScope 全自动启动器", "  OtherScope Auto Launcher"))
    print(f"  Python: {sys.version.split()[0]}  ({sys.executable})")
    print(_t(
        f"  工作目录: {os.path.dirname(os.path.abspath(__file__))}",
        f"  Working dir: {os.path.dirname(os.path.abspath(__file__))}",
    ))
    _sep()
    print()

    # 0. Pre-flight
    _status("预检查", "Pre-check", "验证运行环境...", "Verifying runtime environment...")
    if not _check_python_version():
        return 1
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_py = os.path.join(script_dir, "main.py")
    if not os.path.exists(main_py):
        print(_t(
            f"  [FATAL] main.py 不存在: {main_py}",
            f"  [FATAL] main.py not found: {main_py}",
        ), flush=True)
        return 1
    print(_t("  环境检查通过。", "  Environment check passed."), flush=True)
    print()

    # 1. Upgrade pip
    upgrade_pip()
    print()

    # 2. Install dependencies
    if not ensure_dependencies():
        _sep()
        print(_t("  依赖安装失败，无法启动程序。", "  Dependency install failed. Cannot launch."))
        print(_t("  请检查网络后重新运行启动脚本", "  Check network and re-run the launcher script"))
        _sep()
        return 1
    print()

    # 3. Loop launch
    _status("步骤 3/4", "Step 3/4", "启动 OtherScope 主程序...", "Launching OtherScope main program...")
    for attempt in range(1, MAX_LAUNCH_RETRIES + 1):
        print()
        _sep("-")
        print(_t(f"  启动尝试 {attempt}/{MAX_LAUNCH_RETRIES}",
                 f"  Launch attempt {attempt}/{MAX_LAUNCH_RETRIES}"))
        _sep("-")
        rc = launch_main()

        if rc == 0:
            print()
            _status("步骤 4/4", "Step 4/4",
                    "OtherScope 已正常运行并退出。",
                    "OtherScope ran normally and exited.")
            return 0

        print()
        print(_t(f"  程序异常退出（退出码: {rc}）",
                 f"  Program exited abnormally (code: {rc})"), flush=True)

        if rc == -3:
            print(_t("  main.py 缺失，无法继续重试。", "  main.py missing, cannot retry."), flush=True)
            return 1
        if rc == -4:
            print(_t("  Python 解释器缺失，无法继续重试。", "  Python interpreter missing, cannot retry."), flush=True)
            return 1

        crash_content = _read_crash_log()
        if crash_content:
            print(_t("  ---- 崩溃日志（最后 15 行）----",
                     "  ---- Crash log (last 15 lines) ----"), flush=True)
            print(crash_content, flush=True)
            print("  --------------------------------", flush=True)

        if attempt < MAX_LAUNCH_RETRIES:
            print(_t(f"  {RETRY_DELAY_SEC} 秒后自动重试...",
                     f"  Retrying in {RETRY_DELAY_SEC} seconds..."), flush=True)
            time.sleep(RETRY_DELAY_SEC)
        else:
            print()
            _sep()
            print(_t(f"  连续 {MAX_LAUNCH_RETRIES} 次启动失败，已停止重试。",
                     f"  {MAX_LAUNCH_RETRIES} consecutive launch failures, stopped retrying."))
            print(_t("  可能原因：", "  Possible causes:"))
            print(_t("    1. 显卡驱动与 PySide6 不兼容", "    1. GPU driver incompatible with PySide6"))
            print(_t("    2. 缺少系统运行库（Linux: libxcb-cursor 等；Windows: VC++ Redistributable）",
                     "    2. Missing system libs (Linux: libxcb-cursor etc; Windows: VC++ Redistributable)"))
            print(_t("    3. 杀毒软件拦截了程序运行", "    3. Antivirus blocking the program"))
            print(_t("    4. 无图形界面环境（服务器/SSH 无 X11 转发）",
                     "    4. No GUI environment (server/SSH without X11 forwarding)"))
            print(_t("  详细错误请查看上方日志或 OtherScope_crash.log 文件。",
                     "  See logs above or OtherScope_crash.log for details."))
            _sep()
            return 1

    return 0


def _safe_main() -> int:
    """Wrap main() to handle BrokenPipeError and other unexpected crashes."""
    try:
        return main()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        print()
        print(_t("[OtherScope] 用户中断。", "[OtherScope] Interrupted by user."))
        return 130
    except Exception as exc:
        print()
        print("=" * 60)
        print(_t(
            f"[FATAL] 自动启动器意外错误: {type(exc).__name__}: {exc}",
            f"[FATAL] Unexpected error in auto_launcher: {type(exc).__name__}: {exc}",
        ))
        import traceback
        traceback.print_exc()
        print("=" * 60)
        print(_t("这不应该发生，请报告此问题。", "This should not happen. Please report this issue."))
        try:
            input(_t("按回车键关闭...", "Press Enter to close..."))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass
    sys.exit(_safe_main())
