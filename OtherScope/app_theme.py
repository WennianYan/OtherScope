# -*- coding: utf-8 -*-
"""主题（深色 / 浅色）切换。

以纯 Python 字典定义两套配色，输出：
- QSS 样式表（作用于所有 Qt 控件：菜单、按钮、下拉框、分组框、表格、输入框等）。
- pyqtgraph 绘图区配色（背景 / 前景 / 网格 / 坐标轴文字）。

设计要点：
- 单一入口 ``apply_theme(app, theme)``：先设置 pyqtgraph 全局配置，再安装 QSS。
- 已创建的 PlotWidget 通过其父面板的 ``apply_theme(theme)`` 就地重绘背景，避免重建。
- 默认深色（与既有视觉一致），浅色主题保证足够对比度与可读性。
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QColor, QPalette

THEME_DARK = "dark"
THEME_LIGHT = "light"


THEMES = {
    THEME_DARK: {
        "name_en": "Dark",
        "name_zh": "深色",
        # Qt 控件
        "window": "#141821",
        "base": "#0f1115",          # 输入框/列表底
        "alt_base": "#1a2029",
        "panel": "#1c2330",
        "text": "#e6e9ef",
        "muted": "#9aa4b2",
        "border": "#2c3442",
        "hover_color": "#2a3140",
        "accent": "#00c8ff",
        "accent_text": "#00242e",
        "selection": "#065f72",
        # pyqtgraph
        "pg_bg": "#0f1115",
        "pg_fg": "#d8dee9",
        "pg_grid": (255, 255, 255, 40),
    },
    THEME_LIGHT: {
        "name_en": "Light",
        "name_zh": "浅色",
        "window": "#f4f6f9",
        "base": "#ffffff",
        "alt_base": "#eef1f5",
        "panel": "#e7ebf1",
        "text": "#1c2230",
        "muted": "#5a6577",
        "border": "#c6ceda",
        "hover_color": "#dde4ee",
        "accent": "#0077b6",
        "accent_text": "#ffffff",
        "selection": "#b8dcff",
        "pg_bg": "#ffffff",
        "pg_fg": "#1c2230",
        "pg_grid": (0, 0, 0, 45),
    },
}


def _color(theme: str, key: str) -> str:
    return THEMES[theme][key]


def set_pg_config(theme: str):
    """设置 pyqtgraph 全局配置（影响新建图；已有图由面板 apply_theme 重绘）。

    不在此设置 antialias，避免覆盖 WaveformPanel 为性能设置的
    antialias=False。抗锯齿由各面板自行控制。
    """
    colors = THEMES[theme]
    try:
        pg.setConfigOptions(background=colors["pg_bg"], foreground=colors["pg_fg"])
    except Exception:  # noqa: BLE001
        pass


def qss(theme: str) -> str:
    """生成指定主题的全局 QSS 样式表字符串（深色/浅色共用模板，颜色取自 THEMES）。"""
    colors = THEMES[theme]
    window = colors["window"]
    base = colors["base"]
    alt_base = colors["alt_base"]
    panel = colors["panel"]
    text = colors["text"]
    muted = colors["muted"]
    border = colors["border"]
    hover_color = colors["hover_color"]
    accent = colors["accent"]
    accent_text = colors["accent_text"]
    selection = colors["selection"]
    return f"""
QWidget {{ background: {window}; color: {text}; }}
/* QFont 警告修复：全局 QSS 不再使用像素字号（font-size:13px）。
   像素字号在 Qt6 样式引擎应用到 pyqtgraph 的 QGraphicsView 时，px→point
   转换在部分环境（Windows/无有效 DPI）会得到 point size = -1，触发
   "QFont::setPointSize: Point size <= 0 (-1)" 告警（伴随坐标轴绘制）。
   全局字号改由 QApplication.setFont 以 point 尺寸提供（Qt 原生路径，
   无 px→pt 转换，不会产生 -1）；控件级局部字号仍可正常使用。*/
