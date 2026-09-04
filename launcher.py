# -*- coding: utf-8 -*-
"""OtherScope 启动引导器。

功能：
1. 自动判断操作系统（Windows / macOS / Linux）。
2. 首次运行或缺少依赖时，自动调用对应系统的 pip 安装依赖。
3. 安装成功后启动主程序；失败时在终端显示依赖明细与手动安装命令，按任意键退出。

用法：
    python launcher.py
"""
from __future__ import annotations
import importlib
import os
import subprocess
import sys
import platform

# 依赖清单：(import_name, pip_name)
# 注意：pyqtgraph 必须 >=0.14.0 —— 0.13.x 在 Python 3.12+/3.14 上
# 使用 QPicture 绘制坐标轴会触发 access violation 崩溃（PR #3471 已修复）。
# Python 3.13+ 环境下 PySide6 亦需 >=6.8。
REQUIREMENTS = [
    ("PySide6", "PySide6>=6.8"),
    ("pyqtgraph", "pyqtgraph>=0.14.0"),
    ("serial", "pyserial>=3.5"),
    ("numpy", "numpy>=1.25"),
]

# Linux 无桌面环境时需要的系统库（仅提示，不自动安装）
LINUX_SYS_LIBS = "libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0"


def detect_os() -> str:
    """返回 'windows' / 'macos' / 'linux' / 'unknown'。"""
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    if s == "linux":
        return "linux"
    return "unknown"


def check_missing() -> list[tuple[str, str]]:
    """检查缺少的依赖，返回 [(import_name, pip_name), ...]。"""
    missing = []
    for import_name, pip_name in REQUIREMENTS:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append((import_name, pip_name))
    return missing


def install_deps(missing: list[tuple[str, str]]) -> bool:
    """用 pip 安装缺少的依赖，返回是否成功。"""
    pip_names = [pip_name for _, pip_name in missing]
    cmd = [sys.executable, "-m", "pip", "install", *pip_names]
    print(f"[OtherScope] 正在安装依赖: {' '.join(pip_names)}")
    print(f"[OtherScope] 命令: {' '.join(cmd)}")
    print("-" * 60)
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        print(f"[OtherScope] 安装失败: {exc}")
        return False


def print_failure(missing: list[tuple[str, str]], os_name: str):
    """安装失败时打印依赖明细和手动安装命令。"""
    print("\n" + "=" * 60)
    print("[OtherScope] 依赖安装失败，请手动安装以下依赖：")
    print("=" * 60)
    print("\n缺少的 Python 包：")
    for import_name, pip_name in missing:
        print(f"  - {pip_name} (import: {import_name})")
    print("\n手动安装命令：")
    print(f"  {sys.executable} -m pip install {' '.join(p for _, p in missing)}")
    if os_name == "linux":
        print("\nLinux 系统库（如缺少图形支持）：")
        print(f"  sudo apt-get install {LINUX_SYS_LIBS}")
    print("\n安装完成后重新运行本程序。")
    print("=" * 60)


def wait_key():
    """等待用户按任意键（跨平台）。"""
    print("\n按任意键退出...")
    try:
        if os_name == "windows":
            os.system("pause")
        else:
            # macOS / Linux：读一个字符
            import tty
            import termios
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:  # noqa: BLE001
        input()


def main():
    global os_name
    os_name = detect_os()
    print(f"[OtherScope] 操作系统: {os_name}")
    print(f"[OtherScope] Python: {sys.version.split()[0]}")
    print(f"[OtherScope] 工作目录: {os.getcwd()}")

    missing = check_missing()
    if not missing:
        print("[OtherScope] 所有依赖已就绪，启动程序...")
    else:
        print(f"[OtherScope] 检测到 {len(missing)} 个缺少的依赖，尝试自动安装...")
        ok = install_deps(missing)
        if not ok:
            print_failure(missing, os_name)
            wait_key()
            sys.exit(1)
        # 安装后重新检查
        missing_after_install = check_missing()
        if missing_after_install:
            print("[OtherScope] 安装后仍有依赖缺失：")
            print_failure(missing_after_install, os_name)
            wait_key()
            sys.exit(1)
        print("[OtherScope] 依赖安装成功，启动程序...")

    # 切换到脚本所在目录，确保相对路径正确
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    sys.path.insert(0, script_dir)

    # 启动主程序
    try:
        from main import main as run_main
        run_main()
    except ImportError as exc:
        print(f"[OtherScope] 无法导入主程序: {exc}")
        print_failure(check_missing(), os_name)
        wait_key()
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        # BUG-FIX：主程序运行时任何异常都不闪退，打印错误信息并等待用户按键
        import traceback
        print("\n" + "=" * 60)
        print("[OtherScope] 程序运行出错：")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
        print(f"错误类型: {type(exc).__name__}")
        print(f"错误信息: {exc}")
        print("=" * 60)
        wait_key()
        sys.exit(1)


os_name = "unknown"

if __name__ == "__main__":
    main()
