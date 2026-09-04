# -*- coding: utf-8 -*-
"""OtherScope 自举启动器（bootstrap）——打包产物双击运行时的依赖自检与自动修复。

打包产物（Windows 单文件 exe / macOS / Linux 单文件可执行）双击运行后，
本模块在导入 PySide6 之前执行，按以下顺序处理运行环境：

1. 环境检测：区分「打包态」（PyInstaller onefile，依赖已内嵌）与「源码态」
   （python main.py，Python 依赖需 pip 安装）。
2. 系统级依赖检测：打包态下检查目标系统缺失的 Qt 运行时系统库
   （Linux 的 libGL/libEGL/libxkbcommon/libxcb-cursor 等）。
3. 自动修复：检测到缺失时，自动调用系统包管理器下载安装
   （Linux 用 apt-get；macOS 用 brew；Windows 用 Qt 运行时安装），
   安装成功后自动重启程序；重复检测失败时给出明确告警。
4. 异常提醒：任何依赖或环境异常都通过图形弹窗（tkinter，标准库，
   不依赖 PySide6）与终端双通道提醒，绝不静默失败。

源码方式运行（python main.py）时本模块仅做增强检测，不阻断启动。
"""
from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys

# 首次自检标记：避免同一进程内重复安装尝试
_BOOTSTRAPPED = False

# Linux 下 Qt 运行所需系统库：库文件名 -> 软件包名（Debian/Ubuntu）
_LINUX_QT_LIBS = {
    "libGL.so.1": "libgl1",
    "libEGL.so.1": "libegl1",
    "libxkbcommon-x11.so.0": "libxkbcommon-x11-0",
    "libxcb-cursor.so.0": "libxcb-cursor0",
    "libxcb-icccm.so.4": "libxcb-icccm4",
    "libxcb-keysyms.so.1": "libxcb-keysyms1",
    "libxcb-shape.so.0": "libxcb-shape0",
    "libxcb-render-util.so.0": "libxcb-render-util0",
}

# 各平台自动安装命令模板（格式化：包名列表用空格连接）
_INSTALL_CMD = {
    "Linux": ["sudo", "apt-get", "install", "-y", "{pkgs}"],
    "Darwin": ["brew", "install", "{pkgs}"],
}


def is_frozen() -> bool:
    """是否处于打包态（PyInstaller onefile 单文件运行）。"""
    return bool(getattr(sys, "frozen", False))


def _lib_available(name: str) -> bool:
    """尝试用 ctypes 加载动态库，判断系统库是否存在。"""
    try:
        ctypes.CDLL(name)
        return True
    except OSError:
        return False


def missing_system_packages() -> list[str]:
    """返回缺失的系统库软件包名列表（仅打包态 + Linux 检测）。

    打包态下 Python 依赖已内嵌，但仍依赖目标系统的 Qt 运行库；
    其他平台（Windows/macOS 的 Qt 运行时随打包分发）返回空列表。
    """
    if not is_frozen() or platform.system() != "Linux":
        return []
    missing: list[str] = []
    for so_name, pkg in _LINUX_QT_LIBS.items():
        if not _lib_available(so_name) and pkg not in missing:
            missing.append(pkg)
    return missing


def _run_install(pkgs: list[str]) -> bool:
    """调用系统包管理器自动安装缺失包；返回是否成功。"""
    system = platform.system()
    template = _INSTALL_CMD.get(system)
    if not template:
        return False
    cmd = [part.format(pkgs=" ".join(pkgs)) for part in template]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return result.returncode == 0
    except Exception:
        return False


def _notify(title: str, text: str) -> None:
    """图形弹窗提醒（tkinter 标准库，打包后无终端也可见）。"""
    try:
        import tkinter as _tk
        from tkinter import messagebox as _msg
        _root = _tk.Tk()
        _root.withdraw()
        _root.attributes("-topmost", True)
        _msg.showwarning(title, text, parent=_root)
        _root.destroy()
    except Exception:
        try:
            print("[OtherScope 自举] {0}\n{1}".format(title, text), flush=True)
        except Exception:
            pass


def _restart_self() -> None:
    """自动重启自身（单文件可执行 / 源码脚本）。"""
    try:
        if is_frozen():
            exe = sys.executable
        else:
            exe = sys.argv[0] if sys.argv and sys.argv[0] else sys.executable
        if os.name == "nt":
            subprocess.Popen([exe], shell=False, close_fds=True)
        else:
            subprocess.Popen([exe], close_fds=True)
    except Exception as exc:  # noqa: BLE001
        _notify("OtherScope 自动重启失败",
                "程序已安装缺失依赖，但自动重启失败：\n{0}".format(exc))
        sys.exit(0)
    sys.exit(0)


def bootstrap(auto_install: bool = True) -> None:
    """自举入口：检测缺失系统库 -> 自动安装 -> 重启 -> 异常提醒。

    Args:
        auto_install: 是否允许自动调用系统包管理器安装（默认 True）。
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True

    # 打包态才做系统级依赖检测（源码态 Python 依赖由 launcher.py 处理）
    if not is_frozen():
        return
    missing = missing_system_packages()
    if not missing:
        return

    if auto_install and _run_install(missing):
        _notify("OtherScope 已自动修复运行环境",
                "检测到运行所需系统库缺失，已自动下载安装：\n"
                + "、".join(missing) + "\n\n正在自动重启程序…")
        _restart_self()
    else:
        _notify("OtherScope 运行环境缺失",
                "当前系统缺少运行所需系统库：\n" + "、".join(missing)
                + "\n\n自动安装未成功，请手动执行：\n"
                + "sudo apt-get install -y " + " ".join(missing)
                + "\n\n安装完成后重新运行本程序。")
        sys.exit(1)


if __name__ == "__main__":
    bootstrap()