QMainWindow, QDialog {{ background: {window}; }}
QMenuBar {{ background: {panel}; border-bottom: 1px solid {border}; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {hover_color}; }}
QMenu {{ background: {panel}; border: 1px solid {border}; }}
QMenu::item {{ padding: 5px 22px 5px 14px; }}
QMenu::item:selected {{ background: {selection}; color: {text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QTabWidget::pane {{ border: 1px solid {border}; top: -1px; }}
QTabBar::tab {{ background: {alt_base}; padding: 6px 16px; border: 1px solid {border}; border-bottom: none; }}
QTabBar::tab:selected {{ background: {accent}; color: {accent_text}; }}
QTabBar::tab:hover:!selected {{ background: {hover_color}; }}
QGroupBox {{ border: 1px solid {border}; border-radius: 6px; margin-top: 10px; padding-top: 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {accent}; }}
QPushButton {{ background: {panel}; border: 1px solid {border}; border-radius: 4px; padding: 4px 12px; }}
QPushButton:hover {{ background: {hover_color}; }}
QPushButton:pressed {{ background: {selection}; }}
QPushButton:checked {{ background: {accent}; color: {accent_text}; border-color: {accent}; }}
QPushButton:disabled {{ color: {muted}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {base}; border: 1px solid {border}; border-radius: 4px; padding: 3px 6px; selection-background-color: {selection};
}}
QComboBox QAbstractItemView {{ background: {base}; border: 1px solid {border}; selection-background-color: {selection}; }}
QCheckBox, QRadioButton {{ background: transparent; spacing: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; }}
QTableWidget, QTableView {{ background: {base}; alternate-background-color: {alt_base}; gridline-color: {border}; border: 1px solid {border}; }}
QHeaderView::section {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}
QScrollBar:vertical {{ background: {alt_base}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; min-height: 24px; border-radius: 6px; }}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar:horizontal {{ background: {alt_base}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {border}; min-width: 24px; border-radius: 6px; }}
QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 4px; }}
QLabel {{ background: transparent; }}
QSplitter::handle {{ background: {border}; }}
"""


def style_plot(plot, theme: str):
    """就地重绘已存在的 PlotWidget 背景与坐标轴，随主题切换。
    移除强制 showGrid(True)——此前主题切换会重新打开网格线，
    覆盖波形页的「无网格线」设置（用户看到「很多跟 X 轴平行的线」）。
    各页面自行维护网格/轴状态：波形页=无网格+轴隐藏，FFT/分布图=按需网格。"""
    colors = THEMES[theme]
    try:
        plot.setBackground(colors["pg_bg"])
        plot_item = plot.getPlotItem()
        for axis_name in ("left", "bottom", "right", "top"):
            axis = plot_item.getAxis(axis_name)
            axis.setPen(pg.mkPen(colors["pg_fg"]))
            axis.setTextPen(pg.mkPen(colors["pg_fg"]))
    except Exception:  # noqa: BLE001
        pass


class ThemeManager(object):
    """全局主题管理：安装 QSS、通知各面板重绘 pyqtgraph 背景。"""

    def __init__(self, app):
        self.app = app
        self.theme = THEME_DARK
        self._panels = []

    def register(self, panel):
        """注册需要就地重绘的绘图面板（WaveformPanel / DistPanel 等）。"""
        if panel is not None and panel not in self._panels:
            self._panels.append(panel)

    def apply(self, theme: str):
        """应用主题：设置 pyqtgraph 配色、全局 QSS 与调色板。

        Args:
            theme: 主题名（THEMES 键）；非法名回退深色主题。

        Returns:
            None。
        """
        if theme not in THEMES:
            theme = THEME_DARK
        self.theme = theme
        set_pg_config(theme)
        self.app.setStyleSheet(qss(theme))
        self._set_palette(theme)
        for panel in self._panels:
            try:
                panel.apply_theme(theme)
            except Exception:  # noqa: BLE001
                pass

    def _set_palette(self, theme: str):
        """同步 QPalette，让依赖 palette() 的控件（如终端文字）随主题变色。"""
        colors = THEMES[theme]
        palette = self.app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors["window"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(colors["base"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["alt_base"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(colors["panel"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["selection"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["panel"]))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
        self.app.setPalette(palette)