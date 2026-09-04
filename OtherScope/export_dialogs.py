# -*- coding: utf-8 -*-
"""导出/保存完成对话框公共模块。

所有导出、保存文件完成后弹出的成功提示统一走 show_saved_dialog：
- 提供「打开」按钮：用系统默认程序打开目标文件（目录则直接打开目录）；
- 提供「打开文件夹」按钮：在文件管理器中定位/显示目标文件所在目录；
- 提供「确定」按钮：关闭对话框。

跨平台实现：
- Windows: os.startfile 打开；explorer /select, 定位文件夹并选中文件。
- macOS:  open 打开；open -R 定位。
- Linux:  xdg-open 打开；xdg-open 打开所在目录。
"""
from __future__ import annotations

import os
import subprocess
import sys

from .translations import tr


def _open_path(path: str) -> None:
    """用系统默认程序打开文件或目录（后台进程，不阻塞 UI）。"""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001 - 打开失败不影响主流程
        pass


def _reveal_path(path: str) -> None:
    """在文件管理器中显示/定位目标（文件选中，目录直接打开）。"""
    try:
        if os.path.isdir(path):
            _open_path(path)
            return
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            dir_path = os.path.dirname(path)
            subprocess.Popen(["xdg-open", dir_path if dir_path else "."])
    except Exception:  # noqa: BLE001
        pass


def show_saved_dialog(parent, title: str, message: str, path: str) -> None:
    """导出/保存成功对话框：打开 / 打开文件夹 / 确定 三按钮。

    parent   : 父窗口（可为 None）
    title    : 对话框标题（应使用 tr() 后的文本）
    message  : 成功提示正文（应使用 trf() 后的文本，通常含路径）
    path     : 已生成的文件（或目录）绝对路径
    """
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(message)

    btn_open = box.addButton(tr("common.open"), QMessageBox.ButtonRole.ActionRole)
    btn_folder = box.addButton(tr("common.open_folder"), QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Ok)

    box.exec()

    clicked = box.clickedButton()
    if clicked is btn_open:
        _open_path(path)
    elif clicked is btn_folder:
        _reveal_path(path)
