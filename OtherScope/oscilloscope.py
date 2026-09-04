# -*- coding: utf-8 -*-
"""示波器波形面板 + FFT 频谱面板（基于 pyqtgraph）。

专业示波器风格（参考 Keysight / Tektronix）：
- 时基(sec/div)、水平位置、通道增益/偏移、边沿触发（自动/常规/单次）。
- Auto 自动设置：按信号频率自动选时基，逐通道自动归中垂直刻度，自动置触发电平。
- 双光标（Δt / ΔY）、自动测量（Vpp/Vmax/Vmin/均值/RMS/频率/周期/上升/下降/占空比/正脉宽）。
- FFT：矩形/汉宁/汉明/布莱克曼窗、dB/线性、零填充、抛物线插值峰值。
- 全界面国际化（简体中文 / English）。
"""

from __future__ import annotations

import math
import os
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, QEvent, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QCheckBox,
    QGroupBox, QColorDialog, QSplitter, QApplication, QLineEdit,
    QMenu, QFileDialog, QMessageBox, QAbstractButton, QSizePolicy,
    QSpinBox)

from .translations import tr, trf
from .rotary_knob import RotaryKnob
from .numeric_controls import PlusMinusBox
from .math_expression import validate as math_validate
from .cursor_measure import CursorManager, MODE_OFF, MODE_MANUAL, MODE_TRACK, MODE_AUTO
from .data_hub import (DataHub, POINT_LIMITS, MAX_POINTS,
                      _dedupe_xy, _fmt_points,
                      first_ch_in_expr)

# BUG-16 修复：原模块级 pg.setConfigOptions 在 import 时污染全局配置，
# 现移到 WaveformPanel.__init__ 中按需设置，避免影响 FFT/分布图及主题切换。

crash_log_dir = os.path.dirname(os.path.abspath(__file__))
_CRASH_LOG_PATH = os.path.join(crash_log_dir, "..", "OtherScope_crash.log")


def _log_refresh_error(where: str, exc: BaseException):
    """把窗口刷新/绘制路径上的未捕获异常写入崩溃日志。

    关键防御：Qt 定时器与 showEvent 中的 Python 异常一旦逃逸到 Qt 事件循环，
    在部分 PySide6 版本会导致整个程序闪退。这里统一捕获并落盘，
    保证单个窗口/控件异常不拖垮整个程序，且可事后定位。
    """
    try:
        import traceback as _tb
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"\n==== 刷新异常 @ {where} ====\n")
            _tb.print_exc(file=fh)
    except Exception:
        pass

TIMEBASE = [("100 µs", 1e-4), ("200 µs", 2e-4), ("500 µs", 5e-4),
            ("1 ms", 1e-3), ("2 ms", 2e-3), ("5 ms", 5e-3), ("10 ms", 1e-2),
            ("20 ms", 2e-2), ("50 ms", 5e-2), ("100 ms", 1e-1), ("200 ms", 2e-1),
            ("500 ms", 5e-1), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0), ("10 s", 10.0)]
DIVS = 10          # 每屏横向 10 格
V_DIVS = 10        # 每屏纵向 10 格（标准示波器：中心为垂直位置0，向上/向下各5格）

# 垂直灵敏度（Volts/Div / Scale）标准 1-2-5 档位序列（1 mV/div ~ 10 V/div）
V_DIV_STEPS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
               1.0, 2.0, 5.0, 10.0]
V_POS_RANGE = 5.0     # 垂直位置（Position）调节范围：±5 div
V_POS_AUTO_CENTER = 3.0  # Auto 叠加模式垂直偏移上限：波形中点保持在屏幕中部 ±3div，避免贴顶/贴底
V_POS_STEP = 0.01     # 垂直位置显示分辨率：0.01 div
# Auto 自动设置防抖/最大化阈值
AUTO_RATIO_MIN = 0.04        # 波形占屏比例下限（低于此则需放大）
AUTO_RATIO_MAX = 0.95        # 波形占屏比例上限（高于此则需缩小）
AUTO_VDIV_TOL = 0.01         # 垂直灵敏度调整容差（相对变化 < 1% 视为无需调整）
AUTO_DEBOUNCE_S = 0.5        # 自动调档防抖间隔（秒）：避免连续触发反复调档
AUTO_EDGE_MARGIN = 0.5       # Auto 峰值/谷值预留 0.5 格过冲观察余量（专业硬约束）

# 兼容旧引用（GAIN_STEPS 已废弃，保留避免导入报错；OFFSET_STEPS 已移除）
GAIN_STEPS = V_DIV_STEPS


def _fmt_vdiv(v):
    """垂直灵敏度格式化：0.001→'1 mV/div'，1.0→'1 V/div'，10.0→'10 V/div'。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = 1.0
    if v >= 1.0:
        s = f"{v:g}"
        return f"{s} V/div"
    millivolt = v * 1000.0
    s = f"{millivolt:g}"
    return f"{s} mV/div"


def _parse_vdiv_text(text):
    """解析垂直灵敏度文本：'50 mV/div'→0.05，'1 V/div'→1.0，纯数字→float。"""
    if text is None:
        return None
    t = str(text).strip().lower().replace(" ", "")
    if not t:
        return None
    import re as _re
    m = _re.match(r"^([-+]?[\d.e]+)(mv|v)?", t)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except (TypeError, ValueError):
        return None
    unit = m.group(2)
    if unit == "mv":
        val /= 1000.0
    return val


# 电压单位列表（所有常用电压单位）
VOLT_UNITS = ["V", "mV", "µV", "nV", "kV", "MV"]

# 单帧绘制的原始点上限：可视窗口内超过该值先大步抽取再 min/max 包络
_DRAW_RAW_MAX = 200_000


def _tb_label(index):
    """把时基旋钮的内部索引映射为真实档位文本（如 100 ms），供旋钮显示。"""
    index = int(round(index))
    index = max(0, min(index, len(TIMEBASE) - 1))
    return TIMEBASE[index][0]


def _downsample(t, y, limit=8000):
    """min/max 包络抽样：每箱保留最小/最大两个点，避免漏尖峰与高频混叠。

    返回点数不超过 limit 且 x 严格递增。

    BUG-13 修复：原实现固定输出 (箱起始时间, 最小值) → (箱结束时间, 最大值)，
    当最小值实际发生在箱末尾、最大值在箱开头时，绘制线段会穿越错误区域。
    现分别记录 min/max 对应的真实采样时刻，并按时间排序每箱两点。
    """
    n = len(t)
    if n <= limit:
        return t, y
    nbins = max(1, limit // 2)
    step = int(np.ceil(n / nbins))
    if step <= 1:
        return t, y
    m = n // step
    if m < 2:
        return t[::step], y[::step]
    t_matrix = t[:m * step].reshape(m, step)
    y_matrix = y[:m * step].reshape(m, step)
    imin = y_matrix.argmin(axis=1)
    imax = y_matrix.argmax(axis=1)
    ymin = y_matrix[np.arange(m), imin]
    y_max = y_matrix[np.arange(m), imax]
    t_min = t_matrix[np.arange(m), imin]
    t_max = t_matrix[np.arange(m), imax]
    # 按时间排序每箱两点，保证 x 严格递增
    min_first = t_min <= t_max
    x0 = np.where(min_first, t_min, t_max)
    x1 = np.where(min_first, t_max, t_min)
    y0 = np.where(min_first, ymin, y_max)
    y1 = np.where(min_first, y_max, ymin)
    x = np.empty(m * 2, dtype=t.dtype)
    out_y = np.empty(m * 2, dtype=y.dtype)
    x[0::2] = x0
    x[1::2] = x1
    out_y[0::2] = y0
    out_y[1::2] = y1
    # 尾部未满箱：必须保留最新样本（实时滚动最关键的数据），否则末端出现缺口
    if n > m * step:
        tail_time = t[m * step:]
        tail_data = y[m * step:]
        if tail_time.size >= 2:
            t_argmin = int(np.argmin(tail_data))
            t_argmax = int(np.argmax(tail_data))
            pair_time = np.array([tail_time[t_argmin], tail_time[t_argmax]])
            pair_data = np.array([tail_data[t_argmin], tail_data[t_argmax]])
            order = np.argsort(pair_time)
            x = np.concatenate([x, pair_time[order]])
            out_y = np.concatenate([out_y, pair_data[order]])
        else:
            x = np.concatenate([x, tail_time[[0]]])
            out_y = np.concatenate([out_y, [tail_data[0]]])
    return x, out_y



def _cross_times(t, y, level, rising=True):
    """返回信号穿越 level 的时刻序列（严格递增时间轴，线性插值细化，向量化）。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.size < 2:
        return np.array([], dtype=float)
    # 标准越阈检测：前一采样点严格在电平一侧，后一采样点到达或越过电平。
    # 使用「严格前、含等后」可同时正确捕获上升（0→L 再向上）与下降（落回 L），
    # 且对恰好平铺在电平上的直流线不产生伪边沿。
    if rising:
        idx = np.flatnonzero((y[:-1] < level) & (y[1:] >= level))
    else:
        idx = np.flatnonzero((y[:-1] > level) & (y[1:] <= level))
    if idx.size == 0:
        return np.array([], dtype=float)
    y0 = y[idx]
    y1 = y[idx + 1]
    denom = y1 - y0
    frac = np.divide(level - y0, denom, out=np.zeros_like(denom), where=denom != 0.0)
    return t[idx] + frac * (t[idx + 1] - t[idx])


def _fmt_time(seconds):
    """把秒数格式化为易读的人类单位（seconds/ms/µs/ns），用于测量读数。"""
    seconds = abs(seconds)
    if seconds >= 1.0:
        return f"{seconds:.4g}seconds"
    if seconds >= 1e-3:
        return f"{seconds * 1e3:.4g}ms"
    if seconds >= 1e-6:
        return f"{seconds * 1e6:.4g}µs"
    return f"{seconds * 1e9:.4g}ns"


def _fmt_freq(freq_hz):
    """把频率格式化为 Hz/kHz/MHz 人类单位，用于测量读数。"""
    freq_hz = abs(freq_hz)
    if freq_hz >= 1e6:
        return f"{freq_hz / 1e6:.4g}MHz"
    if freq_hz >= 1e3:
        return f"{freq_hz / 1e3:.4g}kHz"
    return f"{freq_hz:.4g}Hz"


def _fmt_num(v):
    """自适应数值格式化：保留足够有效数字，避免大直流上微小幅值被吞掉。

    示例：-1.642043e9 与 -1.642047e9 之差 3285 不会被 `.4g` 的四舍五入抹平。
    """
    v = float(v)
    if v != v or v in (float("inf"), float("-inf")):
        return "--"
    if v == 0.0:
        return "0"
    a = abs(v)
    if a >= 1e6 or a < 1e-4:
        return f"{v:.7g}"
    return f"{v:.6g}".rstrip("0").rstrip(".")


def _amp(v, unit):
    """幅值读数：自适应数字 +（可选）单位。"""
    return _fmt_num(v) + (f" {unit}" if unit else "")



class ToggleSwitch(QAbstractButton):
    """左右移动的滑动开关，替代生硬的复选框（复刻现代桌面/移动端 UI）。

    纯 QPainter 绘制轨道 + 白色旋钮，点击/空格键切换，占位小且不会被翻译文本
    撑变形。用于通道「显示」列的启用切换，符合人体工学（更大点击目标）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 22)
        self.setToolTip(tr("scope.col_show"))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        checked = self.isChecked()
        corner_radius = r.height() / 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#00c8ff" if checked else "#4a5560"))
        p.drawRoundedRect(r, corner_radius, corner_radius)
        d = r.height() - 4
        x = r.x() + r.width() - d - 2 if checked else r.x() + 2
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 2, d, d))



class GroundRefItem(pg.GraphicsObject):
    """通道 0V 垂直参考点（Ground Reference Level / 地线基准，示波器专业界面元素）：
    - 屏幕左侧边缘一条带左箭头的短横线，位置 = 该通道 0V 显示值；
    - 垂直位置（Position）变化时随之上下移动（0V 基准跟随）；
    - 短横线上方叠加带通道颜色的通道标签（Channel Identifier，见 _ch_labels）。
    set_ref 已把 item 放到 (x, y)，局部坐标从 (0,0) 向右绘制 len 长。"""
    def __init__(self):
        super().__init__()
        self._color = QColor("#00c8ff")
        self._length = 0.0

    def set_ref(self, x, y, length, color=None):
        try:
            self.setPos(x, y)
        except Exception:  # noqa: BLE001
            pass
        self._length = float(length or 0.0)
        if color is not None:
            self._color = QColor(color)
        try:
            self.prepareGeometryChange()
            self.update()
        except Exception:  # noqa: BLE001
            pass

    def boundingRect(self):
        extend = 16.0
        return QRectF(-extend, -extend, self._length + 2 * extend, 2 * extend)

    def paint(self, p, *args):
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(self._color)
            pen.setWidthF(2.0)
            p.setPen(pen)
            L = self._length
            if L <= 0:
                return
            p.drawLine(QPointF(0.0, 0.0), QPointF(L, 0.0))
            arrow_half = min(L * 0.55, 12.0)
            p.drawLine(QPointF(0.0, 0.0), QPointF(-arrow_half, -arrow_half))
            p.drawLine(QPointF(0.0, 0.0), QPointF(-arrow_half, arrow_half))
        except Exception:  # noqa: BLE001
            pass


class ChannelLabelItem(pg.TextItem):
    """可交互通道标签：
    - 鼠标左键拖动 → 调节垂直位置（Position，div），与标准示波器通道标签拖动一致
    - 鼠标滚轮 → 微调垂直位置（Shift 细调 0.01 div，否则 0.1 div）
    - 操作结果实时同步到通道面板垂直位置栏（_set_v_pos → row.set_offset）
    参考 Tektronix / Keysight / RIGOL 通道标签拖动行为。"""

    def __init__(self, text, color, channel_key, panel, **kwargs):
        super().__init__(text, color=color, **kwargs)
        self.channel_key = channel_key
        self.panel = panel
        self._drag_start_view_y = None
        self._drag_start_vpos = None
        try:
            self.setAcceptHoverEvents(True)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        except Exception:  # noqa: BLE001
            pass

    def _view_y_per_div(self):
        """每 div 对应的 view Y 坐标值 = 主控 V/div ÷ Y轴单位系数。"""
        try:
            main_vd = self.panel._main_v_div()
            y_gain = self.panel._y_mag()
            if y_gain <= 0 or main_vd <= 0:
                return 1.0
            return main_vd / y_gain
        except Exception:  # noqa: BLE001
            return 1.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                view = self.panel.plot.getViewBox()
                scene_pos = event.scenePos()
                self._drag_start_view_y = float(view.mapSceneToView(scene_pos).y())
                spec = self.panel._spec_of(self.channel_key)
                self._drag_start_vpos = float(spec.get("v_pos", 0.0))
            except Exception:  # noqa: BLE001
                self._drag_start_view_y = None
            event.accept()
        else:
            try:
                super().mousePressEvent(event)
            except Exception:  # noqa: BLE001
                pass

    def mouseMoveEvent(self, event):
        if self._drag_start_view_y is not None:
            try:
                view = self.panel.plot.getViewBox()
                cur_view_y = float(view.mapSceneToView(event.scenePos()).y())
                delta_div = (cur_view_y - self._drag_start_view_y) / self._view_y_per_div()
                v_pos = self._drag_start_vpos + delta_div
                self.panel._set_v_pos(self.channel_key, v_pos)
            except Exception:  # noqa: BLE001
                pass
            event.accept()
        else:
            try:
                super().mouseMoveEvent(event)
            except Exception:  # noqa: BLE001
                pass

    def mouseReleaseEvent(self, event):
        self._drag_start_view_y = None
        self._drag_start_vpos = None
        event.accept()

    def wheelEvent(self, event):
        try:
            delta = event.angleDelta().y() / 120.0
            step = 0.01 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 0.1
            spec = self.panel._spec_of(self.channel_key)
            v_pos = float(spec.get("v_pos", 0.0)) + delta * step
            self.panel._set_v_pos(self.channel_key, v_pos)
        except Exception:  # noqa: BLE001
            pass
        event.accept()


class TimeOriginItem(pg.GraphicsObject):
    """水平时间参考点（Horizontal Time Reference / 触发点 / 时基原点）：
    屏幕顶部一条带向下箭头的短竖线，位置 = 当前显示窗口水平中心。
    水平位置=0 时触发点位于屏幕中央，是波形左右平移的基准。"""
    def __init__(self):
        super().__init__()
        self._color = QColor("#ff9f1c")
        self._length = 0.0

    def set_ref(self, x, y, length):
        try:
            self.setPos(x, y)
        except Exception:  # noqa: BLE001
            pass
        self._length = float(length or 0.0)
        try:
            self.prepareGeometryChange()
            self.update()
        except Exception:  # noqa: BLE001
            pass

    def boundingRect(self):
        extend = 16.0
        return QRectF(-extend, -extend, 2 * extend, self._length + 2 * extend)

    def paint(self, p, *args):
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(self._color)
            pen.setWidthF(2.0)
            p.setPen(pen)
            L = self._length
            if L <= 0:
                return
            p.drawLine(QPointF(0.0, 0.0), QPointF(0.0, -L))
            arrow_half = min(L * 0.55, 12.0)
            p.drawLine(QPointF(0.0, 0.0), QPointF(-arrow_half, arrow_half))
            p.drawLine(QPointF(0.0, 0.0), QPointF(arrow_half, arrow_half))
        except Exception:  # noqa: BLE001
            pass


class ChannelRow(QWidget):
    """单通道行控件集合：显示开关 + 通道名 + 耦合 + 垂直灵敏度(V/div) + 垂直位置(div)
    + 单位 + 颜色。不持有自身布局——控件由 _rebuild_channel_table 放入
    与表头共用的 QGridLayout，保证「控件值 ↔ 列标题」逐列对齐、列宽随控件值自适应。
    本类仅作为控件持有者，保留原 set_scale / set_offset 等 API。"""

    def __init__(self, ch, info, parent=None):
        super().__init__(parent)
        self.ch = ch
        self._build(info)

    def _build(self, info):
        # 显示开关（42×22 固定）
        # 数学通道用 visible（波形显示开关），物理通道用 enabled（通道存在开关）
        self.switch = ToggleSwitch()
        self.switch.setChecked(info.get("visible", info.get("enabled", True)))

        # 通道名
        self.lb_name = QLabel(info["name"])
        self.lb_name.setStyleSheet(f"color:{info['color']};font-weight:bold;")
        self.lb_name.setMinimumWidth(50)

        # 耦合
        self.cb_coup = QComboBox()
        self.cb_coup.addItem("AC", "ac")
        self.cb_coup.addItem("DC", "dc")
        self.cb_coup.setCurrentIndex(0 if info.get("coupling") == "ac" else 1)
        self.cb_coup.setMinimumWidth(55)
        self.cb_coup.setToolTip(tr("scope.coup_tip"))
        self.cb_coup.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # 垂直灵敏度（Volts/Div / Scale，标准 1-2-5 序列，可编辑）
        # 可编辑 QComboBox 的 AdjustToContents 只按 lineEdit 内容算宽、
        # 不包含下拉按钮，会导致下拉箭头被遮挡。改为手动按「内容+箭头+边距」算宽，
        # 值变化（含用户手动输入）时列宽跟随 → 下拉箭头始终完整显示。
        self.cb_scale = QComboBox()
        self.cb_scale.setToolTip(tr("scope.scale_tip"))
        self.cb_scale.setEditable(True)
        self.cb_scale.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for v in V_DIV_STEPS:
            self.cb_scale.addItem(_fmt_vdiv(v), v)
        self.cb_scale.currentTextChanged.connect(
            lambda t, cb=self.cb_scale: self._fit_combo_width(cb, t))
        self.set_scale(info.get("v_div", info.get("scale", 1.0)))

        # 垂直位置（Position，单位 div）——标准示波器为连续旋转、无固定档位，
        # 因此使用连续数值输入框（PlusMinusBox）：范围 ±5 div、分辨率 0.01 div、
        # 默认 0、可滚轮连续微调、可输入极值范围内任意值。无需下拉列表。
        self.cb_off = PlusMinusBox(-V_POS_RANGE, V_POS_RANGE, 0.0,
                                   decimals=2, step=V_POS_STEP, suffix=" div")
        self.cb_off.setMinimumWidth(90)
        self.set_offset(info.get("v_pos", info.get("offset", 0.0)))
        if info.get("coupling") == "ac":
            self.cb_off.setEnabled(False)

        # 单位（可编辑下拉，宽度随内容调整，同样含下拉箭头余量）
        self.cb_unit = QComboBox()
        self.cb_unit.setToolTip(tr("scope.unit_tip"))
        self.cb_unit.setEditable(True)
        self.cb_unit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for u in VOLT_UNITS:
            self.cb_unit.addItem(u)
        self.cb_unit.currentTextChanged.connect(
            lambda t, cb=self.cb_unit: self._fit_combo_width(cb, t))
        self.set_unit(info.get("unit", "V"))

        # 颜色按钮
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(28, 22)
        self.btn_color.setStyleSheet(
            "background:%s;border:1px solid #2a2f3a;border-radius:3px;" % info["color"])
        self.btn_color.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_color.setToolTip(tr("scope.color_tip"))

    def _fit_combo_width(self, combo, text):
        """可编辑下拉宽度 = 内容文本 + 下拉按钮 + 内边距 + 留白。
        保证「1 V/div」等值 + 下拉箭头完整显示（R4 的 46px 在部分
        字体/QSS 下仍偏紧），余量加大至 60；并让下拉按内容撑满列宽。"""
        try:
            font_metrics = combo.fontMetrics()
            w = int(font_metrics.horizontalAdvance(str(text or ""))) + 60
            combo.setMinimumWidth(max(w, 76))
        except Exception:  # noqa: BLE001
            combo.setMinimumWidth(100)

    def set_scale(self, v):
        """设置垂直灵敏度（V/div）。"""
        self.cb_scale.blockSignals(True)
        txt = _fmt_vdiv(v)
        idx = self.cb_scale.findText(txt)
        if idx >= 0:
            self.cb_scale.setCurrentIndex(idx)
        else:
            self.cb_scale.setCurrentText(txt)
        self.cb_scale.blockSignals(False)
        self._fit_combo_width(self.cb_scale, self.cb_scale.currentText())

    def set_offset(self, v):
        """设置垂直位置（div），连续数值输入（±5，0.01 分辨率）。"""
        try:
            self.cb_off.setValue(float(v))
        except (TypeError, ValueError):
            self.cb_off.setValue(0.0)

    def set_unit(self, unit):
        """同步通道单位下拉框（外部如测量面板更改单位时调用）。"""
        self.cb_unit.blockSignals(True)
        idx = self.cb_unit.findText(unit)
        if idx >= 0:
            self.cb_unit.setCurrentIndex(idx)
        else:
            self.cb_unit.setCurrentText(unit)
        self.cb_unit.blockSignals(False)
        self._fit_combo_width(self.cb_unit, self.cb_unit.currentText())

    def set_color(self, color):
        self.btn_color.setStyleSheet(
            f"background:{color};border:1px solid #2a2f3a;border-radius:3px;")
        self.lb_name.setStyleSheet(f"color:{color};font-weight:bold;")

    def set_coupling(self, coupling):
        self.cb_coup.blockSignals(True)
        self.cb_coup.setCurrentIndex(0 if coupling == "ac" else 1)
        self.cb_coup.blockSignals(False)
        self.cb_off.setEnabled(coupling != "ac")
        if coupling == "ac":
            self.set_offset(0.0)


class WaveformPanel(QWidget):
    """实时波形显示：时基、垂直调节、触发、光标、自动测量、数据导出。

    架构（DataHub 数据总线）：
    - 所有数据（原始/耦合缓冲、通道配置、数学通道、版本、时间零点、数据上限）
      统一由 ``self.dh``（DataHub）持有，本面板是数据的**只读消费方 + 显示方**；
    - 串口终端把每一帧唯一写入 ``dh.append_frame()``，波形/FFT/分布图三个窗口
      各自从 dh 只读取数、独立刷新，彼此互不引用；
    - 面板内部对 ``self.channels/_t/_y/_yc/version/t0/max_points`` 等数据属性的
      读写通过属性转发自动落到 ``self.dh``，实现真正单一数据源。
    """

    cleared = Signal()      # 清屏时发出，供主窗口同步清空原始行缓冲
    channels_changed = Signal()  # 通道启停变化，供主窗口同步 FFT/分布图通道下拉

    # 稳定测量键 -> i18n key（顺序即布局顺序）
    _MEAS_ROWS = [
        ("vpp", "scope.meas_vpp"), ("vmax", "scope.meas_vmax"),
        ("vmin", "scope.meas_vmin"), ("high", "scope.meas_high"),
        ("low", "scope.meas_low"), ("amp", "scope.meas_amp"),
        ("mean", "scope.meas_mean"), ("rms", "scope.meas_rms"),
        ("std", "scope.meas_std"), ("over", "scope.meas_over"),
        ("pre", "scope.meas_pre"), ("freq", "scope.meas_freq"),
        ("period", "scope.meas_period"), ("rise", "scope.meas_rise"),
        ("fall", "scope.meas_fall"), ("duty", "scope.meas_duty"),
        ("width", "scope.meas_width"), ("neg_width", "scope.meas_neg_width"),
        ("trig", "scope.meas_trig"),
        ("area", "scope.meas_area"), ("slew_rise", "scope.meas_slew_rise"),
        ("slew_fall", "scope.meas_slew_fall"), ("cyc_rms", "scope.meas_cyc_rms"),
        ("cyc_mean", "scope.meas_cyc_mean"),
    ]

    # ---------------------------------------------------------------- DataHub 数据转发
    # 数据属性（唯一数据源）通过显式引用 / property 与 DataHub 共享。
    # 不使用 __getattr__/__setattr__ 魔法转发（避免与 PySide6 元对象系统交互冲突，
    # 曾导致点击其它窗口时程序闪退）。

    @property
    def version(self):
        return self.dh.version

    @version.setter
    def version(self, v):
        self.dh.version = v

    @property
    def t0(self):
        return self.dh.t0

    @t0.setter
    def t0(self, v):
        self.dh.t0 = v

    @property
    def max_points(self):
        return self.dh.max_points

    @max_points.setter
    def max_points(self, v):
        self.dh.max_points = v

    # 兼容转发：数据上限变化信号改由 DataHub 统一发出
    @property
    def max_points_changed(self):
        return self.dh.max_points_changed

    def __init__(self, dh=None, parent=None):
        # 先建立数据总线引用（super().__init__ 之前），保证构造期间数据属性可用。
        # 注意：PySide6 ≥6.9 起 QWidget 子类在 super().__init__() 之前调用
        # object.__setattr__ 会抛 "can't apply this __setattr__"，因此改用普通赋值。
        self.dh = dh if dh is not None else DataHub()
        super().__init__(parent)
        # BUG-16 修复：pg 全局配置移到此处按需设置，避免 import 时污染全局
        pg.setConfigOptions(antialias=False, background="#0f1115", foreground="#d8dee9")
        # ---- 数据属性：显式引用 DataHub 的容器（单一数据源，天然共享，零魔法） ----
        self.channels = self.dh.channels   # ch(int) -> dict(通道配置规格)
        self._t = self.dh._t               # ch -> _Buf(时间)
        self._y = self.dh._y               # ch -> _Buf(原始电压)
        self._y_coupled = self.dh._y_coupled             # ch -> _Buf(耦合电压，所有功能统一数据源)
        self.maths = self.dh.maths         # m1..m4 数学通道配置
        self._math_t = self.dh._math_t     # 数学通道结果（numpy 数组）
        self._math_y = self.dh._math_y
        self._math_y_coupled = self.dh._math_y_coupled
        self._math_expr_error = self.dh._math_expr_error
        # ---- 面板自身 UI/显示状态（不进入数据总线） ----
        self.curves = {}
        self.running = True
        self.mode = "auto"          # auto / normal(触发) / single(单次)
        self.single_armed = False
        self.single_done = False
        self._drag_cursor = None
        self._last_click_pos = None
        self._scale_spins = {}      # ch -> PlusMinusBox（增益）
        self._offset_spins = {}     # ch -> PlusMinusBox（垂直位置 Position）
        self._meas_name_labels = {} # key -> QLabel（名称）
        self._dirty = True          # 有新数据需重绘
        self._view_dirty = True     # 有显示参数变化需重绘（暂停/单次冻结时仍要响应）
        self._frame_since_measure = 0
        self._last_window = None    # (x0, x1) 最近一次绘制的可视窗口（相对秒）
        self._last_hpos = 0.0       # 最近一次绘制时使用的水平位置（相对秒）
        self.h_pos = 0.0            # 水平位置/延迟（秒），正值回看更早数据
        self._auto_separate = False # Auto 通道分离排列标志（多通道时启用，Keysight Autoscale 风格）
        self._arr_cache = {}        # ch -> (version, t_rel, y) 显示缓存
        self._trig_arm_t = None     # 单次布防时的相对时间标线，用于只捕获新触发沿
        self.v_unit = "V"           # 信号幅值单位（默认伏特，测量读数与纵轴一致）
        self._auto_no_trig_count = 0  # Auto模式连续无触发计数，超过阈值fallback到滚动
        self._last_stable_trig = None  # Auto模式上一次稳定触发点（防抖用）

        # ---- 显示模式 + 余辉 ----
        self.display_mode = "vector"      # vector（矢量线）/ dot（点阵）
        self.persist_mode = "off"         # off / variable / infinite
        self.persist_time = 1.0           # 可变余辉时间（秒），控制幽灵帧衰减速率
        self._ghosts = {}                 # ch -> list[(alpha, t_ghost, y_ghost)] 余辉叠加帧

        self._build_ui()
        # BUG-G 修复：构造完成后立即填充触发源/测量通道/光标通道下拉框，
        # 否则初次打开波形页时这些下拉为空，Auto 触发源设置也会失败。
        self._repopulate_combos()
        self.retranslate()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(50)   # 20 fps：示波器刷新足够顺滑，且显著降低 CPU 占用
        # 自动测量用低频独立定时器，避免每帧都做 ptp/mean/period 等重计算
        self._measure_timer = QTimer(self)
        self._measure_timer.timeout.connect(self._on_measure_timer)
        self._measure_timer.start(300)
        # 数据总线：新数据写入（append_frame/bulk_add/clear/setup_channels）统一
        # 通过 data_updated 信号标记重绘，保证波形与串口数据实时同步（唯一数据源）。
        self.dh.data_updated.connect(self._on_dh_data_updated)
        # 自动垂直灵敏度（默认开启，波形与屏幕严重不匹配时自动 1-2-5 选档，
        # 使用户手动调 V/div 或按 Auto 后停止）
        self._vdiv_auto = True
        self._last_vdiv_auto_t = 0.0

    def _on_dh_data_updated(self, _version):
        """DataHub 数据版本变化（新帧/清屏/重算）→ 标记波形需要重绘。"""
        self._dirty = True

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 顶部控制条
        top_bar = QHBoxLayout()
        self.lb_timebase = QLabel()
        top_bar.addWidget(self.lb_timebase)
        self.cb_timebase = QComboBox()
        for label, _ in TIMEBASE:
            self.cb_timebase.addItem(label + "/div")
        self.cb_timebase.setCurrentText("100 ms/div")
        self.cb_timebase.setToolTip(tr("scope.timebase_tip"))
        self.cb_timebase.currentIndexChanged.connect(self._on_timebase)
        top_bar.addWidget(self.cb_timebase)

        self.btn_auto = QPushButton()
        self.btn_auto.clicked.connect(self._on_auto)
        top_bar.addWidget(self.btn_auto)

        top_bar.addSpacing(8)
        self.lb_limit = QLabel()
        top_bar.addWidget(self.lb_limit)
        self.cb_limit = QComboBox()
        for label, val in POINT_LIMITS:
            self.cb_limit.addItem(label, val)
        self.cb_limit.setCurrentIndex(2)   # 默认 100 K
        self.cb_limit.currentIndexChanged.connect(self._on_limit_changed)
        top_bar.addWidget(self.cb_limit)
        self.lb_limit_hint = QLabel()
        self.lb_limit_hint.setStyleSheet("color:#9aa4b2;")
        top_bar.addWidget(self.lb_limit_hint)

        top_bar.addSpacing(8)
        self.lb_refresh = QLabel()
        top_bar.addWidget(self.lb_refresh)
        self.sp_refresh = PlusMinusBox(1.0, 60.0, 20.0, decimals=0, step=1.0, suffix=" Hz")
        self.sp_refresh.valueChanged.connect(self._on_refresh_changed)
        top_bar.addWidget(self.sp_refresh)

        top_bar.addSpacing(12)
        self.lb_trigger = QLabel()
        top_bar.addWidget(self.lb_trigger)
        self.cb_trig_mode = QComboBox()
        self.cb_trig_mode.setToolTip(tr("scope.trig_mode_tip"))
        self.cb_trig_mode.currentIndexChanged.connect(self._on_trig_mode)
        top_bar.addWidget(self.cb_trig_mode)

        self.cb_trig_type = QComboBox()
        self.cb_trig_type.setToolTip(tr("scope.trig_type_tip"))
        self.cb_trig_type.addItem("Edge", "edge")
        self.cb_trig_type.addItem("Pulse Width", "pulse")
        self.cb_trig_type.addItem("Runt", "runt")
        self.cb_trig_type.currentIndexChanged.connect(self._on_trig_type)
        top_bar.addWidget(self.cb_trig_type)

        self.cb_trig_src = QComboBox()
        self.cb_trig_src.setToolTip(tr("scope.trig_src_tip"))
        self.cb_trig_src.currentIndexChanged.connect(lambda *_: self._on_trig_src_changed())
        top_bar.addWidget(self.cb_trig_src)
        self.cb_trig_edge = QComboBox()
        self.cb_trig_edge.setToolTip(tr("scope.trig_edge_tip"))
        self.cb_trig_edge.currentIndexChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.cb_trig_edge)
        self.lb_level = QLabel()
        top_bar.addWidget(self.lb_level)
        self.sp_trig_level = PlusMinusBox(-10.0, 10.0, 0.0, decimals=3, step=0.05)
        self.sp_trig_level.valueChanged.connect(self._on_trig_spin)
        top_bar.addWidget(self.sp_trig_level)

        # 脉宽触发参数：条件（> 宽于 / < 窄于）+ 脉宽阈值
        self.lb_pw = QLabel()
        top_bar.addWidget(self.lb_pw)
        self.cb_pw_cond = QComboBox()
        self.cb_pw_cond.setToolTip(tr("scope.pw_cond_tip"))
        self.cb_pw_cond.addItem(">", "greater")
        self.cb_pw_cond.addItem("<", "less")
        self.cb_pw_cond.currentIndexChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.cb_pw_cond)
        self.sp_pw_width = PlusMinusBox(1e-9, 100.0, 1e-3, decimals=6, step=1e-4, suffix=" s")
        self.sp_pw_width.valueChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.sp_pw_width)
        # 欠幅触发参数：高阈值（低阈复用触发电平）
        self.sp_runt_hi = PlusMinusBox(-10.0, 10.0, 2.0, decimals=3, step=0.05)
        self.sp_runt_hi.valueChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.sp_runt_hi)
        # 超时触发参数：状态（高于/低于电平）+ 超时时长
        self.lb_to = QLabel()
        top_bar.addWidget(self.lb_to)
        self.cb_to_state = QComboBox()
        self.cb_to_state.setToolTip(tr("scope.to_state_tip"))
        self.cb_to_state.addItem("Above", "above")
        self.cb_to_state.addItem("Below", "below")
        self.cb_to_state.currentIndexChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.cb_to_state)
        self.sp_to_time = PlusMinusBox(1e-9, 100.0, 1e-3, decimals=6, step=1e-4, suffix=" s")
        self.sp_to_time.valueChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.sp_to_time)
        # 窗口触发参数：上限 / 下限（信号进入/退出该电压窗口）
        self.lb_win = QLabel()
        top_bar.addWidget(self.lb_win)
        self.sp_win_hi = PlusMinusBox(-10.0, 10.0, 2.0, decimals=3, step=0.05)
        self.sp_win_hi.valueChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.sp_win_hi)
        self.sp_win_lo = PlusMinusBox(-10.0, 10.0, -2.0, decimals=3, step=0.05)
        self.sp_win_lo.valueChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.sp_win_lo)
        # 上升/下降时间触发参数：边沿转换耗时阈值
        self.lb_rt = QLabel()
        top_bar.addWidget(self.lb_rt)
        self.sp_rt_time = PlusMinusBox(1e-9, 100.0, 1e-3, decimals=6, step=1e-4, suffix=" s")
        self.sp_rt_time.valueChanged.connect(lambda *_: self._mark_dirty())
        top_bar.addWidget(self.sp_rt_time)
        self._update_trig_param_visibility()

        top_bar.addSpacing(12)
        self.btn_run = QPushButton()
        self.btn_run.setToolTip(tr("scope.run_tip"))
        self.btn_run.setCheckable(True)
        self.btn_run.setChecked(True)
        self.btn_run.toggled.connect(self._on_run)
        top_bar.addWidget(self.btn_run)
        self.btn_single = QPushButton()
        self.btn_single.setToolTip(tr("scope.single_tip"))
        self.btn_single.clicked.connect(self._on_single)
        top_bar.addWidget(self.btn_single)
        self.btn_clear = QPushButton()
        self.btn_clear.setToolTip(tr("scope.clear_tip"))
        self.btn_clear.clicked.connect(self.clear)
        top_bar.addWidget(self.btn_clear)
        self.btn_csv = QPushButton()
        self.btn_csv.setToolTip(tr("scope.csv_tip"))
        self.btn_csv.clicked.connect(self.export_csv)
        top_bar.addWidget(self.btn_csv)
        top_bar.addStretch(1)
        self.lb_status = QLabel()
        top_bar.addWidget(self.lb_status)
        root.addLayout(top_bar)

        # 旋钮控制区：三旋钮一行（旋钮左、实时值上/名称下右），操作提示居中置于第 2 个旋钮正下方
        knob_zone = QGridLayout()
        knob_zone.setContentsMargins(0, 0, 0, 0)
        knob_zone.setHorizontalSpacing(48)
        knob_zone.setVerticalSpacing(4)
        self.knob_tb = RotaryKnob("Timebase", 0, len(TIMEBASE) - 1, 9, "/div",
                                  decimals=0, format_str=_tb_label)
        self.knob_tb.valueChanged.connect(self._on_knob_timebase)
        knob_zone.addWidget(self.knob_tb, 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.knob_trig = RotaryKnob("Trig Level", -10.0, 10.0, 0.0, decimals=3)
        self.knob_trig.valueChanged.connect(self._on_knob_trig_level)
        knob_zone.addWidget(self.knob_trig, 0, 1, Qt.AlignmentFlag.AlignLeft)
        self.knob_hpos = RotaryKnob("H Pos", -0.5, 0.5, 0.0, "", decimals=3,
                                    format_str=self._hpos_fmt)
        self.knob_hpos.valueChanged.connect(self._on_knob_hpos)
        knob_zone.addWidget(self.knob_hpos, 0, 2, Qt.AlignmentFlag.AlignLeft)
        knob_zone.setColumnStretch(3, 1)   # 右侧留白，三旋钮保持左对齐
        self.lb_knob_help = QLabel()
        self.lb_knob_help.setStyleSheet("color:#9aa4b2;")
        self.lb_knob_help.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lb_knob_help.setWordWrap(False)          # 整行显示、不换行
        # 与第一个旋钮左对齐
        knob_zone.addWidget(self.lb_knob_help, 1, 0, 1, 3,
                            Qt.AlignmentFlag.AlignLeft)
        root.addLayout(knob_zone)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.split = split   # 光标模式切换时保持左右比例

        # 左侧：通道表 + 测量
        left = QWidget()
        left.setMinimumWidth(510)   # 通道面板宽度初始值 = 完整显示 7 列（截图实测）
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.group_ch = QGroupBox()
        # 表头与通道行控件放入同一个 QGridLayout，列由 grid 统一控制 →
        # 列宽严格对齐、随控件值自动调整，彻底修复「表头与控件错位」。
        # 分页显示——完全无滚动条，面板高度自适应，每页最多5个通道，
        #   通道数>5时显示分页控件（上一页/下一页/手动页码），通道数<=5时隐藏分页控件。
        grp_layout = QVBoxLayout(self.group_ch)
        grp_layout.setContentsMargins(0, 0, 0, 0)
        grp_layout.setSpacing(2)
        # 通道表容器（QWidget + QGridLayout，高度自适应，无滚动条）
        ch_container = QWidget()
        channel_grid = QGridLayout(ch_container)
        channel_grid.setContentsMargins(4, 4, 4, 4)
        channel_grid.setSpacing(4)
        self.ch_container = ch_container
        grp_layout.addWidget(ch_container)
        # 分页控件行（通道数>5时显示）
        self._page_size = 5
        self._current_page = 0  # 0-based
        page_row_layout = QHBoxLayout()
        page_row_layout.setContentsMargins(4, 0, 4, 4)
        page_row_layout.setSpacing(4)
        self.btn_first_page = QPushButton(tr("scope.page_first"))
        self.btn_first_page.setToolTip(tr("scope.page_first_tip"))
        self.btn_first_page.clicked.connect(self._on_first_page)
        self.btn_prev_page = QPushButton(tr("scope.page_prev"))
        self.btn_prev_page.setToolTip(tr("scope.page_prev_tip"))
        self.btn_prev_page.clicked.connect(self._on_prev_page)
        self.btn_next_page = QPushButton(tr("scope.page_next"))
        self.btn_next_page.setToolTip(tr("scope.page_next_tip"))
        self.btn_next_page.clicked.connect(self._on_next_page)
        self.btn_last_page = QPushButton(tr("scope.page_last"))
        self.btn_last_page.setToolTip(tr("scope.page_last_tip"))
        self.btn_last_page.clicked.connect(self._on_last_page)
        self.spin_page = QSpinBox()
        self.spin_page.setMinimum(1)
        self.spin_page.setMaximum(1)
        self.spin_page.setMaximumWidth(60)
        self.spin_page.setToolTip(tr("scope.page_spin_tip"))
        self.spin_page.valueChanged.connect(self._on_page_spin_changed)
        self.lbl_page_total = QLabel("/ 1")
        self.lbl_page_total.setStyleSheet("color:#9aa4b2;font-size:11px;")
        self.lbl_channel_count = QLabel("")
        self.lbl_channel_count.setStyleSheet("color:#9aa4b2;font-size:11px;")
        page_row_layout.addWidget(self.btn_prev_page)
        page_row_layout.addWidget(self.spin_page)
        page_row_layout.addWidget(self.lbl_page_total)
        page_row_layout.addStretch(1)
        page_row_layout.addWidget(self.lbl_channel_count)
        page_row_layout.addWidget(self.btn_next_page)
        self.page_row_widget = QWidget()
        page_row_layout = QHBoxLayout(self.page_row_widget)
        page_row_layout.setContentsMargins(4, 0, 4, 4)
        page_row_layout.setSpacing(4)
        page_row_layout.addWidget(self.btn_first_page)
        page_row_layout.addWidget(self.btn_prev_page)
        page_row_layout.addWidget(self.spin_page)
        page_row_layout.addWidget(self.lbl_page_total)
        page_row_layout.addStretch(1)
        page_row_layout.addWidget(self.lbl_channel_count)
        page_row_layout.addWidget(self.btn_next_page)
        page_row_layout.addWidget(self.btn_last_page)
        self.page_row_widget.setVisible(False)
        grp_layout.addWidget(self.page_row_widget)
        headers = ["scope.col_show", "scope.col_ch", "scope.col_coupling",
                   "scope.col_gain", "scope.col_offset", "scope.col_unit", "scope.col_color"]
        self.ch_header_labels = []
        for col, key in enumerate(headers):
            header_label = QLabel(tr(key))
            # 表头标题与内容列左对齐——表头文字左缘 = 控件左缘，
            # 彻底解决「表头居中 vs 内容左对齐」导致的各列间距不一致问题。
            header_label.setAlignment(Qt.AlignmentFlag.AlignLeft
                                      | Qt.AlignmentFlag.AlignVCenter)
            header_label.setStyleSheet("color:#9aa4b2;font-size:11px;")
            self.ch_header_labels.append(header_label)
            channel_grid.addWidget(header_label, 0, col)
        for c in range(len(headers)):
            channel_grid.setColumnStretch(c, 0)   # 0 = 按内容自适应（列宽随控件值）
        self.ch_grid = channel_grid               # QGridLayout（表头第0行 + 每通道1行）
        self._channel_rows = {}         # ch -> ChannelRow
        left_layout.addWidget(self.group_ch)

        self.grp_meas = QGroupBox()
        meas_layout = QGridLayout(self.grp_meas)
        self.lb_meas_ch = QLabel()
        meas_layout.addWidget(self.lb_meas_ch, 0, 0)
        self.cb_meas_ch = QComboBox()
        self.cb_meas_ch.setToolTip(tr("scope.meas_ch_tip"))
        self.cb_meas_ch.currentIndexChanged.connect(lambda *_: self._on_meas_ch_changed())
        meas_layout.addWidget(self.cb_meas_ch, 0, 1)
        self.lb_unit = QLabel()
        meas_layout.addWidget(self.lb_unit, 0, 2)
        self.ed_unit = QLineEdit()
        self.ed_unit.setMaximumWidth(72)
        self.ed_unit.setReadOnly(True)  # 单位唯一来源是通道列表，自动测量单位只读
        self.ed_unit.setPlaceholderText(tr("scope.unit_ph"))
        self.ed_unit.setToolTip(tr("scope.unit_tip"))
        meas_layout.addWidget(self.ed_unit, 0, 3)
        self.ed_unit.setText(self.v_unit)   # 默认单位 V，保证测量读数恒带单位
        self.meas_labels = {}
        for pos, (key, _i18n) in enumerate(self._MEAS_ROWS):
            r = pos // 2 + 1
            c = (pos % 2) * 2
            name_lab = QLabel()
            self._meas_name_labels[key] = name_lab
            meas_layout.addWidget(name_lab, r, c)
            lab = QLabel("--")
            self.meas_labels[key] = lab
            meas_layout.addWidget(lab, r, c + 1)
        left_layout.addWidget(self.grp_meas)

        # 数学通道 M1-M4：自定义表达式，可测量/可做触发源
        self.grp_math = QGroupBox()
        math_layout = QGridLayout(self.grp_math)
        math_layout.setContentsMargins(4, 4, 4, 4)
        self._math_rows = {}        # key -> dict(行控件: checkbox/line_edit/btn)
        for i in range(4):
            key = f"m{i + 1}"
            r = i
            checkbox = QCheckBox()
            checkbox.toggled.connect(lambda on, k=key: self._on_math_enabled(k, on))
            math_layout.addWidget(checkbox, r, 0)
            line_edit = QLineEdit()
            line_edit.setPlaceholderText(tr("scope.math_ph"))
            line_edit.setClearButtonEnabled(True)
            line_edit.setToolTip(tr("scope.math_tip"))
            line_edit.editingFinished.connect(
                lambda k=key, e=line_edit: self._on_math_expr_edited(k, e.text()))
            math_layout.addWidget(line_edit, r, 1)
            btn = QPushButton()
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda _, k=key: self._pick_math_color(k))
            math_layout.addWidget(btn, r, 2)
            self._math_rows[key] = dict(checkbox=checkbox, line_edit=line_edit, btn=btn)
        self.lb_math_note = QLabel()
        self.lb_math_note.setWordWrap(True)
        self.lb_math_note.setStyleSheet("color:#9aa4b2;font-size:11px;")
        math_layout.addWidget(self.lb_math_note, 4, 0, 1, 3)
        left_layout.addWidget(self.grp_math)
        left_layout.addStretch(1)

        # 光标说明
        self.lbl_cur = QLabel()
        self.lbl_cur.setWordWrap(True)
        left_layout.addWidget(self.lbl_cur)

        split.addWidget(left)

        # 右侧：波形图（顶部一行放置显示/余辉/光标按钮，波形占剩余空间）
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)
        # 显示模式
        self.lb_display = QLabel()
        ctrl_bar.addWidget(self.lb_display)
        self.cb_display = QComboBox()
        self.cb_display.setToolTip(tr("scope.display_tip"))
        self.cb_display.addItem("Vector", "vector")
        self.cb_display.addItem("Dots", "dot")
        self.cb_display.currentIndexChanged.connect(self._on_display_mode)
        ctrl_bar.addWidget(self.cb_display)

        ctrl_bar.addSpacing(10)

        # 光标开关按钮：X A/B（时间竖线）、Y A/B（幅度横线）
        # 光标开关按钮初始为非选中：光标模式默认「关闭(OFF)」，按钮应与模式一致
        self.btn_cursor_xa = self._make_cursor_btn("scope.cursor_xa_tip", False)
        self.btn_cursor_xb = self._make_cursor_btn("scope.cursor_xb_tip", False)
        self.btn_cursor_ya = self._make_cursor_btn("scope.cursor_ya_tip", False)
        self.btn_cursor_yb = self._make_cursor_btn("scope.cursor_yb_tip", False)
        ctrl_bar.addWidget(self.btn_cursor_xa)
        ctrl_bar.addWidget(self.btn_cursor_xb)
        ctrl_bar.addWidget(self.btn_cursor_ya)
        ctrl_bar.addWidget(self.btn_cursor_yb)

        ctrl_bar.addSpacing(10)

        # 光标模式 / 源 / 高级功能（合并到同一行）
        self.lb_cur_mode = QLabel()
        ctrl_bar.addWidget(self.lb_cur_mode)
        self.cb_cursor_mode = QComboBox()
        self.cb_cursor_mode.setToolTip(tr("scope.cursor_mode_tip"))
        ctrl_bar.addWidget(self.cb_cursor_mode)
        self.lb_cur_src = QLabel()
        ctrl_bar.addWidget(self.lb_cur_src)
        self.cb_cursor_src = QComboBox()
        self.cb_cursor_src.setToolTip(tr("scope.cursor_src_tip"))
        ctrl_bar.addWidget(self.cb_cursor_src)
        ctrl_bar.addSpacing(8)
        # 光标源选择标志：记录用户是否手动选择过（程序合成选择不算），
        # 未手动选择时始终默认 ch1，避免初始化/格式切换时光标源停在数学通道
        self._cursor_src_touched = False
        self._cursor_src_synth = False
        self.btn_track_scaling = QPushButton()
        self.btn_track_scaling.setCheckable(True)
        ctrl_bar.addWidget(self.btn_track_scaling)
        self.btn_coupling = QPushButton()
        self.btn_coupling.setCheckable(True)
        ctrl_bar.addWidget(self.btn_coupling)
        self.btn_set_wave = QPushButton()
        ctrl_bar.addWidget(self.btn_set_wave)
        self.btn_set_screen = QPushButton()
        ctrl_bar.addWidget(self.btn_set_screen)

        ctrl_bar.addSpacing(10)

        # 光标操作提示
        self.lb_cur_keys = QLabel()
        self.lb_cur_keys.setStyleSheet("color:#9aa4b2;")
        self.lb_cur_keys.setWordWrap(False)
        ctrl_bar.addWidget(self.lb_cur_keys)
        self.lb_cursor = QLabel("")
        self.lb_cursor.setStyleSheet("color:#ffd000;")
        ctrl_bar.addWidget(self.lb_cursor)
        ctrl_bar.addStretch(1)
        right_layout.addLayout(ctrl_bar)

        self.plot = pg.PlotWidget()
        # 背景关闭 pyqtgraph 内置网格线（showGrid=False），
        # 栅格由 GridDotsItem 静态绘制：中心十字实线 + 其余栅格点线 + 交叉格点，
        # 只显示栅格与波形，无其他线条
        self.plot.showGrid(x=False, y=False)
        # 移除软件初始化波形显示区域 X/Y 轴的标题和刻度（并隐藏
        # 轴边框，彻底消除栅格方向「很粗的阴影」线条），波形区=纯黑背景+
        # 静态格点+波形+⬇触发点+➡通道标签
        try:
            self.plot.getPlotItem().hideAxis('left')
            self.plot.getPlotItem().hideAxis('bottom')
        except Exception:  # noqa: BLE001
            pass
        # 背景栅格完全清空重写——离散散点方案，移除密集点线(DotLine)。
        # 中心十字 = PlotCurveItem 实线（唯一实线）；
        # 大格交叉点 = ScatterPlotItem（11×11，size=5，较亮）；
        # 小格点 = ScatterPlotItem（每大格之间9个小点=10小格，size=2，较暗）。
        # 标准示波器栅格：每大格(div)分为10小格，2个大格点之间恰好9个小格点。
        self._grid_cross = pg.PlotCurveItem(
            pen=pg.mkPen("#aab4c4", width=1), connect="finite")
        self._grid_cross.setZValue(-6)
        self.plot.addItem(self._grid_cross, ignoreBounds=True)
        # 大格交叉点（11×11 = 10大格，size=5，较亮）
        self._grid_dots = pg.ScatterPlotItem(
            size=5, brush=pg.mkBrush("#6a7482"), pen=pg.mkPen(None))
        self._grid_dots.setZValue(-6)
        self.plot.addItem(self._grid_dots, ignoreBounds=True)
        # 小格点（每大格之间9个小点=10小格，size=2，较暗）
        self._grid_minor_dots = pg.ScatterPlotItem(
            size=2, brush=pg.mkBrush("#3a4452"), pen=pg.mkPen(None))
        self._grid_minor_dots.setZValue(-7)
        self.plot.addItem(self._grid_minor_dots, ignoreBounds=True)
        # 软件刚打开即按当前数据窗口静态显示 10×10 栅格
        # （中心十字实线 + 其余点线 + 交叉点；不随数据移动、整个运行周期保持初始状态）
        try:
            self._update_reference_markers()
        except Exception:  # noqa: BLE001
            pass
        # 背景栅格任何情况下都不随鼠标滚轮移动/缩放——
        # 创建即禁用 X/Y 轴鼠标交互（范围只由时基 / 垂直灵敏度旋钮控制）。
        self.plot.setMouseEnabled(False, False)
        try:
            self.plot.getPlotItem().vb.setMouseEnabled(False, False)
        except Exception:  # noqa: BLE001
            pass
        # 移除图例（顶部宽线），通道由左侧通道标签标识
        # 关闭 pyqtgraph 内置英文右键菜单，改用本地化自定义菜单（含图片导出等）
        try:
            self.plot.getPlotItem().setMenuEnabled(False)
            view_box = self.plot.getPlotItem().vb
            if view_box is not None:
                view_box.setMenuEnabled(False)
        except Exception:  # noqa: BLE001
            pass
        self.plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(self._on_plot_context_menu)
        # 实时同步：波形图 Y 轴范围变化时，触发旋钮极值跟随更新
        try:
            _vb = self.plot.getPlotItem().vb
            if _vb is not None:
                _vb.sigRangeChanged.connect(self._on_view_range_changed)
        except Exception:  # noqa: BLE001
            pass
        right_layout.addWidget(self.plot, 1)

        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 820])
        root.addWidget(split, 1)

        # 专业 X/Y 光标测量系统（CursorManager）：四条虚线光标 + 右下角读数面板
        self.cursor = CursorManager(self)

        # 触发电平参考线（黄色虚线）：TRIG-03 修复：可鼠标拖拽调整，拖拽同步到文本框
        self.trig_line = pg.InfiniteLine(angle=0, movable=True,
                                         pen=pg.mkPen(
                                             "#ffff00", width=1.5, style=Qt.PenStyle.DashLine))
        self.trig_line.setValue(0.0)
        self.trig_line.setVisible(False)
        # 悬停显示上下双箭头（与测量光标一致）
        try:
            from PySide6.QtGui import QCursor
            self.trig_line.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        except Exception:  # noqa: BLE001
            pass
        self.trig_line.sigPositionChanged.connect(self._on_trig_line_dragged)
        self.plot.addItem(self.trig_line, ignoreBounds=True)

        # ---- V1.37-R4 示波器专业参考元素 ----
        # t=0 触发点（屏幕顶部橙色向下箭头）+ 中心虚线（格线中心参考）
        self._ground_refs = {}      # ch -> GroundRefItem（0V 垂直参考点）
        self._ch_labels = {}        # ch -> pg.TextItem（通道标签）
        # 水平时间参考点（t=0/触发点）：顶部橙色 "T" + 短竖线（TextItem/PlotDataItem 渲染可靠）
        # anchor=(0.5,0) —— T 文本顶部贴在波形显示区域最顶部，
        # 文本整体在可视区内向下显示，不被顶部裁剪
        self._t0_ref = pg.TextItem("", anchor=(0.5, 0.0))
        try:
            # t0 触发点标记改为向下箭头「⬇」（顶部与波形区顶部平齐，
            # 箭头自带向下的指向，不再需要额外竖线）
            self._t0_ref.setHtml(
                '<div style="color:#ff9f1c;font-weight:bold;font-size:20px;'
                'font-family:Segoe UI Symbol,Consolas,Monospace;">⬇</div>')
        except Exception:  # noqa: BLE001
            self._t0_ref.setText("⬇")
        self._t0_ref.setVisible(False)
        try:
            self._t0_ref.setZValue(-4)
        except Exception:  # noqa: BLE001
            pass
        self.plot.addItem(self._t0_ref, ignoreBounds=True)
        self._t0_line = pg.PlotDataItem([], [],
                                        pen=pg.mkPen("#ff9f1c", width=2))
        self._t0_line.setVisible(False)
        try:
            self._t0_line.setZValue(-4)
        except Exception:  # noqa: BLE001
            pass
        self.plot.addItem(self._t0_line, ignoreBounds=True)
        _cpen = pg.mkPen("#6b7484", width=1, style=Qt.PenStyle.DashLine)
        self._center_vline = pg.InfiniteLine(angle=90, pen=_cpen)
        self._center_vline.setVisible(False)
        try:
            self._center_vline.setZValue(-5)
        except Exception:  # noqa: BLE001
            pass
        self.plot.addItem(self._center_vline, ignoreBounds=True)
        self._center_hline = pg.InfiniteLine(angle=0, pen=_cpen)
        self._center_hline.setVisible(False)
        try:
            self._center_hline.setZValue(-5)
        except Exception:  # noqa: BLE001
            pass
        self.plot.addItem(self._center_hline, ignoreBounds=True)

        # 光标开关与线条联动（Manual 模式下按线显隐）
        self.btn_cursor_xa.toggled.connect(lambda on: self._set_cursor_visible("x1", on))
        self.btn_cursor_xb.toggled.connect(lambda on: self._set_cursor_visible("x2", on))
        self.btn_cursor_ya.toggled.connect(lambda on: self._set_cursor_visible("y1", on))
        self.btn_cursor_yb.toggled.connect(lambda on: self._set_cursor_visible("y2", on))

        # 光标模式 / 源 / 高级功能接线
        self.cb_cursor_mode.currentIndexChanged.connect(self._on_cursor_mode)
        self.cb_cursor_src.currentIndexChanged.connect(self._on_cursor_src)
        self.btn_track_scaling.toggled.connect(self.cursor.set_track_scaling)
        self.btn_coupling.toggled.connect(self.cursor.set_coupling)
        self.btn_set_wave.clicked.connect(self.cursor.set_to_wave)
        self.btn_set_screen.clicked.connect(self._on_reset_screen)
        self.cursor.cursorMoved.connect(self._on_cursor_moved_signal)

        # 光标拖动处理
        self.plot.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        self._mouse_proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved,
                                           rateLimit=60, slot=self._on_mouse_moved)
        # 滚轮微调：悬停光标线上时拦截（其余交给 ViewBox 缩放）
        self.plot.viewport().installEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ------------------------------------------------------------- i18n
    def retranslate(self):
        self.lb_timebase.setText(tr("scope.timebase"))
        self.btn_auto.setText(tr("scope.auto"))
        self.btn_auto.setToolTip(tr("scope.auto_tip"))
        self.lb_limit.setText(tr("scope.limit"))
        self.cb_limit.setToolTip(tr("scope.limit_tip"))
        self._refresh_limit_hint()
        self.lb_refresh.setText(tr("scope.refresh"))
        self.sp_refresh.setToolTip(tr("scope.refresh_tip"))
        self.lb_trigger.setText(tr("scope.trigger"))
        self.lb_level.setText(tr("scope.level"))
        self.sp_trig_level.setToolTip(tr("scope.level_tip"))
        self.lb_pw.setText(tr("scope.pw_width"))
        self.sp_runt_hi.setToolTip(tr("scope.runt_hi_tip"))
        self.lb_to.setText(tr("scope.to_state"))
        self.sp_to_time.setToolTip(tr("scope.to_time_tip"))
        self.lb_win.setText(tr("scope.win_levels"))
        self.sp_win_hi.setToolTip(tr("scope.win_hi_tip"))
        self.sp_win_lo.setToolTip(tr("scope.win_lo_tip"))
        self.lb_rt.setText(tr("scope.rt_time"))
        self.sp_rt_time.setToolTip(tr("scope.rt_time_tip"))
        # ＋/− 数值控件按钮提示随语言刷新
        for spin in (self.sp_trig_level, self.sp_pw_width, self.sp_runt_hi,
                     self.sp_to_time, self.sp_win_hi, self.sp_win_lo, self.sp_rt_time):
            spin.retranslate()
        self._update_run_btn_text()
        self.btn_single.setText(tr("scope.single"))
        self.btn_clear.setText(tr("scope.clear_plot"))
        self.btn_csv.setText(tr("scope.export"))

        self.knob_tb.setLabel(tr("scope.knob_timebase"))
        self.knob_trig.setLabel(tr("scope.knob_trig"))
        self.knob_hpos.setLabel(tr("scope.knob_hpos"))
        self.lb_knob_help.setText(tr("scope.knob_help"))

        # 触发模式 / 边沿下拉项（保留当前选择）
        self._retranslate_trig_combos()

        # 通道表表头与分组标题
        self.group_ch.setTitle(tr("scope.group_ch"))
        # 通道表表头
        for i, key in enumerate(["scope.col_show", "scope.col_ch", "scope.col_coupling",
                                  "scope.col_gain", "scope.col_offset", "scope.col_unit",
                                  "scope.col_color"]):
            if i < len(self.ch_header_labels):
                self.ch_header_labels[i].setText(tr(key))

        # 分页按钮文本随语言切换更新
        if hasattr(self, "btn_first_page"):
            self.btn_first_page.setText(tr("scope.page_first"))
        if hasattr(self, "btn_prev_page"):
            self.btn_prev_page.setText(tr("scope.page_prev"))
        if hasattr(self, "btn_next_page"):
            self.btn_next_page.setText(tr("scope.page_next"))
        if hasattr(self, "btn_last_page"):
            self.btn_last_page.setText(tr("scope.page_last"))

        # 自动测量标题与名称
        self.grp_meas.setTitle(tr("scope.group_meas"))
        self.lb_meas_ch.setText(tr("scope.meas_ch"))
        self.lb_unit.setText(tr("scope.unit_label"))
        self.ed_unit.setPlaceholderText(tr("scope.unit_ph"))
        self.ed_unit.setToolTip(tr("scope.unit_tip"))
        for key, i18n in self._MEAS_ROWS:
            if key in self._meas_name_labels:
                self._meas_name_labels[key].setText(tr(i18n) + ":")
        self.lbl_cur.setText(tr("scope.cursor_hint"))

        # 移除 X 轴时间标题 + 统一坐标刻度/轴隐藏策略
        # （setLabel 会触发 showAxis 恢复轴，必须用 _apply_axis_policy 兜底）
        self._apply_axis_policy()

        # 显示模式 / 余辉
        self._retranslate_display_combos()
        # 数学通道
        self.grp_math.setTitle(tr("scope.group_math"))
        for i in range(4):
            key = f"m{i + 1}"
            row = self._math_rows[key]
            spec = self.maths[key]
            row["checkbox"].setText(spec["name"])
            row["line_edit"].setPlaceholderText(tr("scope.math_ph"))
            row["line_edit"].setToolTip(tr("scope.math_tip"))
            row["btn"].setStyleSheet(
                f"background:{spec['color']};border:none;border-radius:3px;")
            if row["line_edit"].text() != spec["expr"]:
                row["line_edit"].setText(spec["expr"])
        self.lb_math_note.setText(tr("scope.math_note"))

        # 光标开关按钮文本与提示
        self.btn_cursor_xa.setText(tr("scope.cursor_xa"))
        self.btn_cursor_xb.setText(tr("scope.cursor_xb"))
        self.btn_cursor_ya.setText(tr("scope.cursor_ya"))
        self.btn_cursor_yb.setText(tr("scope.cursor_yb"))
        self.btn_cursor_xa.setToolTip(tr("scope.cursor_xa_tip"))
        self.btn_cursor_xb.setToolTip(tr("scope.cursor_xb_tip"))
        self.btn_cursor_ya.setToolTip(tr("scope.cursor_ya_tip"))
        self.btn_cursor_yb.setToolTip(tr("scope.cursor_yb_tip"))
        self._retranslate_cursor_bar()
        self._update_cursor_readout()

    def _retranslate_trig_combos(self):
        idx = self.cb_trig_mode.currentIndex()
        self.cb_trig_mode.blockSignals(True)
        self.cb_trig_mode.clear()
        mode_keys = ("scope.trig_mode_auto", "scope.trig_mode_normal",
                     "scope.trig_mode_single")
        for key in mode_keys:
            self.cb_trig_mode.addItem(tr(key))
        self.cb_trig_mode.setCurrentIndex(max(0, min(idx, self.cb_trig_mode.count() - 1)))
        self.cb_trig_mode.blockSignals(False)

        current_val = self.cb_trig_edge.currentData()
        self.cb_trig_edge.blockSignals(True)
        self.cb_trig_edge.clear()
        self.cb_trig_edge.addItem(tr("scope.trig_edge_rise"), "rise")
        self.cb_trig_edge.addItem(tr("scope.trig_edge_fall"), "fall")
        self.cb_trig_edge.addItem(tr("scope.trig_edge_both"), "both")
        i = self.cb_trig_edge.findData(current_val if current_val is not None else "rise")
        self.cb_trig_edge.setCurrentIndex(max(0, i))
        self.cb_trig_edge.blockSignals(False)

        idx = self.cb_trig_type.currentIndex()
        self.cb_trig_type.blockSignals(True)
        self.cb_trig_type.clear()
        self.cb_trig_type.addItem(tr("scope.trig_type_edge"), "edge")
        self.cb_trig_type.addItem(tr("scope.trig_type_pulse"), "pulse")
        self.cb_trig_type.addItem(tr("scope.trig_type_runt"), "runt")
        self.cb_trig_type.addItem(tr("scope.trig_type_timeout"), "timeout")
        self.cb_trig_type.addItem(tr("scope.trig_type_window"), "window")
        self.cb_trig_type.addItem(tr("scope.trig_type_rt"), "risetime")
        self.cb_trig_type.setCurrentIndex(max(0, min(idx, self.cb_trig_type.count() - 1)))
        self.cb_trig_type.blockSignals(False)

        current_val = self.cb_to_state.currentData()
        self.cb_to_state.blockSignals(True)
        self.cb_to_state.clear()
        self.cb_to_state.addItem(tr("scope.to_above"), "above")
        self.cb_to_state.addItem(tr("scope.to_below"), "below")
        self.cb_to_state.setCurrentIndex(1 if current_val == "below" else 0)
        self.cb_to_state.blockSignals(False)

    def _retranslate_display_combos(self):
        self.lb_display.setText(tr("scope.display"))
        display_idx = self.cb_display.currentIndex()
        self.cb_display.blockSignals(True)
        self.cb_display.clear()
        self.cb_display.addItem(tr("scope.display_vector"), "vector")
        self.cb_display.addItem(tr("scope.display_dot"), "dot")
        self.cb_display.setCurrentIndex(max(0, min(display_idx, 1)))
        self.cb_display.blockSignals(False)

    def _update_run_btn_text(self):
        self.btn_run.setText(tr("scope.pause") if self.running else tr("scope.run"))

    def _make_cursor_btn(self, tip_key, checked):
        """创建一个可勾选的光标开关按钮（文本由 retranslate 填充）。"""
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setToolTip(tr(tip_key))
        btn.setMinimumWidth(44)
        return btn

    def _set_cursor_visible(self, name, checked):
        self.cursor.set_line_visible(name, checked)
        self._update_cursor_readout()

    def _retranslate_cursor_bar(self):
        """填充光标模式/源下拉框与高级功能按钮文案、提示。"""
        sel = self.cb_cursor_mode.currentData()
        self.cb_cursor_mode.blockSignals(True)
        self.cb_cursor_mode.clear()
        self.cb_cursor_mode.addItem(tr("scope.cur_mode_off"), MODE_OFF)
        self.cb_cursor_mode.addItem(tr("scope.cur_mode_manual"), MODE_MANUAL)
        self.cb_cursor_mode.addItem(tr("scope.cur_mode_track"), MODE_TRACK)
        self.cb_cursor_mode.addItem(tr("scope.cur_mode_auto"), MODE_AUTO)
        i = self.cb_cursor_mode.findData(sel)
        self.cb_cursor_mode.setCurrentIndex(i if i >= 0 else MODE_OFF)
        self.cb_cursor_mode.blockSignals(False)

        self._repopulate_cursor_src()

        self.lb_cur_mode.setText(tr("scope.cur_mode"))
        self.lb_cur_src.setText(tr("scope.cur_source"))
        self.btn_track_scaling.setText(tr("scope.cur_track_scaling"))
        self.btn_track_scaling.setToolTip(tr("scope.cur_track_scaling_tip"))
        self.btn_coupling.setText(tr("scope.cur_coupling"))
        self.btn_coupling.setToolTip(tr("scope.cur_coupling_tip"))
        self.btn_set_wave.setText(tr("scope.cur_set_wave"))
        self.btn_set_wave.setToolTip(tr("scope.cur_set_wave_tip"))
        self.btn_set_screen.setText(tr("scope.cur_set_screen"))
        self.btn_set_screen.setToolTip(tr("scope.cur_set_screen_tip"))
        self.lb_cur_keys.setText(tr("scope.cur_keys_hint"))

    def _repopulate_cursor_src(self):
        current_val = self.cb_cursor_src.currentData()
        self.cb_cursor_src.blockSignals(True)
        self.cb_cursor_src.clear()
        for c in self.channels:
            self.cb_cursor_src.addItem(self.channels[c]["name"], c)
        for key, spec in self.maths.items():
            self.cb_cursor_src.addItem(spec["name"], key)
        if self.cb_cursor_src.count() > 0:
            i = self.cb_cursor_src.findData(current_val)
            # 用户未手动选择过，或当前选择已失效 → 默认选中 ch1
            # （编号最小的模拟通道）；无模拟通道时退回第一项
            if (not self._cursor_src_touched) or i < 0:
                i = self.cb_cursor_src.findData(0)
                if i < 0:
                    i = 0
            self.cb_cursor_src.setCurrentIndex(i)
        self.cb_cursor_src.blockSignals(False)
        # 程序合成选择不视为用户手动操作
        self._cursor_src_synth = True
        try:
            self._on_cursor_src(self.cb_cursor_src.currentIndex())
        finally:
            self._cursor_src_synth = False

    def _on_cursor_mode(self, index):
        # 记录切换前的左右面板比例，切换后恢复——
        # 保证打开/关闭光标测量模式时波形显示区域宽度完全不变
        sizes = self.split.sizes() if hasattr(self, "split") else None
        m = self.cb_cursor_mode.itemData(index)
        self.cursor.set_mode(int(m) if m is not None else MODE_OFF)
        self._sync_cursor_buttons()
        self._update_cursor_readout()
        self._update_vb_mouse_enabled()
        if sizes is not None and hasattr(self, "split"):
            try:
                self.split.setSizes(sizes)
            except Exception:  # noqa: BLE001
                pass

    def _update_vb_mouse_enabled(self):
        """光标模式非「关闭」时，波形图禁用鼠标平移/缩放（仅光标响应移动）；
        「关闭」时恢复原有鼠标调整波形功能（平移/滚轮缩放）。
        """
        # 标准示波器 X/Y 轴缩放均通过旋钮（时基 / 垂直灵敏度）控制，
        # 禁用波形图鼠标滚轮缩放，防止用户滚轮改变 X/Y 范围导致「时基 500ms/div 却
        # 显示 20s 窗口」这类与旋钮读数不一致的异常；仅保留光标模式下的鼠标响应。
        try:
            view_box = self.plot.getPlotItem().vb
            if view_box is not None:
                # X/Y 轴鼠标缩放均禁用 → 背景栅格任何情况下
                # 都不随鼠标滚轮移动或缩放（标准示波器：X 轴由时基旋钮、
                # Y 轴由垂直灵敏度旋钮控制范围）。
                view_box.setMouseEnabled(False, False)
        except Exception:  # noqa: BLE001
            pass

    def _on_cursor_src(self, index):
        if not getattr(self, "_cursor_src_synth", False):
            self._cursor_src_touched = True
        if index < 0:
            self.cursor.set_source(None)
            return
        key = self.cb_cursor_src.itemData(index)
        self.cursor.set_source(key)
        self._update_cursor_readout()

    def _on_cursor_moved_signal(self):
        self._update_cursor_readout()

    def _sync_cursor_buttons(self):
        # 光标模式关闭(OFF)时四个开关按钮一律取消选中（与模式视觉一致）
        if self.cursor.mode == MODE_OFF:
            for btn in (self.btn_cursor_xa, self.btn_cursor_xb,
                        self.btn_cursor_ya, self.btn_cursor_yb):
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)
            return
        for name, btn in (("x1", self.btn_cursor_xa), ("x2", self.btn_cursor_xb),
                          ("y1", self.btn_cursor_ya), ("y2", self.btn_cursor_yb)):
            btn.blockSignals(True)
            btn.setChecked(self.cursor.lines[name].isVisible())
            btn.blockSignals(False)

    def apply_theme(self, theme: str):
        """主题切换时就地重绘波形图背景与坐标轴（由 ThemeManager 调用）。
        style_plot 之后强制保持「无网格线 + 轴隐藏」状态，
        防止主题切换重新打开网格线/恢复坐标刻度。"""
        from .app_theme import style_plot
        style_plot(self.plot, theme)
        # 保持无网格线 + X/Y 轴隐藏（坐标刻度不显示）
        self._apply_axis_policy()
        self._view_dirty = True

    @property
    def timebase(self):
        return TIMEBASE[self.cb_timebase.currentIndex()][1]

    def _mark_dirty(self):
        self._dirty = True
        self._view_dirty = True

    # ------------------------------------------------------------- 通道扩展
    def _spec_of(self, ch):
        """统一取通道显示规格：模拟通道 ch(int) 或数学通道 key(str)。"""
        return self.dh._spec_of(ch)

    def _is_math(self, ch):
        return self.dh._is_math(ch)

    # ------------------------------------------------------------- 触发类型
    def _trig_type(self):
        d = self.cb_trig_type.currentData()
        return d if d in ("edge", "pulse", "runt", "timeout", "window", "risetime") else "edge"

    def _on_trig_type(self, _idx):
        self._update_trig_param_visibility()
        self._mark_dirty()

    def _update_trig_param_visibility(self):
        t = self._trig_type()
        self.lb_pw.setVisible(t == "pulse")
        self.cb_pw_cond.setVisible(t == "pulse")
        self.sp_pw_width.setVisible(t == "pulse")
        self.sp_runt_hi.setVisible(t == "runt")
        self.lb_to.setVisible(t == "timeout")
        self.cb_to_state.setVisible(t == "timeout")
        self.sp_to_time.setVisible(t == "timeout")
        self.lb_win.setVisible(t == "window")
        self.sp_win_hi.setVisible(t == "window")
        self.sp_win_lo.setVisible(t == "window")
        self.lb_rt.setVisible(t == "risetime")
        self.sp_rt_time.setVisible(t == "risetime")

    # ------------------------------------------------------------- 显示模式/余辉
    def _on_display_mode(self, _idx):
        self.display_mode = self.cb_display.currentData() or "vector"
        self._rebuild_curve_drawstyle()
        self._mark_dirty()

    def _clear_ghosts(self):
        for ch, ghosts in self._ghosts.items():
            while ghosts:
                item = ghosts.pop()
                self.plot.removeItem(item)
        self._ghosts.clear()

    def _rebuild_curve_drawstyle(self):
        # 点阵模式：主曲线改用散点绘制；矢量模式恢复折线
        dot = self.display_mode == "dot"
        for ch, curve in self.curves.items():
            spec = self._spec_of(ch)
            if spec is None:
                continue
            if dot:
                curve.setPen(None)
                curve.setSymbol("o")
                curve.setSymbolSize(3)
                curve.setSymbolBrush(QColor(spec["color"]))
            else:
                curve.setPen(pg.mkPen(spec["color"], width=1.5))
                curve.setSymbol(None)

    # ------------------------------------------------------------- 数学通道
    def _on_math_enabled(self, key, checked):
        """数学面板开关变化时重建通道面板（添加/移除数学通道行）。
        数学面板开启(enabled=True) → 通道面板添加设置行；关闭(enabled=False) → 移除。
        通道面板的显示开关只控制 visible（波形显示），不影响数学面板的 enabled 状态。"""
        self.maths[key]["enabled"] = checked
        if checked:
            # 数学面板开启时，曲线可见性由 visible 字段决定（用户可能之前关闭了显示）
            if key in self.curves:
                self.curves[key].setVisible(self.maths[key].get("visible", True))
        else:
            # 关闭时移除已绘曲线与缓存
            if key in self.curves:
                self.plot.removeItem(self.curves.pop(key))
            self._math_t.pop(key, None)
            self._math_y.pop(key, None)
        self._apply_left_axis_label()   # Y 轴单位随打开的数学通道更新
        self._rebuild_channel_table()
        # BUG-J 修复：数学通道开关变化 → 通知主窗口同步 FFT 通道下拉与分布图
        self.channels_changed.emit()
        self._mark_dirty()

    def _on_math_expr_edited(self, key, text):
        expr = (text or "").strip()
        self.maths[key]["expr"] = expr
        self._math_expr_error.pop(key, None)
        if expr:
            try:
                math_validate(expr)
            except ValueError as exc:
                self._math_expr_error[key] = str(exc)
        # 表达式改变 → unit_auto 数学通道单位跟随表达式第一个引用通道
        self._sync_math_auto_unit(key)
        # 表达式非法时输入框红色边框 + tooltip 提示，用户可立即发现。
        self._update_math_error_style(key)
        self._mark_dirty()

    def _sync_math_auto_unit(self, key):
        """unit_auto 的数学通道：单位 = 表达式第一个引用通道的单位，并刷新 UI。
        覆盖 M1=ch1（跟随ch1）、M1=ch2+1（跟随ch2）、M1=ch3+ch1（跟随ch3）
        等所有引用顺序场景；无引用通道或已手动改过单位则不改变。"""
        spec = self.maths.get(key)
        if spec is None or not spec.get("unit_auto", False) or not spec.get("expr"):
            return
        first_ch = first_ch_in_expr(spec["expr"])
        if first_ch is None or first_ch not in self.channels:
            return
        new_unit = self.channels[first_ch].get("unit", "V")
        if spec.get("unit") != new_unit:
            spec["unit"] = new_unit
            row = self._channel_rows.get(key)
            if row is not None:
                row.set_unit(new_unit)
            self._apply_left_axis_label()
            self._update_measures()

    def _update_math_error_style(self, key):
        """根据 _math_expr_error 更新数学通道输入框的边框与 tooltip。"""
        row = self._math_rows.get(key)
        if row is None:
            return
        line_edit = row["line_edit"]
        err = self._math_expr_error.get(key)
        if err:
            line_edit.setStyleSheet("border:1px solid #e74c3c;border-radius:3px;")
            line_edit.setToolTip(str(err))
        else:
            line_edit.setStyleSheet("")
            line_edit.setToolTip("")

    def _pick_math_color(self, key):
        c = QColorDialog.getColor(
            QColor(self.maths[key]["color"]), self, tr("scope.color_title"))
        if c.isValid():
            self.maths[key]["color"] = c.name()
            self._math_rows[key]["btn"].setStyleSheet(
                f"background:{c.name()};border:none;border-radius:3px;")
            if key in self.curves:
                self.curves[key].setPen(pg.mkPen(c.name(), width=1.5))
            self._mark_dirty()

    def _compute_math(self):
        """把启用且表达式合法的数学通道计算为独立数组。

        计算核心统一在 DataHub.compute_math()（唯一数据源），本面板调用后仅
        刷新表达式错误的 UI 样式。
        """
        self.dh.compute_math()
        # 刷新数学通道表达式错误的 UI 样式
        for key in self.maths:
            self._update_math_error_style(key)

    def _clear_math_computed(self):
        self.dh._clear_math_computed()

    # ------------------------------------------------------------- 通道管理
    def setup_channels(self, n):
        """设置通道数量并重建数据缓冲（数据层交给 DataHub）+ 重建 UI。"""
        self.dh.setup_channels(n)
        # 以下为 UI 层重建
        for ch in list(self.curves):
            self.plot.removeItem(self.curves.pop(ch))
        self.single_armed = False
        self.single_done = False
        self._last_window = None
        self._last_hpos = 0.0
        # 格式变更后若仍处于单次模式，会退化为自动滚动绘制，须退回自动并同步下拉框
        if self.mode == "single":
            self.mode = "auto"
            if self.cb_trig_mode.currentIndex() != 0:
                self.cb_trig_mode.blockSignals(True)
                self.cb_trig_mode.setCurrentIndex(0)
                self.cb_trig_mode.blockSignals(False)
        self.running = True
        if not self.btn_run.isChecked():
            self.btn_run.setChecked(True)
        self._trig_arm_t = None
        self._update_run_btn_text()
        self._vdiv_auto = True      # 格式/通道重建后重新自动适配垂直灵敏度
        self._last_vdiv_auto_t = 0.0
        self._rebuild_channel_table()
        self._repopulate_combos()
        self._ensure_data_dicts()
        # 数学通道计算缓存与曲线随数据一起重置（表达式与开关保留）
        self._math_t.clear()
        self._math_y.clear()
        self._math_expr_error.clear()
        self._clear_ghosts()
        for key, spec in self.maths.items():
            if spec["enabled"] and key in self.curves:
                self.plot.removeItem(self.curves.pop(key))
        self._apply_left_axis_label()   # 通道重建后刷新 Y 轴单位
        self._dirty = True
        self._view_dirty = True

    def _ensure_data_dicts(self):
        self.dh._ensure_data_dicts()

    def _all_channel_keys(self):
        """返回所有通道键（物理通道 + 已启用的数学通道），用于分页计算。"""
        keys = list(self.channels.keys())
        for mkey, mspec in self.maths.items():
            if mspec.get("enabled", False):
                keys.append(mkey)
        return keys

    def _total_pages(self):
        """总页数 = ceil(总通道数 / 每页通道数)，至少1页。"""
        page_size = getattr(self, '_page_size', 5)
        total = len(self._all_channel_keys())
        return max(1, (total + page_size - 1) // page_size)

    def _on_first_page(self):
        """跳转到首页（第1页）。"""
        if self._current_page > 0:
            self._current_page = 0
            self._rebuild_channel_table()

    def _on_last_page(self):
        """跳转到尾页（最后一页）。"""
        last = self._total_pages() - 1
        if self._current_page < last:
            self._current_page = last
            self._rebuild_channel_table()

    def _on_prev_page(self):
        """上一页。"""
        if self._current_page > 0:
            self._current_page -= 1
            self._rebuild_channel_table()

    def _on_next_page(self):
        """下一页。"""
        if self._current_page < self._total_pages() - 1:
            self._current_page += 1
            self._rebuild_channel_table()

    def _on_page_spin_changed(self, page):
        """手动页码变化（1-based）。"""
        new_page = max(0, min(page - 1, self._total_pages() - 1))
        if new_page != self._current_page:
            self._current_page = new_page
            self._rebuild_channel_table()

    def _rebuild_channel_table(self):
        """重建通道行：表头(第0行)与通道控件(第1..N行)放入同一个
        QGridLayout，列宽由 grid 统一控制 → 控件值与列标题严格对齐、随值自适应。

        注意：QGridLayout 无 removeRow（那是表格控件 API），清行必须用
        removeWidget + deleteLater；行号由 self._ch_row_spans 显式记录，
        不依赖 grid.rowCount()。"""
        self._scale_spins.clear()
        self._offset_spins.clear()
        self._coupling_combos = {}
        grid = self.ch_grid
        # 清除旧的通道行（记录在 self._ch_row_spans：(行号, [控件])，保留表头第0行）
        for _row_idx, widgets in getattr(self, "_ch_row_spans", []):
            for w in widgets:
                try:
                    grid.removeWidget(w)
                    w.deleteLater()
                except Exception:  # noqa: BLE001
                    pass
        self._ch_row_spans = []
        for row in self._channel_rows.values():
            try:
                row.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        self._channel_rows.clear()
        # 创建新的通道行（分页显示，每页最多 _page_size 个通道）
        r = 1
        all_chs = self._all_channel_keys()
        # 钳位当前页码
        total_pages = self._total_pages()
        cur_page = getattr(self, '_current_page', 0)
        if cur_page >= total_pages:
            self._current_page = total_pages - 1
        # 分页切片：只显示当前页的通道
        page_size = getattr(self, '_page_size', 5)
        start = getattr(self, '_current_page', 0) * page_size
        end = start + page_size
        page_chs = all_chs[start:end]
        for ch in page_chs:
            info = self._spec_of(ch)
            if info is None:
                continue
            row = ChannelRow(ch, info)
            # 连接信号
            row.switch.toggled.connect(lambda on, c=ch: self._set_ch_enabled(c, on))
            row.cb_coup.currentIndexChanged.connect(
                lambda *_i, c=ch, cb=row.cb_coup: self._on_coupling_changed(c, cb))
            row.cb_scale.currentIndexChanged.connect(
                lambda *_i, c=ch, cb=row.cb_scale: self._on_scale_combo(c, cb))
            row.cb_off.valueChanged.connect(
                lambda v, c=ch: self._on_offset_spin(c, v))
            # 单位列：下拉选择(currentIndexChanged)与手动输入(currentTextChanged)
            # 均触发——可编辑下拉手动键入新单位时 currentIndex 可能不变，
            # 仅靠 currentIndexChanged 会导致单位修改不生效。
            row.cb_unit.currentIndexChanged.connect(
                lambda *_i, c=ch, cb=row.cb_unit: self._on_channel_unit_changed(
                    c, cb.currentText()))
            row.cb_unit.currentTextChanged.connect(
                lambda txt, c=ch: self._on_channel_unit_changed(c, txt))
            row.btn_color.clicked.connect(lambda _, c=ch: self._pick_color(c))
            # 放入与表头共用的 grid（列 0-6），逐列对齐
            widgets = [row.switch, row.lb_name, row.cb_coup, row.cb_scale,
                       row.cb_off, row.cb_unit, row.btn_color]
            for col, w in enumerate(widgets):
                grid.addWidget(w, r, col)
            self._ch_row_spans.append((r, widgets))
            self._channel_rows[ch] = row
            self._scale_spins[ch] = row.cb_scale
            self._offset_spins[ch] = row.cb_off
            self._coupling_combos[ch] = row.cb_coup
            r += 1
        grid.setRowStretch(r, 1)   # 底部弹性留白
        # 更新表头标签
        for i, key in enumerate(["scope.col_show", "scope.col_ch", "scope.col_coupling",
                                  "scope.col_gain", "scope.col_offset", "scope.col_unit",
                                  "scope.col_color"]):
            if i < len(self.ch_header_labels):
                self.ch_header_labels[i].setText(tr(key))
        # 通道面板宽度跟随内容自适应（表头+控件列宽齐整后取 sizeHint）
        self._fit_channel_panel_width()
        # 分页控件更新——完全无滚动条，面板高度自适应，每页最多5个通道
        try:
            self.ch_grid.activate()
            self.ch_container.adjustSize()
            total_ch = len(self._all_channel_keys())
            total_pages = self._total_pages()
            page_size = getattr(self, '_page_size', 5)
            # 通道数>5时显示分页控件，否则隐藏
            self.page_row_widget.setVisible(total_ch > page_size)
            # 更新页码范围（阻止信号避免循环）
            self.spin_page.blockSignals(True)
            self.spin_page.setMinimum(1)
            self.spin_page.setMaximum(total_pages)
            self.spin_page.setValue(self._current_page + 1)
            self.spin_page.blockSignals(False)
            self.lbl_page_total.setText(f"/ {total_pages}")
            self.lbl_channel_count.setText(trf("scope.page_total_ch", n=total_ch))
            # 分页按钮可用性
            self.btn_first_page.setEnabled(self._current_page > 0)
            self.btn_prev_page.setEnabled(self._current_page > 0)
            self.btn_next_page.setEnabled(self._current_page < total_pages - 1)
            self.btn_last_page.setEnabled(self._current_page < total_pages - 1)
        except Exception:  # noqa: BLE001
            pass

    def _fit_channel_panel_width(self):
        """通道面板宽度自适应：通道表列宽随控件值自适应后，
        面板 minimumWidth 取 grid sizeHint，避免过宽留白或过窄挤压，
        使面板宽度保持在「最合适」状态。"""
        try:
            group = getattr(self, "group_ch", None)
            if group is None:
                return
            lay = group.layout()
            if lay is None:
                return
            size_hint = lay.sizeHint()
            if size_hint is not None and size_hint.width() > 0:
                group.setMinimumWidth(int(min(size_hint.width() + 16, 640)))
        except Exception:  # noqa: BLE001
            pass


    def _on_coupling_changed(self, ch, cb):
        """切换耦合模式：同步垂直位置并重新计算耦合数据。

        AC 耦合：偏移强制为 0（以 0V 为中心），禁用偏移输入框；
        DC 耦合：恢复偏移输入框，用户可自由调整。
        支持数学通道 key(str)：数学通道耦合同样进入数据层，由 _recouple_channel
        用与物理通道完全相同的算法重算（统一框架），保证 M1 与 ch1 波形一致。"""
        val = cb.currentData()
        spec = self._spec_of(ch)
        if spec is None:
            return
        spec["coupling"] = val or "dc"
        offset_spin = self._offset_spins.get(ch)
        if offset_spin is not None:
            if val == "ac":
                # AC 耦合垂直位置强制为 0（以 0V 为中心），禁用连续数值输入框
                spec["v_pos"] = 0.0
                offset_spin.blockSignals(True)
                offset_spin.setValue(0.0)
                offset_spin.blockSignals(False)
                offset_spin.setEnabled(False)
                offset_spin.setToolTip(tr("scope.offset_ac_disabled"))
            else:
                # DC 耦合：恢复垂直位置输入框
                offset_spin.setEnabled(True)
                offset_spin.setToolTip(tr("scope.offset_tip"))
        # 切换耦合后重新计算该通道的所有耦合数据（统一数据源）
        self._recouple_channel(ch)
        # 切换耦合后同步触发范围（AC耦合offset=0，触发旋钮范围需更新）
        if ch == self._trig_ch_key():
            self._sync_trig_range()
        # 拖动通道标签时立即更新标签位置（不等待刷新循环，确保拖动流畅）
        ch_label = self._ch_labels.get(ch)
        if ch_label is not None and ch_label.isVisible():
            try:
                y_ref = float(self._display_y(ch, 0.0))
                ch_label.setPos(ch_label.pos().x(), y_ref)
            except Exception:  # noqa: BLE001
                pass
        self._mark_dirty()

    def _repopulate_combos(self):
        self.cb_trig_src.blockSignals(True)
        self.cb_trig_src.clear()
        for c in self.channels:
            self.cb_trig_src.addItem(self.channels[c]["name"], c)
        for key, spec in self.maths.items():
            self.cb_trig_src.addItem(spec["name"], key)
        self.cb_trig_src.blockSignals(False)
        self.cb_meas_ch.blockSignals(True)
        self.cb_meas_ch.clear()
        for c in self.channels:
            self.cb_meas_ch.addItem(self.channels[c]["name"], c)
        for key, spec in self.maths.items():
            self.cb_meas_ch.addItem(spec["name"], key)
        self.cb_meas_ch.blockSignals(False)
        self._repopulate_cursor_src()

    def _meas_ch_key(self):
        d = self.cb_meas_ch.currentData()
        if isinstance(d, int) or (isinstance(d, str) and d in self.maths):
            return d
        return -1

    def _trig_ch_key(self):
        d = self.cb_trig_src.currentData()
        if isinstance(d, int) or (isinstance(d, str) and d in self.maths):
            return d
        return -1

    def _first_enabled_ch(self):
        for ch, info in self.channels.items():
            if info["enabled"]:
                return ch
        return None

    def _set_ch_enabled(self, ch, checked):
        spec = self._spec_of(ch)
        if spec is None:
            return
        if self._is_math(ch):
            # 数学通道的通道面板显示开关只控制波形可见性(visible)，
            # 不改变数学面板的 enabled 状态，也不从通道面板移除设置行。
            # 数学面板关闭(enabled=False)时才从通道面板移除。
            spec["visible"] = checked
        else:
            spec["enabled"] = checked
        # 同步通道面板的显示开关状态（程序内部调用时确保 UI 与数据一致）
        row = self._channel_rows.get(ch)
        if row is not None and row.switch.isChecked() != checked:
            row.switch.blockSignals(True)
            row.switch.setChecked(checked)
            row.switch.blockSignals(False)
        if ch in self.curves:
            self.curves[ch].setVisible(checked)
        # BUG-I 修复：通道启停变化时通知主窗口，同步 FFT/分布图通道下拉与刷新
        self.channels_changed.emit()
        # 通道开关变化时恢复 Y 轴自动范围，避免 Auto 锁定后新通道超出范围
        self.plot.enableAutoRange(axis=1)
        self._apply_left_axis_label()   # Y 轴单位随打开通道集合更新
        self._mark_dirty()

    def _pick_color(self, ch):
        spec = self._spec_of(ch)
        if spec is None:
            return
        c = QColorDialog.getColor(QColor(spec["color"]), self, tr("scope.color_title"))
        if c.isValid():
            spec["color"] = c.name()
            if ch in self._channel_rows:
                self._channel_rows[ch].set_color(c.name())
            if ch in self.curves:
                self.curves[ch].setPen(pg.mkPen(c.name(), width=1.5))
            self._mark_dirty()

    # ------------------------------------------------------------- 数据输入
    def add_frame(self, t, vals):
        """由主线程调用：写入一帧 {通道序号: 数值}（数据层唯一写入 DataHub）。"""
        if not vals or not math.isfinite(t):
            return
        self.dh.append_frame(t, vals)
        self._dirty = True

    def bulk_add(self, frames):
        """批量写入多帧（格式变化后按新格式重新解析历史数据用）。"""
        if not frames:
            return
        self.dh.bulk_add(frames)
        self._dirty = True

    def _trim(self):
        # 容量控制已下沉到 _Buf.append（环形覆盖 + 批量前移），此处无需再逐项删除。
        return

    def clear(self):
        """清屏：清除所有波形缓存。
        BUG-FIX：Normal/Single 模式下保持触发模式，不切回 Auto；
        清除后空屏幕等待触发，只有触发到的波形才显示。"""
        self.dh.clear_data()
        self.single_armed = False
        self.single_done = False
        # 清除所有显示曲线（空屏幕）
        for ch in list(self.curves.keys()):
            self.curves[ch].setVisible(False)
        self._clear_ghosts()
        self._arr_cache.clear()
        self._last_window = None
        self._last_hpos = 0.0
        self._trig_arm_t = None
        self._last_stable_trig = None  # 触发防抖：上一次稳定触发点
        self._auto_no_trig_count = 0   # Auto模式无触发计数
        # Normal/Single 模式下保持模式，不切回 Auto
        if self.mode == "single":
            self._arm_single()
        elif self.mode == "normal":
            self.running = True
            if not self.btn_run.isChecked():
                self.btn_run.setChecked(True)
            self._update_run_btn_text()
            self.lb_status.setText(tr("scope.status_normal_wait"))
        else:
            self.running = True
            if not self.btn_run.isChecked():
                self.btn_run.setChecked(True)
            self._update_run_btn_text()
            self.lb_status.setText(tr("scope.status_cleared"))
        self._dirty = True
        self._view_dirty = True
        self.cleared.emit()

    # ------------------------------------------------------------- 耦合数据层
    def _recouple_channel(self, ch):
        """重新计算单个通道的所有耦合数据（切换耦合模式时调用，数据层在 DataHub）。"""
        self.dh._recouple_channel(ch)
        self._mark_dirty()

    def _recouple_all(self):
        """重新计算所有通道的耦合数据。"""
        self.dh._recouple_all()
        self._mark_dirty()

    def _get_coupled_arrays(self, ch):
        """获取耦合后的数据（DC原样 / AC去直流），所有功能的统一数据源。
        数学通道直接返回其计算结果（数学通道无耦合概念）。
        【数据安全】返回数组的副本，避免外部修改污染 DataHub 内部缓存。"""
        return self.dh.get_coupled_arrays(ch)

    def _get_arrays_deduped(self, ch):
        """光标专用：获取耦合数据并去除重复时间戳（返回副本）。
        cursor_measure.py 的 _sync_track / _auto_refresh / set_to_wave 依赖此方法做
        特征定位；此前方法缺失导致波形对齐/跟踪/自动光标功能失效。"""
        t, y = self._get_coupled_arrays(ch)
        return _dedupe_xy(np.asarray(t, dtype=float),
                          np.asarray(y, dtype=float))

    def _on_reset_screen(self):
        """「重置屏幕」：光标模式为关闭（OFF）时，按各通道当前设置的
        增益/偏移/单位，把所有选中（enabled）通道的波形以最大比例显示到
        波形图；光标模式非关闭（Manual/Track/Auto）时保持原功能
        （光标线复位到屏幕 1/3、2/3 处）。"""
        mode = self.cb_cursor_mode.itemData(self.cb_cursor_mode.currentIndex())
        if mode == MODE_OFF:
            self._auto_fit_visible_waves()
        else:
            self.cursor.set_to_screen()

    def _auto_fit_visible_waves(self):
        """按通道设置值（增益/偏移/单位），把所有选中通道波形以最大比例
        垂直显示：遍历所有 enabled 的通道与数学通道，取其耦合数据经
        _display_y 换算为屏幕显示值（含单位系数×增益+偏移），求整体包络
        范围后设置 Y 轴范围，使波形包络占屏幕垂直高度约 85%（最大比例，
        保留少量边距）。"""
        lo, hi = None, None
        for ch, info in self.channels.items():
            if not info.get("enabled", False):
                continue
            try:
                y = self._get_arrays_deduped(ch)[1]
            except Exception:
                continue
            if y is None or len(y) == 0:
                continue
            y_disp = np.asarray(self._display_y(ch, y), dtype=float)
            ch_lo = float(np.min(y_disp))
            ch_hi = float(np.max(y_disp))
            lo = ch_lo if lo is None else min(lo, ch_lo)
            hi = ch_hi if hi is None else max(hi, ch_hi)
        for key, spec in self.maths.items():
            if not spec.get("enabled", False):
                continue
            try:
                y = self._get_arrays_deduped(key)[1]
            except Exception:
                continue
            if y is None or len(y) == 0:
                continue
            y_disp = np.asarray(self._display_y(key, y), dtype=float)
            ch_lo = float(np.min(y_disp))
            ch_hi = float(np.max(y_disp))
            lo = ch_lo if lo is None else min(lo, ch_lo)
            hi = ch_hi if hi is None else max(hi, ch_hi)
        if lo is None or hi is None:
            return
        span = (hi - lo) or 1.0
        center = (hi + lo) / 2.0
        half = span * 0.5 / 0.85   # 波形包络占屏幕垂直高度约 85%
        self.plot.setYRange(center - half, center + half, padding=0)
        self.plot.disableAutoRange(axis=1)
        # 重置屏幕后同步触发电平旋钮范围（跟随新 Y 轴可视范围）
        if getattr(self, "_trig_ch_key", None) is not None:
            try:
                self._sync_trig_range()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------- 显示更新
    def _get_arrays(self, ch):
        return self.dh.get_arrays(ch)

    # ================================================================
    # 显示层核心（清零重做）：垂直灵敏度 v_div 恒为 V/div
    # ----------------------------------------------------------------
    # 数据模型：spec["v_div"] = 垂直灵敏度（V/div，0.001~10，与通道单位无关）；
    #           spec["v_pos"] = 垂直位置（div，±5）。
    # 显示统一框架（所有波形/操作/计算/耦合共用）：
    #   物理值(通道单位) → 伏特:   y_v  = y × _ch_mag(ch)
    #   伏特 → 显示值(Y轴单位):    disp = (y_v + v_pos×v_div) / _y_mag()
    #   Y 轴范围 = 中心 0，±5 格 = ±5×v_div（V）→ 换算到 Y 轴单位
    #   显示↔物理互逆：_phys_to_disp / _disp_to_phys（触发/光标/测量共用）
    # ================================================================
    def _ch_mag(self, ch):
        """通道单位 → 伏特 的系数（V=1, mV=1e-3, µV=1e-6 ...）。"""
        spec = self._spec_of(ch)
        if spec is None:
            return 1.0
        return self._unit_magnitude(str(spec.get("unit", "V") or "V")) or 1.0

    def _y_mag(self):
        """Y 轴单位 → 伏特 的系数。"""
        return self._unit_magnitude(self._y_axis_unit()) or 1.0

    def _v_pos_eff(self, ch):
        """有效垂直位置（div）：叠加模式下 AC 耦合强制 0（以 0V 为中心）。

        Auto 通道分离排列模式（_auto_separate=True）下，AC 通道同样按
        spec["v_pos"] 定位到各自显示区域（AC 去直流后 0V 参考可置于区域中心，
        物理语义不变），保证多通道分离布局不被 AC 耦合破坏。
        """
        spec = self._spec_of(ch)
        if spec is None:
            return 0.0
        v_pos = float(spec.get("v_pos", 0.0) or 0.0)
        if (isinstance(ch, int)
                and self.channels.get(ch, {}).get("coupling") == "ac"
                and not self._auto_separate):
            v_pos = 0.0
        return v_pos

    def _v_div_eff(self, ch):
        """有效垂直灵敏度（V/div）。"""
        spec = self._spec_of(ch)
        if spec is None:
            return 1.0
        return max(float(spec.get("v_div", 1.0) or 1.0), 1e-12)

    def _phys_to_disp(self, ch, phys):
        """物理值（通道单位）→ 显示值（Y 轴单位）。含每通道 V/div 缩放与
        垂直位置平移（与 _disp_to_phys 严格互逆）。"""
        try:
            v = float(phys)
        except (TypeError, ValueError):
            return 0.0
        return float(self._display_y(ch, v))

    def _disp_to_phys(self, ch, disp):
        """显示值（Y 轴单位）→ 物理值（通道单位）。含每通道 V/div 缩放与
        垂直位置平移的逆运算（与 _display_y 严格互逆）。"""
        try:
            v = float(disp)
        except (TypeError, ValueError):
            return 0.0
        ch_gain = self._ch_mag(ch)
        v_div = self._v_div_eff(ch)
        main_vd = self._main_v_div()
        y_gain = self._y_mag()
        if ch_gain == 0 or v_div <= 0 or main_vd <= 0 or y_gain <= 0:
            return v
        return (v * y_gain / main_vd - self._v_pos_eff(ch)) * v_div / ch_gain

    def _display_y(self, ch, y):
        """【显示数据层】唯一入口：物理值（通道单位）→ 显示值（Y 轴单位）。
        标准示波器模型（修复非主通道垂直灵敏度/垂直位置失效）：
          波形位置（格）= 物理电压 / 本通道V/div + 本通道垂直位置(div)
          显示值（Y 轴单位）= 波形位置（格）× 主控通道V/div / Y轴单位系数
        - 每个通道按自身 V/div 独立垂直缩放、按自身 v_pos 独立上下平移，
          ch1~ch8 完全同一框架、行为完全一致；
        - Y 轴格线以主控通道 V/div 为刻度（±5 格），主控 V/div 变化时格线
          刻度与全通道显示同比变化（标准示波器主刻度行为，各通道波形格数不变）；
        - 主控通道（自身 V/div = 主控 V/div）退化为历史公式，行为零变化；
        - v_div 恒为 V/div、v_pos 恒为 div，与通道单位无关；
        - AC 耦合时垂直位置强制 0（以 0V 为中心）。"""
        spec = self._spec_of(ch)
        if spec is None:
            return np.asarray(y, dtype=float)
        base_v = np.asarray(y, dtype=float) * self._ch_mag(ch)
        v_div = self._v_div_eff(ch)
        main_vd = self._main_v_div()
        y_gain = self._y_mag()
        if y_gain <= 0:
            y_gain = 1.0
        if v_div <= 0:
            v_div = 1e-12
        return (base_v / v_div + self._v_pos_eff(ch)) * main_vd / y_gain

    def _find_trigger(self, src, span, after=None):
        spec = self._spec_of(src)
        if spec is None:
            return None
        # 使用耦合数据（DC原样 / AC去直流），所有触发类型统一数据源
        t, y = self._get_coupled_arrays(src)
        t, y = _dedupe_xy(np.asarray(t, dtype=float), np.asarray(y, dtype=float))
        if len(t) < 4 or len(y) < 4:
            # TRIG-05 修复：触发源为数学通道且数据为空时，在状态标签提示
            if self._is_math(src):
                self.lb_status.setText(tr("scope.trig_src_no_data"))
            return None
        # 显示电平（Y轴单位）→ 物理电平（通道单位），统一反解
        display_level = self.sp_trig_level.value()
        level = self._disp_to_phys(src, display_level)
        # 只检索可视窗前后 2 屏，避免大缓冲全量扫描
        if t[-1] - t[0] > span * 2:
            cut = int(np.searchsorted(t, t[-1] - span * 2, side="left"))
            if cut > 0:
                t = t[cut - 1:]
                y = y[cut - 1:]
        edge = self.cb_trig_edge.currentData() or "rise"
        rising = edge != "fall"        # 脉宽/欠幅触发：双沿按上升处理
        ttype = self._trig_type()
        if ttype == "pulse":
            return self._find_trigger_pulse(t, y, level, rising, after)
        if ttype == "runt":
            hi = self._disp_to_phys(src, self.sp_runt_hi.value())
            return self._find_trigger_runt(t, y, level, hi, rising, after)
        if ttype == "timeout":
            return self._find_trigger_timeout(t, y, level, after)
        if ttype == "window":
            hi = self._disp_to_phys(src, self.sp_win_hi.value())
            lo = self._disp_to_phys(src, self.sp_win_lo.value())
            return self._find_trigger_window(t, y, lo, hi, after)
        if ttype == "risetime":
            return self._find_trigger_risetime(
                t, y, level, rising, self.sp_rt_time.value(), after)
        # 默认：边沿触发（与 _cross_times 一致的严格前/含等后越阈检测）
        if edge == "both":
            cross = (((y[:-1] < level) & (y[1:] >= level))
                     | ((y[:-1] > level) & (y[1:] <= level)))
        elif edge == "fall":
            cross = (y[:-1] > level) & (y[1:] <= level)
        else:
            cross = (y[:-1] < level) & (y[1:] >= level)
        idx = np.flatnonzero(cross)
        if idx.size == 0:
            return None
        # BUG-09 修复：原代码用 t[idx+1] 与 after 比较，应使用线性插值得到的精确触发时刻。
        y0_arr = y[idx]
        y1_arr = y[idx + 1]
        denom_arr = y1_arr - y0_arr
        frac_arr = np.divide(level - y0_arr, denom_arr,
                             out=np.zeros_like(denom_arr, dtype=float),
                             where=denom_arr != 0.0)
        trig_times = t[idx] + frac_arr * (t[idx + 1] - t[idx])
        if after is not None:
            candidate = trig_times[trig_times > after]
            if candidate.size == 0:
                return None
            return float(candidate[0])
        return float(trig_times[-1])

    def _find_trigger_pulse_cond(self, widths, times, after):
        cond = self.cb_pw_cond.currentData() or "greater"
        threshold = self.sp_pw_width.value()
        for w, time_val in zip(widths, times):
            ok = w > threshold if cond == "greater" else w < threshold
            if ok and (after is None or time_val > after):
                return float(time_val)
        return None

    def _find_trigger_pulse(self, t, y, level, rising, after):
        rise = _cross_times(t, y, level, rising=True)
        fall = _cross_times(t, y, level, rising=False)
        starts = rise if rising else fall
        ends = fall if rising else rise
        widths, times = [], []
        j = 0
        for s in starts:
            while j < len(ends) and ends[j] <= s:
                j += 1
            if j >= len(ends):
                break
            e = ends[j]
            w = float(e - s)
            if w > 0:
                widths.append(w)
                times.append(float(e))
        if not widths:
            return None
        return self._find_trigger_pulse_cond(widths, times, after)

    def _find_trigger_runt(self, t, y, lo, hi, rising, after):
        """欠幅触发：正欠幅（越 LO 未越 HI）或负欠幅（越 HI 未越 LO）。"""
        if hi < lo:
            lo, hi = hi, lo
        if rising:
            rise_lo = _cross_times(t, y, lo, rising=True)
            fall_lo = _cross_times(t, y, lo, rising=False)
            rise_hi = _cross_times(t, y, hi, rising=True)
            for right_layout in sorted(rise_lo):
                candidates = fall_lo[fall_lo > right_layout]
                if candidates.size == 0:
                    continue
                fall_low_t = float(candidates[0])
                if np.any((rise_hi > right_layout) & (rise_hi < fall_low_t)):
                    continue          # 中途穿越了高阈值，属于完整脉冲而非欠幅
                if after is None or fall_low_t > after:
                    return fall_low_t
        else:
            fall_hi = _cross_times(t, y, hi, rising=False)
            rise_hi2 = _cross_times(t, y, hi, rising=True)
            fall_lo = _cross_times(t, y, lo, rising=False)
            for fall_high_t in sorted(fall_hi):
                candidates = rise_hi2[rise_hi2 > fall_high_t]
                if candidates.size == 0:
                    continue
                rise_high_t = float(candidates[0])
                if np.any((fall_lo > fall_high_t) & (fall_lo < rise_high_t)):
                    continue
                if after is None or rise_high_t > after:
                    return rise_high_t
        return None

    def _find_trigger_timeout(self, t, y, level, after):
        """超时触发：信号保持高于/低于触发电平超过设定时长后，在当前时间触发。"""
        state = self.cb_to_state.currentData() or "above"
        threshold = self.sp_to_time.value()
        cond = (y > level) if state == "above" else (y < level)
        cond = np.asarray(cond, dtype=bool)
        if not np.any(cond):
            return None
        # 沿分割出保持区间：[s, e) 内 cond 恒为 True/False
        edges = np.flatnonzero(np.diff(cond.astype(np.int8)) != 0)
        bounds = [0] + (edges + 1).tolist() + [len(cond)]
        for s, e in zip(bounds[:-1], bounds[1:]):
            if s < e and cond[s]:
                t0 = float(t[s])
                t1 = float(t[e - 1])
                if t1 - t0 >= threshold:
                    time_val = t0 + threshold
                    if after is None or time_val > after:
                        return float(time_val)
        return None

    def _find_trigger_window(self, t, y, lo, hi, after):
        """窗口触发：信号穿越窗口边界（进入或退出）的瞬间作为触发沿。

        BUG-14 修复：原代码仅检测「进入窗口」，手册描述为「进入或越窗」。
        现改为检测 inside 状态的任何跳变（进入或退出均触发）。
        同时修复 after 筛选使用精确插值时刻而非采样点。
        """
        if hi < lo:
            lo, hi = hi, lo
        inside = (y >= lo) & (y <= hi)
        edge = inside[1:] != inside[:-1]   # 进入或退出窗口边界
        idx = np.flatnonzero(edge)
        if idx.size == 0:
            return None
        # 穿越时刻用线性插值（在窗口边界 lo 或 hi 处）
        trig_times = []
        for i in idx:
            y0, y1 = float(y[i]), float(y[i + 1])
            if y0 == y1:
                trig_times.append(float(t[i + 1]))
                continue
            # 确定穿越的是 lo 还是 hi 边界
            target = lo if (y0 < lo <= y1 or y0 > lo >= y1) else hi
            if not (min(y0, y1) <= target <= max(y0, y1)):
                target = lo if abs(y0 - lo) < abs(y0 - hi) else hi
            frac = (target - y0) / (y1 - y0)
            trig_times.append(float(t[i] + frac * (t[i + 1] - t[i])))
        trig_times = np.array(trig_times)
        if after is not None:
            candidate = trig_times[trig_times > after]
            if candidate.size == 0:
                return None
            return float(candidate[0])
        return float(trig_times[-1])

    def _find_trigger_risetime(self, t, y, level, rising, threshold, after):
        """上升/下降时间触发：边沿在 10%–90% 之间的转换耗时超过阈值时触发。"""
        del level  # 阈值基于信号自身 10%/90% 计算，与电平参考线解耦
        lo = float(np.min(y))
        hi = float(np.max(y))
        if hi - lo <= 1e-12:
            return None
        l10 = lo + 0.1 * (hi - lo)
        l90 = lo + 0.9 * (hi - lo)
        if rising:
            starts = _cross_times(t, y, l10, rising=True)
            ends = _cross_times(t, y, l90, rising=True)
        else:
            starts = _cross_times(t, y, l90, rising=False)
            ends = _cross_times(t, y, l10, rising=False)
        for s in starts:
            candidates = ends[ends > s]
            if candidates.size == 0:
                continue
            e = float(candidates[0])
            if (e - s) >= threshold:
                if after is None or e > after:
                    return float(e)
        return None

    def _on_timer(self):
        try:
            # 后台页签不重绘：切换其它页签时示波器/FFT/测量全部停止刷新，
            # 是所有串口助手里最容易造成“界面卡顿”的隐藏 CPU 占用来源
            if self.isVisible() and not self.window().isMinimized():
                self._update()
        except Exception as exc:
            _log_refresh_error("WaveformPanel._on_timer", exc)

    def _on_measure_timer(self):
        try:
            if self.isVisible() and not self.window().isMinimized():
                self._update_measures()
                self.cursor._auto_refresh()   # Auto 光标：随测量结果周期性更新（内部按版本节流）
        except Exception as exc:
            _log_refresh_error("WaveformPanel._on_measure_timer", exc)

    def shutdown(self):
        """窗口关闭前停止本面板所有计时器（BUG-O 清理）。"""
        self._timer.stop()
        self._measure_timer.stop()
        if hasattr(self, "_range_debounce") and self._range_debounce.isActive():
            self._range_debounce.stop()

    def _update(self):
        if not self.channels:
            return
        if not self._dirty and not self._view_dirty:
            return
        # 自动垂直灵敏度（有数据且波形不可见/出屏时自动选档）
        self._auto_vdiv_apply()
        if not self.running and self.mode != "single":
            if self._last_window is not None:
                # BUG-01 修复：_last_window 是已减去 h_pos 的最终窗口，原始中心需加回 h_pos
                center = (self._last_window[0] + self._last_window[1]) / 2.0 + self._last_hpos
                span = self.timebase * DIVS
                self._draw_window(center - span / 2.0, center + span / 2.0)
            elif self._dirty:
                self._update_auto()
            self._dirty = False
            self._view_dirty = False
            return
        if self.mode == "single":
            self._update_single()
        elif self.mode == "auto":
            self._update_auto()
        else:
            self._update_normal()
        self._dirty = False
        self._view_dirty = False

    def _update_auto(self):
        """Auto 模式采用自由滚动（与软件初始状态一致）。
        修复：Auto 后触发电平被设为信号中位 → 触发检测稳定命中 → 触发定位锁定
        窗口，波形停止平滑滚动（冻结/防抖跳变）→ 用户感知「滚动卡顿不丝滑」。
        现改为 Auto 模式始终自由滚动：波形右对齐最新数据、从右向左连续平滑移动，
        与软件启动后的初始滚动行为完全一致。
        Auto 仍会设置好时基/垂直灵敏度/触发电平/触发源（其他功能完全不变）；
        如需触发定位稳定显示，切换到 Normal / Single 触发模式即可。"""
        span = self.timebase * DIVS
        last = None
        for ch in self.channels:
            if not self.channels[ch]["enabled"]:
                if ch in self.curves:
                    self.curves[ch].setVisible(False)
                continue
            self._ensure_curve(ch)
            t, _ = self._get_arrays(ch)
            if len(t) == 0:
                self.curves[ch].setVisible(False)
                continue
            if last is None or t[-1] > last:
                last = t[-1]
        if last is None:
            return
        # 自由滚动：右对齐到最新数据，波形从右向左连续移动（与初始状态一致）
        self._draw_window(last - span, last)
        self.lb_status.setText(trf("scope.status_running", n=len(self._t.get(0, []))))

    def _fit_trigger_window(self, trig_t, span, data_end):
        """标准示波器触发窗口：数据充足时触发点位于屏幕正中央
        （窗口 = [触发点−5格, 触发点+5格]，右侧极值=时基×5，左侧极值=−时基×5）。
        实时流中触发点通常接近数据末尾、其后不足半屏：此时右对齐到数据末尾
        （波形填满屏幕，不出现右半空白——标准示波器无预触发缓冲时的行为）。
        水平位置(在_draw_window中)再左移/右移触发点。"""
        half = span / 2.0
        x0 = trig_t - half
        x1 = trig_t + half
        if data_end is not None:
            if x1 > data_end:
                # 触发点后数据不足半屏：右对齐数据末尾，波形填满屏幕
                x1 = data_end
                x0 = x1 - span
                if x0 < 0:
                    x0 = 0.0
            elif x0 < 0:
                # 触发点前数据不足：左对齐数据起点
                x0 = 0.0
                x1 = span
        return x0, x1

    def _update_normal(self):
        src = self._trig_ch_key()
        span = self.timebase * DIVS
        last = None
        for ch in self.channels:
            if not self.channels[ch]["enabled"]:
                continue
            t, _ = self._get_arrays(ch)
            if len(t) == 0:
                continue
            time_last = float(t[-1])
            last = time_last if last is None or time_last > last else last
        if last is None:
            return
        trig_t = self._find_trigger(src, span)
        if trig_t is not None:
            x0, x1 = self._fit_trigger_window(trig_t, span, last)
            self._draw_window(x0, x1)
            self.lb_status.setText(trf("scope.status_running", n=len(self._t.get(0, []))))
        else:
            # TRIG-04 修复：Normal 模式未触发时显示"等待触发"，不更新显示（保持上一帧）
            self.lb_status.setText(tr("scope.status_normal_wait"))

    def _update_single(self):
        if self.single_armed and not self.single_done:
            if not self.running:
                return
            src = self._trig_ch_key()
            span = self.timebase * DIVS
            last = None
            for ch in self.channels:
                if not self.channels[ch]["enabled"]:
                    continue
                t, _ = self._get_arrays(ch)
                if len(t):
                    time_last = float(t[-1])
                    last = time_last if last is None or time_last > last else last
            trig_t = self._find_trigger(src, span, after=self._trig_arm_t)
            if trig_t is not None:
                x0, x1 = self._fit_trigger_window(trig_t, span, last)
                self._draw_window(x0, x1)
                self.single_done = True
                self.single_armed = False
                self.running = False
                self.btn_run.blockSignals(True)
                self.btn_run.setChecked(False)
                self.btn_run.blockSignals(False)
                self._update_run_btn_text()
                src_spec = self._spec_of(src)
                src_name = src_spec["name"] if src_spec else str(src)
                self.lb_status.setText(trf("scope.status_single_done",
                                           name=src_name))
        elif self.single_done:
            if self._view_dirty and self._last_window is not None:
                # BUG-01 修复：同上，原始中心需加回 h_pos
                center = (self._last_window[0] + self._last_window[1]) / 2.0 + self._last_hpos
                span = self.timebase * DIVS
                self._draw_window(center - span / 2.0, center + span / 2.0)
            self._view_dirty = False
        else:
            self._update_auto()

    def _ensure_curve(self, ch):
        if ch not in self.curves:
            spec = self._spec_of(ch)
            if spec is None:
                return
            if self.display_mode == "dot":
                self.curves[ch] = self.plot.plot(pen=None, symbol="o", symbolSize=3,
                                                 symbolBrush=QColor(spec["color"]),
                                                 name=spec["name"])
            else:
                self.curves[ch] = self.plot.plot(pen=pg.mkPen(spec["color"], width=1.5),
                                                 name=spec["name"])
            # 该通道 0V 垂直参考点 + 通道标签（颜色与波形一致）
            # z 层级置底，避免遮挡可拖拽的光标线与触发电平线
            if ch not in self._ground_refs:
                ground_item = GroundRefItem()
                try:
                    ground_item.setZValue(-3)
                except Exception:  # noqa: BLE001
                    pass
                self.plot.addItem(ground_item, ignoreBounds=True)
                self._ground_refs[ch] = ground_item
            if ch not in self._ch_labels:
                # 0V 参考 = 小箭头 + 通道标签（➡ch1），箭头很小
                # 可交互通道标签——拖动/滚轮调节垂直位置
                ch_label = ChannelLabelItem("➡" + spec["name"], color=spec["color"],
                                      channel_key=ch, panel=self, anchor=(0.0, 0.5))
                ch_label.setVisible(False)
                try:
                    ch_label.setZValue(-2)
                except Exception:  # noqa: BLE001
                    pass
                self.plot.addItem(ch_label, ignoreBounds=True)
                self._ch_labels[ch] = ch_label

    def _draw_window(self, x0, x1):
        # 记录原始跨度，钳位后保持X轴长度不变（标准示波器：时基固定则屏幕时间跨度固定）
        orig_span = x1 - x0
        # 应用水平位置：正值回看更早数据；左缘不早于零点
        x0 -= self.h_pos
        x1 -= self.h_pos
        x0 = max(x0, 0.0 if self.t0 is not None else -1e18)
        x1 = x0 + orig_span  # 钳位后保持跨度不变，X轴长度严格等于时基×格数
        if x1 < x0:
            x1 = x0
        # 固定屏幕坐标系（真实示波器）：波形用「相对屏幕中心」的坐标，
        # X 轴范围恒为 [-span/2, +span/2] → 背景格线/刻度固定不动，只有采样数据点移动。
        center = (x0 + x1) / 2.0
        half = orig_span / 2.0
        # 禁用重绘：批量更新所有曲线数据和X轴范围后统一刷新，避免中间状态导致重影
        self.plot.setUpdatesEnabled(False)
        try:
            # 数学通道在重绘前重算（仅当存在启用项，避免无谓开销）
            if any(s["enabled"] for s in self.maths.values()):
                self._compute_math()
            # 收集待绘制的通道：模拟通道 + 启用数学通道
            draw_chs = list(self.channels)
            for key, spec in self.maths.items():
                if spec["enabled"]:
                    draw_chs.append(key)
            for ch in draw_chs:
                spec = self._spec_of(ch)
                if spec is None:
                    continue
                # 数学通道用 visible（波形显示开关），物理通道用 enabled
                if self._is_math(ch):
                    _is_on = spec.get("visible", True)
                else:
                    _is_on = spec.get("enabled", True)
                if not _is_on:
                    if ch in self.curves:
                        self.curves[ch].setVisible(False)
                    continue
                self._ensure_curve(ch)
                # 只取可视窗口内的耦合数据（避免整条 FIFO 全量复制造成内存峰值）
                t, y = self.dh.get_coupled_window(ch, x0, x1)
                n = len(t)
                if n == 0:
                    self.curves[ch].setVisible(False)
                    continue
                idx_start = int(np.searchsorted(t, x0, side="left"))
                idx_end = int(np.searchsorted(t, x1, side="right"))
                if idx_start > 0:
                    idx_start -= 1
                if idx_end <= idx_start or idx_end > n:
                    idx_end = min(n, idx_end)
                if idx_end <= idx_start:
                    self.curves[ch].setVisible(False)
                    continue
                t_ghost = t[idx_start:idx_end]
                y_ghost = self._display_y(ch, y[idx_start:idx_end])
                # 大数据窗加固：当可视窗口含数十万点以上时先大步抽取，再交给 min/max
                # 包络，避免 1S/div 以上大时基下每帧生成巨额中间数组造成内存抖动卡死。
                m = idx_end - idx_start
                if m > _DRAW_RAW_MAX:
                    step = int(math.ceil(m / _DRAW_RAW_MAX))
                    t_ghost = t_ghost[::step]
                    y_ghost = y_ghost[::step]
                t_ghost, y_ghost = _downsample(t_ghost, y_ghost)
                # 绝对时间 → 相对屏幕中心坐标（格线固定，数据移动）
                x_disp = np.asarray(t_ghost, dtype=float) - center
                # 确保数据是连续数组，避免pyqtgraph渲染残留导致重影
                self.curves[ch].setData(
                    np.ascontiguousarray(x_disp), np.ascontiguousarray(y_ghost))
                self.curves[ch].setVisible(True)
            # X 轴范围固定 → 格线固定不动
            self.plot.setXRange(-half, half, padding=0)
            # 软件初始状态及全程移除坐标刻度显示（X 轴刻度清空 +
            # 轴已隐藏双保险，任何环境下波形区都不显示坐标刻度数值与刻度线）
            try:
                _ax = self.plot.getAxis("bottom")
                _ax.setTicks([])
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.plot.setUpdatesEnabled(True)
        self._last_window = (x0, x1)
        self._last_center = center
        self._last_hpos = self.h_pos
        # 每次重绘同步标准示波器 Y 轴范围（±5×主通道垂直灵敏度）
        self._update_y_range()
        self._sync_trig_range()
        self._update_trig_marker()
        # 光标随波形重绘同步：
        # - Track Scaling（数据锚定）：视图中心与垂直换算参数已更新为最新值，
        #   光标按快照的数据坐标重映射，缩放/平移后相对波形相位保持不变。
        # - Track 模式（跟踪）：垂直位置/灵敏度变化不改变 Y 视图范围，
        #   sigRangeChanged 不触发，必须在此主动重新吸附波形，否则光标脱靶。
        if self.cursor.mode == MODE_TRACK and not self.cursor.track_scaling:
            self.cursor._sync_track()
        else:
            self.cursor._remap_anchored()
        # 同步示波器专业参考元素（t=0 触发点 / 中心虚线 / 通道 0V 参考点与标签）
        self._update_reference_markers()

    # ------------------------------------------------------------- Auto 自动设置
    def _on_auto(self):
        self._autoscale()
        self._mark_dirty()

    @staticmethod
    def _round_to_125(value):
        """把正值向上取整到 1-2-5 标准序列（示波器档位标准）。"""
        if value <= 0:
            return 1.0
        exp = math.floor(math.log10(value))
        base = 10 ** exp
        frac = value / base
        if frac <= 1:
            return 1.0 * base
        if frac <= 2:
            return 2.0 * base
        if frac <= 5:
            return 5.0 * base
        return 10.0 * base

    def _autoscale(self):
        """Auto Setup 自动设置（V2.0 完全重写）。

        严格按专业示波器 Auto Setup 规范实现：一次按键将各启用通道快速配置
        到能稳定显示信号的状态。本实现**不改变任何通道的耦合设置**（DC/AC
        保持用户配置），DC 与 AC 耦合波形在 Auto 后均能正常显示：

        阶段一：通道扫描——统计各启用通道当前耦合数据的 Vpp/极值/均值；
        阶段二：主控通道——有效通道（Vpp≥2mV）中峰峰值最大者（电压最高通道），
                并将其设为触发源；
        阶段三：水平时基——测量主控通道波动主频，显示约 3 个完整周期，
                按 1-2-5 序列向上取整；<20Hz 或测不出频率时强制 100ms/div；
        阶段四：垂直档位——每通道独立计算（1-2-5 取整）：
                · AC 耦合：V/div = Vpp/7，波动占屏幕 70% 高度，以 0V 为中心；
                · DC 耦合：V/div = max(Vpp/7, |DC偏置|/5)，波动与直流位置
                  均落在屏幕 ±5 格内；
        阶段五：触发——源=主控通道，电平=主控中位值（50%），上升沿，
                Auto 触发模式（无触发时强制扫描保证屏幕不空白）。
        输出：立即重绘 + 参数配置清单 + 警告信息（采样率不足/频率过低/噪声）。
        """
        warnings = []
        enabled = [ch for ch, info in self.channels.items() if info["enabled"]]
        for mkey, mspec in self.maths.items():
            if mspec.get("enabled", False) and mspec.get("visible", True):
                enabled.append(mkey)
        if not enabled:
            self.lb_status.setText(tr("scope.auto_no_channel"))
            return

        # ===== 阶段一：通道扫描与数据统计（当前耦合数据）=====
        ch_data = {}
        last_time = 0.0
        for ch in enabled:
            t, y = self._get_coupled_arrays(ch)
            y = np.asarray(y, dtype=float)
            if y.size < 2 or t.size < 2:
                continue
            vpp = float(np.ptp(y))
            v_max = float(np.max(y))
            v_min = float(np.min(y))
            mean_val = float(np.mean(y))
            ch_data[ch] = (t, y, vpp, v_max, v_min, mean_val)
            if t.size and float(t[-1]) > last_time:
                last_time = float(t[-1])

        if not ch_data:
            # 无任何有效数据：重置水平位置并提示
            self._set_hpos(0.0)
            self.lb_status.setText(tr("scope.auto_no_data"))
            return

        # ===== 阶段二：主控通道选择（电压最高通道）=====
        MIN_VPP = 0.002  # 2mVpp：低于此阈值视为噪声/无效信号（专业规范 >2mVpp）
        valid_chs = [ch for ch, (_, _, vpp, _, _, _) in ch_data.items()
                     if vpp >= MIN_VPP]
        if not valid_chs:
            # 全部低于阈值：退化为使用第一个有数据的通道，并告警
            valid_chs = list(ch_data.keys())
            warnings.append("all channels below 2mV threshold (noise)")
        # 可排序通道序号：物理通道(ch1..ch8, int)优先于数学通道(m1..m4, str)，
        # 避免 min/max 混合类型比较崩溃（TypeError: '<' not supported）
        def _ch_order(c):
            return (0, c) if isinstance(c, int) else (1, str(c))
        # 主控/触发源仅从物理通道中选择（数学通道为派生信号，真实示波器规范
        # 上不作为触发源）；仅数学通道启用的极端情况下回退到全部有效通道
        phys_pool = [c for c in valid_chs if isinstance(c, int)]
        pool = phys_pool if phys_pool else valid_chs
        # 主控 = 有效通道中峰峰值最大者（电压最高通道）；多个通道幅值相近
        # （相差 <30%）时按专业规范优先编号较小的通道（如 CH1），避免触发源随意跳变
        master_ch = max(pool, key=lambda c: ch_data[c][2])
        max_vpp = ch_data[master_ch][2]
        min_ch = min(pool, key=_ch_order)
        if max_vpp > 0 and ch_data[min_ch][2] >= max_vpp * 0.7:
            master_ch = min_ch
        t_m, y_m, vpp_m, v_max_master, v_min_master, mean_master = ch_data[master_ch]

        # 立即将触发源设为主控通道：确保后续触发电平换算与 Y 轴刻度
        # 均基于主控通道（电压最高通道）的垂直灵敏度
        for i in range(self.cb_trig_src.count()):
            if self.cb_trig_src.itemData(i) == master_ch:
                self.cb_trig_src.blockSignals(True)
                self.cb_trig_src.setCurrentIndex(i)
                self.cb_trig_src.blockSignals(False)
                break

        # ===== 阶段三：水平时基计算 =====
        # 基于主控通道去均值后的波动信号测主频（对 DC 偏置信号同样可靠）
        period, frequency = self._estimate_period(y_m - mean_master, t_m)
        fs = 0.0
        if t_m.size >= 2:
            delta_t = np.diff(t_m)
            delta_t = delta_t[delta_t > 0]
            fs = float(1.0 / np.median(delta_t)) if delta_t.size else 0.0
        if period is None or period <= 0:
            # 无法测出周期（直流/静音/强噪声）：时基强制 100ms/div（保守大时基）
            timebase_idx = min(range(len(TIMEBASE)), key=lambda i: abs(TIMEBASE[i][1] - 0.1))
            warnings.append("period undetectable, forced 100ms/div")
        else:
            # 周期法适用于低频与中高频：屏上 2~5 个完整周期（专业规范）。
            # 低频（<20Hz）不再强制 100ms/div——那会导致屏上 8 个甚至更多周期，
            # 违反 2~5 周期约束（如 8Hz 信号 100ms/div 屏上 8 周期）。
            if frequency is not None and frequency < 20.0:
                warnings.append(f"low frequency {frequency:.4g}Hz (<20Hz)")
            # 显示约 3 个完整周期；硬性约束屏上 2~5 个完整周期（专业 Auto 规范）。
            # 屏上周期数 N = timebase*DIVS/period → 要 2≤N≤5 须 period/5 ≤ timebase ≤ period/2。
            # 原实现 raw_timebase=period/3 向下取整，1-2-5 档位跳变可致屏上仅 1.33~1.67 个周期
            # （不足 2 个，违反规范）——修复：在 [period/5, period/2] 区间内选最接近
            # period/3 的 1-2-5 档位，保证 2~5 个完整周期。
            raw_timebase = period / 3.0
            timebase_lo = period * 2.0 / DIVS    # 对应屏上 2 个周期
            timebase_hi = period * 5.0 / DIVS    # 对应屏上 5 个周期
            timebase_idx = 0
            best_d = float("inf")
            for i, (_, val) in enumerate(TIMEBASE):
                if timebase_lo - 1e-12 <= val <= timebase_hi + 1e-12:
                    d = abs(val - raw_timebase)
                    if d < best_d:
                        best_d = d
                        timebase_idx = i
            if best_d == float("inf"):
                # 无档位落在区间内（档位离散极限）：退化为最接近 raw_timebase 的档位
                timebase_idx = min(range(len(TIMEBASE)),
                             key=lambda i: abs(TIMEBASE[i][1] - raw_timebase))
            if fs > 0 and fs < frequency * 10.0:
                warnings.append(f"sample rate {fs:.1f}Hz < 10x frequency {frequency:.1f}Hz, may alias")

        self._set_timebase_value(TIMEBASE[timebase_idx][1])

        # AUTO-FIX：时基过大导致屏幕跨度远超数据总时长时减小时基，使波形填满屏幕。
        # 修复：原实现「选 ≤max_tb 的最大档」可能把时基减到屏上仅 1.3~1.7 个周期
        # （违反专业规范 2~5 周期，如数据 4 周期时被减到 1.6 周期）。现改为在
        # 「跨度≤数据1.5倍 且 屏上周期∈[2,5]」的档位中选最接近 3 个周期的档；
        # 数据过短无候选时，退化为跨度最接近数据总时长的档位（尽可能显示完整波形）。
        span = TIMEBASE[timebase_idx][1] * DIVS
        if last_time > 0 and span > last_time * 1.5:
            max_span = last_time * 1.5
            candidates = []
            for i, (_, val) in enumerate(TIMEBASE):
                if val * DIVS <= max_span + 1e-12 and period and period > 0:
                    num_cycles = val * DIVS / period
                    if 2 - 1e-9 <= num_cycles <= 5 + 1e-9:
                        candidates.append((abs(num_cycles - 3.0), i))
            if candidates:
                _, timebase_idx = min(candidates)
            else:
                # 数据不足以满足 2~5 周期（如数据仅 1~2 个周期）：优先显示完整
                # 波形——选「屏幕跨度≥数据总时长」的最小档（屏能容纳全部数据），
                # 数据超最大档时用最大档；避免原逻辑选中跨度小于数据的档位丢掉波形。
                timebase_idx = min(range(len(TIMEBASE)),
                             key=lambda i: (TIMEBASE[i][1] * DIVS < last_time,
                                            abs(TIMEBASE[i][1] * DIVS - last_time)))
            if TIMEBASE[timebase_idx][1] != self.timebase:
                self._set_timebase_value(TIMEBASE[timebase_idx][1])
                warnings.append(f"timebase reduced to fit data span ({last_time:.3g}s)")

        # ===== 阶段四：垂直档位（各通道独立，不改变耦合）=====
        # 专业 Auto 规范支持两种垂直布局：
        # ① 叠加模式（Overlay）：算法优先调整刻度（V/div），波形幅度最大化至
        #    70%~80% 屏高（约 6~7.2 格）；0V 参考地线固定在屏幕垂直中心
        #    （v_pos 默认 0，不移动位置）；仅当直流偏置导致波形溢出屏幕时
        #    （峰值>屏顶-0.5格 或 谷值<屏底+0.5格），才引入垂直偏移（v_pos）
        #    将波形拉回视野；若 v_pos 已到极限仍溢出，则增大 V/div 使波形满足
        #    「不削顶（No Clipping）」硬性约束。
        # ② 通道分离模式（Channel Separation）：启用通道≥2 时自动启用（Keysight
        #    Autoscale 风格）——启用通道按编号从上到下各占一段屏幕，第 i 通道
        #    区域中心 = 5-(i+0.5)*10/N div，波形互不重叠；每通道 V/div 独立设置
        #    为波动占其区域高度 70%（区域内最大化、不削顶），v_pos 设为区域中心
        #    并补偿 DC 偏置。多通道同时观察时波形清晰可辨（用户需求）。
        enabled_order = sorted(enabled,
                               key=lambda c: (0, c) if isinstance(c, int) else (1, str(c)))
        # 通道分离只对「有有效数据」的启用通道分配区域；无数据通道不占区域
        # （避免默认启用但无数据的通道挤占显示空间，导致有数据通道区域过小）。
        sep_chs = [c for c in enabled_order if c in ch_data]
        separate = len(sep_chs) >= 2
        self._auto_separate = separate

        def _apply_auto_v(ch, v_div, v_pos):
            """同步通道的 V/div 与 v_pos 到面板控件（阶段四共用尾部）。"""
            spec = self._spec_of(ch)
            if spec is None:
                return
            spin = self._scale_spins.get(ch)
            if spin is not None:
                spin.blockSignals(True)
                txt = _fmt_vdiv(v_div)
                idx = spin.findText(txt)
                if idx >= 0:
                    spin.setCurrentIndex(idx)
                else:
                    spin.setCurrentText(txt)
                spin.blockSignals(False)
            offset_spin = self._offset_spins.get(ch)
            if offset_spin is not None:
                offset_spin.blockSignals(True)
                offset_spin.setValue(v_pos)
                offset_spin.blockSignals(False)
                offset_spin.setEnabled(spec.get("coupling") != "ac")
                ac_disable = (spec.get("coupling") == "ac")
                offset_spin.setToolTip(tr("scope.offset_ac_disabled") if ac_disable
                              else tr("scope.offset_tip"))

        if separate:
            # ---- 通道分离排列（Keysight Autoscale 风格）----
            region_h = V_DIVS / len(sep_chs)            # 每区高度（div）
            region_half = region_h / 2.0
            region_pp = region_h * 0.7                  # 波形峰峰值占区域 70%
            for i, ch in enumerate(sep_chs):
                spec = self._spec_of(ch)
                if spec is None:
                    continue
                if ch not in ch_data:
                    # 无数据通道设默认档位，避免残留
                    spec["v_div"] = 1.0
                    spec["v_pos"] = 0.0
                    _apply_auto_v(ch, 1.0, 0.0)
                    continue
                _, _, vpp, _, _, mean_ch = ch_data[ch]
                ch_gain = self._ch_mag(ch)
                vpp_voltage = vpp * ch_gain
                mid_voltage = float(mean_ch) * ch_gain  # DC 偏置（AC 已去直流≈0）
                if vpp_voltage <= 0 or not np.isfinite(vpp_voltage):
                    spec["v_div"] = 1.0
                    spec["v_pos"] = 0.0
                    _apply_auto_v(ch, 1.0, 0.0)
                    continue
                center_i = V_DIVS / 2.0 - (i + 0.5) * region_h  # 区域中心（div）
                # 波动占区域 70% 的 V/div（区域最大化）
                vd_need = vpp_voltage / region_pp
                half_voltage = vpp_voltage / 2.0
                # 波动不削顶硬约束：峰/谷离区域边界留 0.15 半区余量
                if half_voltage / vd_need > region_half * 0.85:
                    vd_need = half_voltage / (region_half * 0.85)
                v_div = 1.0 if vd_need < 1e-12 else self._round_to_125(vd_need)
                # 限制在垂直灵敏度下拉可选档位范围内（V_DIV_STEPS）
                v_div = max(V_DIV_STEPS[0], min(V_DIV_STEPS[-1], v_div))
                # 用「最终档位 v_div」把波形中点（含 DC 偏置）拉到区域中心：
                # v_pos = center - mid_voltage/v_div（必须在 1-2-5 取整后再算，
                # 否则取整造成的档位变化会让波形中点偏移区域中心）。
                v_pos = center_i - mid_voltage / v_div
                v_pos = max(-V_POS_RANGE, min(V_POS_RANGE, v_pos))
                # v_pos 钳位后复核：波形中点必须位于区域内（±0.8 半区），
                # 否则增大 V/div 收缩（直流偏置过大时波形变小但完整显示）
                mid_pos = mid_voltage / v_div + v_pos
                inner_top = center_i + region_half * 0.8
                inner_bot = center_i - region_half * 0.8
                if mid_pos > inner_top:
                    den = inner_top - v_pos
                    if den > 1e-12:
                        vd_need = max(vd_need, mid_voltage / den)
                elif mid_pos < inner_bot:
                    den = inner_bot - v_pos
                    if den < -1e-12:
                        vd_need = max(vd_need, mid_voltage / den)
                if vd_need > v_div * 1.001:
                    # 中点越界需要更大档位：重取整并重算 v_pos
                    v_div = 1.0 if vd_need < 1e-12 else self._round_to_125(vd_need)
                    v_div = max(V_DIV_STEPS[0], min(V_DIV_STEPS[-1], v_div))
                    v_pos = center_i - mid_voltage / v_div
                    v_pos = max(-V_POS_RANGE, min(V_POS_RANGE, v_pos))
                spec["v_div"] = float(v_div)
                spec["v_pos"] = float(v_pos)
                _apply_auto_v(ch, v_div, v_pos)
            warnings.append(
                f"channels separated ({len(sep_chs)}ch stacked top-down)")
        else:
            # ---- 叠加模式（单通道居中 / 多通道叠加）----
            target_pp = V_DIVS * 0.7   # 7 格，占 70% 屏高
            edge_margin = AUTO_EDGE_MARGIN   # 峰值/谷值预留过冲观察余量（专业硬约束）
            top_lim = V_DIVS / 2.0 - edge_margin    # 4.5 格
            bot_lim = -V_DIVS / 2.0 + edge_margin   # -4.5 格
            for ch in enabled:
                spec = self._spec_of(ch)
                if spec is None:
                    continue
                if ch not in ch_data:
                    # 无数据通道设默认档位，避免残留
                    spec["v_div"] = 1.0
                    spec["v_pos"] = 0.0
                    _apply_auto_v(ch, 1.0, 0.0)
                    continue
                _, _, vpp, v_max_ch, v_min_ch, mean_ch = ch_data[ch]
                ch_gain = self._ch_mag(ch)
                vpp_voltage = vpp * ch_gain
                mid_voltage = float(mean_ch) * ch_gain   # DC 偏置（AC 耦合数据已去直流≈0）
                if vpp_voltage <= 0 or not np.isfinite(vpp_voltage):
                    spec["v_div"] = 1.0
                    spec["v_pos"] = 0.0
                    _apply_auto_v(ch, 1.0, 0.0)
                    continue
                half_voltage = vpp_voltage / 2.0
                if spec.get("coupling") == "ac":
                    # AC：波动占 70% 屏高，0V 居中，无直流分量
                    vd_need = vpp_voltage / target_pp
                    v_pos = 0.0
                else:
                    # DC：叠加模式——波动占 70%，0V 居中；溢出时 v_pos 拉回。
                    # 注意：溢出判断与 v_pos 计算一律用「1-2-5 取整后的最终档位」
                    # v_div_base（而非取整前 vd_need），否则微小信号取整跳档
                    # （如 0.000286→0.001，跳 3.5 倍）会造成误判溢出、v_pos 被
                    # 无谓拉离 0V。
                    vd_need = vpp_voltage / target_pp
                    v_div_base = self._round_to_125(vd_need)
                    v_div_base = max(V_DIV_STEPS[0], min(V_DIV_STEPS[-1], v_div_base))
                    peak_ok = (mid_voltage + half_voltage) / v_div_base <= top_lim
                    valley_ok = (mid_voltage - half_voltage) / v_div_base >= bot_lim
                    if peak_ok and valley_ok:
                        v_pos = 0.0   # 波形在屏内，保持 0V 居中、不移动位置
                    else:
                        # 溢出：引入垂直偏移把波形中点拉回屏幕中部区域。
                        # 优化：v_pos 限制在 ±3div（V_POS_AUTO_CENTER）——波形中点
                        # 保持在屏幕中部，既不贴顶也不贴底（用户要求：不能到最下面）；
                        # 偏置过大时增大 V/div 使波形整体收缩回中部区域并满足不削顶。
                        clamped = min(V_POS_AUTO_CENTER, -mid_voltage / v_div_base)
                        v_pos = max(-V_POS_AUTO_CENTER, clamped)
                        needed_div = v_div_base
                        den_top = top_lim - v_pos
                        if den_top > 0:
                            needed_div = max(needed_div, (mid_voltage + half_voltage) / den_top)
                        den_bot = bot_lim - v_pos
                        # 谷约束：(mid_voltage-half_voltage)/vd_need + v_pos >= bot_lim
                        # → vd_need >= (mid_voltage-half_voltage)/(bot_lim-v_pos)（分子分母同负 → 正下界）
                        # 原实现用 /(-den_bot) 当分子为负时得到负下界，导致偏置方向
                        # 相反的波形不增大档位而贴底——已修正。
                        if den_bot < 0:
                            needed_div = max(needed_div, (mid_voltage - half_voltage) / den_bot)
                        vd_need = needed_div
                v_div = 1.0 if vd_need < 1e-12 else self._round_to_125(vd_need)
                # 限制在垂直灵敏度下拉可选档位范围内（V_DIV_STEPS）：Auto 计算出的
                # 档位必须与控件可选档位一致（如最小 1mV/div），否则下拉无法显示
                v_div = max(V_DIV_STEPS[0], min(V_DIV_STEPS[-1], v_div))
                spec["v_div"] = float(v_div)
                spec["v_pos"] = float(v_pos)
                _apply_auto_v(ch, v_div, v_pos)

        # Y 轴范围固定 ±5×主通道垂直灵敏度（标准示波器），随后立即应用
        self._update_y_range()

        # ===== 阶段五：触发参数设定（触发源已在阶段二后确定，主控已就绪）=====
        # 触发电平 = 主控通道中位值（50%）
        trig_level_phys = (v_max_master + v_min_master) / 2.0
        trig_level_disp = self._phys_to_disp(master_ch, trig_level_phys)
        self._set_trig_level(trig_level_disp)
        # 触发类型 = 边沿，边沿 = 上升沿
        self.cb_trig_type.blockSignals(True)
        self.cb_trig_type.setCurrentIndex(0)
        self.cb_trig_type.blockSignals(False)
        self.cb_trig_edge.blockSignals(True)
        self.cb_trig_edge.setCurrentIndex(0)
        self.cb_trig_edge.blockSignals(False)
        # 触发模式 = Auto（无触发时强制扫描，保证屏幕始终有波形）
        if self.cb_trig_mode.currentIndex() != 0:
            self.cb_trig_mode.blockSignals(True)
            self.cb_trig_mode.setCurrentIndex(0)
            self.cb_trig_mode.blockSignals(False)
        self.mode = "auto"
        self.single_armed = False
        self.single_done = False
        self._last_stable_trig = None  # 重置触发防抖基准
        self.running = True
        if not self.btn_run.isChecked():
            self.btn_run.blockSignals(True)
            self.btn_run.setChecked(True)
            self.btn_run.blockSignals(False)
        self._update_run_btn_text()

        # ===== 立即重绘 + 全变量同步 =====
        self._set_hpos(0.0)
        self._sync_trig_range()
        # Auto 已明确设置垂直灵敏度，停用自动垂直灵敏度
        self._vdiv_auto = False
        span = self.timebase * DIVS
        # 波形居中显示：若数据总时长小于屏幕跨度，居中而非左对齐
        if last_time < span:
            center = last_time / 2.0
            x0 = center - span / 2.0
            x1 = center + span / 2.0
            if x0 < 0:
                x0 = 0.0
                x1 = span
        else:
            x1 = last_time
            x0 = x1 - span
        self._draw_window(x0, x1)
        # Auto 执行后重置触发防抖和无触发计数
        self._last_stable_trig = None
        self._auto_no_trig_count = 0

        # ===== 输出参数配置清单 + 警告 =====
        master_spec = self._spec_of(master_ch)
        src_name = master_spec["name"] if master_spec else str(master_ch)
        tb_label = TIMEBASE[timebase_idx][0]
        freq_str = f"{frequency:.4g}Hz" if frequency else "N/A"
        warn_str = "; ".join(warnings) if warnings else "none"
        self.lb_status.setText(
            f"Auto: master={src_name}, T/div={tb_label}, freq={freq_str}, "
            f"trig={trig_level_phys:.4g}V, {len(valid_chs)}ch, warnings=[{warn_str}]"
        )
    def _set_timebase_value(self, timebase_value):
        best = min(range(len(TIMEBASE)), key=lambda i: abs(TIMEBASE[i][1] - timebase_value))
        self.cb_timebase.blockSignals(True)
        self.cb_timebase.setCurrentIndex(best)
        self.cb_timebase.blockSignals(False)
        self.knob_tb.blockSignals(True)
        self.knob_tb.setValue(float(best))
        self.knob_tb.blockSignals(False)
        self._update_hpos_range()

    def _set_trig_level_center(self):
        """TRIG-CENTER：把触发电平设为触发源通道波形的中心位置。
        中心 = 触发源耦合数据 (Vmax+Vmin)/2 的物理值 → 显示值（×scale+offset，
        AC 耦合 offset 强制为 0，与 _display_y 一致）。数据不足时保持当前值。"""
        src = self._trig_ch_key()
        if src == -1:
            return
        spec = self._spec_of(src)
        if spec is None:
            return
        t, y = self._get_coupled_arrays(src)
        if y is None or y.size < 2:
            return
        # 物理中心（通道单位）→ 显示电平（Y轴单位）统一换算
        center_phys = (float(np.min(y)) + float(np.max(y))) * 0.5
        center_disp = self._phys_to_disp(src, center_phys)
        self._set_trig_level(center_disp)
        self._update_trig_marker()

    def _set_trig_level(self, v):
        # 若当前量程不含目标值，先扩容，避免 setValue 被钳制
        lo, hi = self.sp_trig_level.minimum(), self.sp_trig_level.maximum()
        if v < lo or v > hi:
            self.sp_trig_level.setRange(min(v, lo) - 0.001, max(v, hi) + 0.001)
            self.knob_trig.setRange(min(v, lo) - 0.001, max(v, hi) + 0.001)
        self.sp_trig_level.blockSignals(True)
        self.sp_trig_level.setValue(v)
        self.sp_trig_level.blockSignals(False)
        self.knob_trig.blockSignals(True)
        self.knob_trig.setValue(v)
        self.knob_trig.blockSignals(False)

    def _set_hpos(self, v):
        self.h_pos = float(v)
        self.knob_hpos.blockSignals(True)
        self.knob_hpos.setValue(self.h_pos)
        self.knob_hpos.blockSignals(False)

    def _update_hpos_range(self):
        span = self.timebase * DIVS
        self.knob_hpos.setRange(-span / 2.0, span / 2.0)
        self.h_pos = self.knob_hpos.value()

    def _hpos_fmt(self, v):
        """水平位置显示：单位随时基自适应（s/ms/µs），内部数值恒为秒。"""
        timebase_value = self.timebase
        if timebase_value < 1e-3:
            return f"{v * 1e6:.3g} µs"
        if timebase_value < 1.0:
            return f"{v * 1e3:.3g} ms"
        return f"{v:.3g} s"

    # ------------------------------------------------------------- 数据上限（FIFO）
    def _on_refresh_changed(self, v):
        """波形刷新频率改变：修改定时器间隔（1000/refresh_rate ms）。"""
        refresh_rate = max(1.0, min(60.0, float(v)))
        interval = int(1000.0 / refresh_rate)
        self._timer.setInterval(interval)

    def _on_limit_changed(self, _idx):
        val = self.cb_limit.itemData(self.cb_limit.currentIndex())
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = MAX_POINTS
        # CACHE-02 修复：大点数档位内存确认。每点 16 字节（时间+值各 8 字节），
        # 80M × 8 通道峰值内存约 10GB（全局上限）。选择超过 1M 时提示用户确认。
        if val > 1_000_000 and val != self.max_points:
            from PySide6.QtWidgets import QMessageBox
            est_megabytes = val * 16 * max(1, len(self._channels)) / (1024 * 1024)
            ret = QMessageBox.question(
                self, tr("scope.limit_warn_title"),
                trf("scope.limit_warn", n=val, mb=int(est_megabytes)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                # 用户取消：恢复到当前实际值
                self.cb_limit.blockSignals(True)
                self._sync_limit_combo(self.max_points)
                self.cb_limit.blockSignals(False)
                return
        self.set_max_points(val)

    def set_max_points(self, val):
        """把每通道 FIFO 容量调整为 val（夹紧到安全区间），先进先出保留最近数据。

        数据上限由 DataHub 统一管理（唯一数据源），本面板只做 UI 同步。
        """
        self.dh.set_max_points(val)
        self._sync_limit_combo(val)
        self._refresh_limit_hint()
        self._mark_dirty()

    def _sync_limit_combo(self, value):
        idx = -1
        for i in range(self.cb_limit.count()):
            if self.cb_limit.itemData(i) == value:
                idx = i
                break
        self.cb_limit.blockSignals(True)
        if idx >= 0:
            self.cb_limit.setCurrentIndex(idx)
        self.cb_limit.blockSignals(False)

    def _refresh_limit_hint(self):
        self.lb_limit_hint.setText(trf("scope.limit_hint", n=_fmt_points(self.max_points)))

    @staticmethod
    def _normalize_unit(unit):
        """把单位字符串规范化为标准电压单位写法（小写/异体字 → 规范大写）。
        数据格式串（如 ch1:%fmv）与手动输入可能产生小写 mv/uv/kv 等，
        统一规范为 mV / µV / nV / kV / MV / GV，保证通道列与各窗口单位一致。
        非电压单位或无法识别的前缀原样返回。"""
        s = (unit or "").strip()
        if not s:
            return "V"
        s = s.replace("μ", "µ").replace("µ", "µ")
        lower = s.lower()
        if lower == "v":
            return "V"
        if not lower.endswith("v"):
            return s
        pre = s[:-1]
        if pre == "":
            return "V"
        if len(pre) == 1:
            c = pre
            if c == "m":
                return "mV"
            if c == "M":
                return "MV"
            if c in ("k", "K"):
                return "kV"
            if c in ("u", "µ"):
                return "µV"
            if c in ("n", "N"):
                return "nV"
            if c in ("g", "G"):
                return "GV"
            if c in ("p", "P"):
                return "pV"
        return s

    @staticmethod
    def _unit_magnitude(unit):
        """把电压单位解析为量纲倍数（电子学单位制）：V=1, mV=1e-3,
        µV/uV=1e-6, nV=1e-9, kV=1e3, MV=1e6, GV=1e9；解析失败返回 0。
        用于多通道单位不一致时选取「量纲最大」的单位（kV > V > mV > µV）。"""
        u = (unit or "").strip()
        if not u:
            return 1.0
        u = u.replace("μ", "u").replace("µ", "u")
        if not u.endswith("V") and not u.endswith("v"):
            return 0.0
        pre = u[:-1]
        if pre == "":
            return 1.0
        m_map = {"G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
                 "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
        return m_map.get(pre, m_map.get(pre.lower(), 0.0))

    def _y_axis_unit(self):
        """按当前「打开的通道集合」决定波形 Y 轴单位：
        - 单通道打开 → 该通道单位；
        - 多通道单位一致 → 该单位；
        - 多通道单位不一致 → 电子学电压量纲最大的通道单位（kV>V>mV>µV>nV）。
        仅统计 enabled 的通道与数学通道；无打开通道时退回 v_unit。"""
        units = []
        for ch, info in self.channels.items():
            if info.get("enabled", True):
                u = str(info.get("unit", "V") or "V").strip()
                if u:
                    units.append(u)
        for key, spec in self.maths.items():
            # 数学通道需 enabled（数学面板开启）且 visible（波形显示）才参与 Y 轴单位
            if spec.get("enabled", False) and spec.get("visible", True):
                u = str(spec.get("unit", "V") or "V").strip()
                if u:
                    units.append(u)
        if not units:
            return getattr(self, "v_unit", "V") or "V"
        first = units[0]
        if all(u == first for u in units):
            return first
        best, best_mag = first, self._unit_magnitude(first)
        for u in units[1:]:
            m = self._unit_magnitude(u)
            if m > best_mag:
                best, best_mag = u, m
        return best

    def _apply_axis_policy(self):
        """坐标刻度/轴标题移除统一策略。
        pyqtgraph 的 setLabel()/setTicks() 内部会调用 showAxis(True) 把隐藏的轴
        恢复显示——这就是主题切换/重绘后坐标刻度与轴又回来的根因。
        因此在任何 setLabel/setTicks 之后都必须重新：清空刻度 + 关闭网格 + 隐藏轴。"""
        try:
            self.plot.setLabel("left", "")
            self.plot.setLabel("bottom", "")
            self.plot.showGrid(x=False, y=False)
            pi = self.plot.getPlotItem()
            pi.hideAxis('left')
            pi.hideAxis('bottom')
            self.plot.getAxis('left').setTicks([])
            self.plot.getAxis('bottom').setTicks([])
        except Exception:  # noqa: BLE001
            pass

    def _apply_left_axis_label(self):
        # 按实际示波器移除 Y 轴单位标题
        self._apply_axis_policy()

    def _on_unit_changed(self, text):
        self.v_unit = (text or "").strip()
        # 构建期（plot/meas_labels 尚未就绪）仅记录单位，避免信号早发导致
        # 未初始化属性访问；正式更新由 retranslate/后续编辑触发
        if not hasattr(self, "plot"):
            return
        self._apply_left_axis_label()
        self._mark_dirty()
        self._update_measures()

    # ------------------------------------------------------------- 测量
    def _meas_data(self, ch):
        # 使用耦合数据（DC原样 / AC去直流），测量值反映真实物理量纲
        t, y = self._get_coupled_arrays(ch)
        if self._last_window is not None and len(t):
            x0, x1 = self._last_window
            idx_start = int(np.searchsorted(t, x0, side="left"))
            idx_end = int(np.searchsorted(t, x1, side="right"))
            if idx_end > idx_start:
                t = t[idx_start:idx_end]
                y = y[idx_start:idx_end]
        # 测量/触发范围同步用的窗口若过大，先大步抽取，避免超大数组内存抖动
        if t.size > _DRAW_RAW_MAX:
            step = int(math.ceil(t.size / _DRAW_RAW_MAX))
            t = t[::step]
            y = y[::step]
        return t, y

    def _sync_trig_range(self):
        """触发旋钮极值实时同步为波形图 Y 轴可视范围（±极值）：
        从 self.plot.viewRange()[1] 读取当前 Y 轴上下界，作为触发电平旋钮
        的调节范围，用户缩放/滚动/Auto/重置屏幕等导致 Y 轴范围变化时实时跟随。
        波形图未绘图或无有效范围时回退 ±10 格（覆盖屏幕外 2 倍）。
        文本框保留更宽的输入范围，旋钮使用紧凑范围便于精细调节。
        仅在范围显著变化时更新，避免频繁重置导致输入中断。"""
        src = self._trig_ch_key()
        spec = self._spec_of(src)
        if spec is None:
            return
        # 触发旋钮显示值 = Y 轴单位，与 _disp_to_phys 换算一致
        # 波形图 Y 轴可视极值（实时，Y轴单位）
        lo = hi = None
        try:
            view_range = self.plot.viewRange()
            y0 = float(view_range[1][0])
            y1 = float(view_range[1][1])
            if math.isfinite(y0) and math.isfinite(y1) and y1 > y0:
                lo, hi = y0, y1
        except Exception:  # noqa: BLE001
            pass
        if lo is None:
            # 回退：Y 轴固定 ±5×垂直灵敏度（标准示波器），换算到 Y 轴单位
            half = 5.0 * self._main_v_div() / self._y_mag()
            if half < 0.001:
                half = 0.001
            lo = -half
            hi = half
        # 范围过小保护：至少 ±0.05 的调节区间
        if hi - lo < 1e-4:
            c = (hi + lo) / 2.0
            lo, hi = c - 0.05, c + 0.05
        # 仅当范围变化超过 5% 时才更新，避免频繁重置导致输入中断
        cur_low = self.knob_trig.min_value
        cur_high = self.knob_trig.max_value
        if (abs(lo - cur_low) > abs(cur_low) * 0.05 + 1e-6
                or abs(hi - cur_high) > abs(cur_high) * 0.05 + 1e-6):
            self.knob_trig.setRange(lo, hi)
        # 文本框使用更宽范围（±1000），允许用户自由输入超出旋钮范围的值
        if (abs(self.sp_trig_level.minimum() - (-1000.0)) > 1e-6
                or abs(self.sp_trig_level.maximum() - 1000.0) > 1e-6):
            self.sp_trig_level.setRange(-1000.0, 1000.0)

    def _update_trig_marker(self):
        """更新触发电平参考线：常规/单次触发模式下显示于当前电平处（与 Y 轴一致）。
        BUG-FIX：加 _trig_line_updating 递归锁，避免与 _on_trig_line_dragged 信号循环。"""
        if not hasattr(self, "trig_line"):
            return
        if getattr(self, "_trig_line_updating", False):
            return
        self._trig_line_updating = True
        try:
            self.trig_line.setValue(self.sp_trig_level.value())
            # 仅在「自动」触发模式下不显示触发电平参考线（避免
            # 自动模式下电平参考线干扰观察）；常规/单次触发模式下仍显示虚线，
            # 其他触发相关功能完全不变。触发源通道无效时一律不显示。
            show = (self._trig_ch_key() != -1) and (self.cb_trig_mode.currentIndex() != 0)
            self.trig_line.setVisible(show)
        finally:
            self._trig_line_updating = False

    def _update_measures(self):
        """刷新自动测量面板（全部基于耦合数据，经 _meas_data 读取）。

        专业示波器标准：垂直增益（V/div）和偏移（Position）只影响屏幕显示，
        不影响测量结果。Vpp/Vmax/Vmin/均值/RMS 等全部反映信号真实物理量纲
        （DC 原样 / AC 已去直流）。"""
        ch = self._meas_ch_key()
        spec = self._spec_of(ch)
        if spec is None:
            for k in self.meas_labels:
                self.meas_labels[k].setText("--")
            return
        t, y = self._meas_data(ch)
        measure_data = dict.fromkeys(self.meas_labels, "--")
        # 自动测量单位唯一来源 = 选中测量通道的单位列（含数学通道默认 V）
        unit = spec.get("unit", "V") or "V"
        # 同步测量面板单位标签（ed_unit 只读）：无论单位由格式串解析、下拉选择
        # 还是手动输入修改，测量刷新时自动保持一致，杜绝通道列与测量面板单位错位
        if hasattr(self, "ed_unit") and self.ed_unit.text() != unit:
            self.ed_unit.blockSignals(True)
            self.ed_unit.setText(unit)
            self.ed_unit.blockSignals(False)
        if y.size >= 2:
            # 数据已经是耦合后的（_meas_data返回_coupled_arrays），直接使用
            vpp = float(np.ptp(y))
            vmax = float(np.max(y))
            vmin = float(np.min(y))
            measure_data["vpp"] = _amp(vpp, unit)
            measure_data["vmax"] = _amp(vmax, unit)
            measure_data["vmin"] = _amp(vmin, unit)
            measure_data["mean"] = _amp(float(np.mean(y)), unit)
            measure_data["rms"] = _amp(float(np.sqrt(np.mean(y ** 2))), unit)
            measure_data["std"] = _amp(float(np.std(y)), unit)
            # 高/低电平与幅值：直方图众数法
            high, low = self._hist_levels(y)
            if high is not None and low is not None:
                measure_data["high"] = _amp(high, unit)
                measure_data["low"] = _amp(low, unit)
                amplitude = high - low
                measure_data["amp"] = _amp(amplitude, unit)
                if amplitude > 1e-12:
                    measure_data["over"] = f"{(vmax - high) / amplitude * 100:.3g}%"
                    measure_data["pre"] = f"{(low - vmin) / amplitude * 100:.3g}%"
            period, frequency = self._estimate_period(y, t)
            if frequency is not None:
                measure_data["freq"] = _fmt_freq(frequency)
                measure_data["period"] = _fmt_time(period)
            # 上升/下降时间、占空比、正脉宽（基于物理值）
            edges = self._measure_edges(t, y)
            if edges is not None:
                if edges["rise"] is not None:
                    measure_data["rise"] = _fmt_time(edges["rise"])
                if edges["fall"] is not None:
                    measure_data["fall"] = _fmt_time(edges["fall"])
                if edges["duty"] is not None:
                    measure_data["duty"] = f"{edges['duty'] * 100:.3g}%"
                if edges["width"] is not None:
                    measure_data["width"] = _fmt_time(edges["width"])
                if edges["neg_width"] is not None:
                    measure_data["neg_width"] = _fmt_time(edges["neg_width"])
            # 面积（物理值·秒）、斜率（物理值/秒）
            ts, y_area = _dedupe_xy(t, y)
            if ts.size >= 2:
                area = 0.5 * float(np.sum((y_area[1:] + y_area[:-1]) * np.diff(ts)))
                measure_data["area"] = f"{area:.6g} {unit}·s"
                dydt = np.diff(y_area) / np.diff(ts)
                if dydt.size:
                    measure_data["slew_rise"] = f"{float(np.max(dydt)):.6g} {unit}/s"
                    measure_data["slew_fall"] = f"{float(np.min(dydt)):.6g} {unit}/s"
            # 周期 RMS / 周期均值
            if frequency is not None and period > 0 and ts.size >= 4:
                idx_start = int(np.searchsorted(ts, float(ts[-1]) - period, side="left"))
                if ts.size - idx_start >= 2:
                    seg = y_area[idx_start:]
                    measure_data["cyc_rms"] = _amp(float(np.sqrt(np.mean(seg ** 2))), unit)
                    measure_data["cyc_mean"] = _amp(float(np.mean(seg)), unit)
            # 触发电平：显示电平转换为物理电平（显示值含单位换算系数）
            # 触发显示电平（Y轴单位）→ 物理电平（通道单位）统一反解
            display_level = self.sp_trig_level.value()
            phys_level = self._disp_to_phys(ch, display_level)
            measure_data["trig"] = _amp(phys_level, unit)
        else:
            # 无数据时仍显示触发电平（物理值）
            # 触发显示电平（Y轴单位）→ 物理电平（通道单位）统一反解
            display_level = self.sp_trig_level.value()
            phys_level = self._disp_to_phys(ch, display_level)
            measure_data["trig"] = _amp(phys_level, unit)
        for k, lab in self.meas_labels.items():
            lab.setText(measure_data.get(k, "--"))

    @staticmethod
    def _hist_levels(y, bins=64):
        """用直方图众数估计高/低电平（标准双电平幅度测量）。

        以均值为界把直方图分成上下两部分，各自取众数所在 bin 的中心作为高/低
        电平；信号退化（如近似平直）时回退为最大/最小，且恒保证 high >= low。
        """
        y = np.asarray(y, dtype=float)
        y = y[np.isfinite(y)]
        if y.size < 8:
            return None, None
        lo = float(np.min(y))
        hi = float(np.max(y))
        if hi - lo <= 1e-12:
            return hi, lo
        bins = int(max(8, min(bins, y.size)))
        counts, edges = np.histogram(y, bins=bins, range=(lo, hi))
        centers = (edges[:-1] + edges[1:]) * 0.5
        mean = float(np.mean(y))
        upper = centers >= mean
        lower = centers < mean
        if bool(upper.any()) and bool(lower.any()):
            high = float(centers[int(np.argmax(counts * upper))])
            low = float(centers[int(np.argmax(counts * lower))])
        else:
            high, low = hi, lo
        if high <= low:
            high, low = low, high
        return high, low

    @staticmethod
    def _estimate_period(y, t):
        y = np.asarray(y, dtype=float)
        if y.size < 4:
            return None, None
        t = np.asarray(t, dtype=float)
        t, y = _dedupe_xy(t, y)
        if y.size < 4:
            return None, None
        mean = np.mean(y)
        rising = (y[:-1] <= mean) & (y[1:] > mean)
        idx = np.flatnonzero(rising)
        if idx.size < 2:
            return None, None
        # 向量化过零时刻插值（避免逐元素 Python 循环，高频/方波下显著提速）
        t0 = t[idx]
        t1 = t[idx + 1]
        y0 = y[idx]
        y1 = y[idx + 1]
        positions = t0 + (mean - y0) * (t1 - t0) / (y1 - y0 + 1e-12)
        periods = np.diff(positions)
        periods = periods[periods > 0]
        if periods.size == 0:
            return None, None
        period = float(np.median(periods))
        if period <= 0:
            return None, None
        return period, 1.0 / period

    @staticmethod
    def _measure_edges(t, y):
        """在显示量纲信号上计算上升/下降时间、占空比（50%）与正脉宽。

        BUG-FIX：上升/下降时间改用高/低电平（直方图众数法）的 10%-90%，
        而非信号极值的 10%-90%，避免过冲/噪声导致边沿时间测量偏大。
        全部基于线性插值的过阈时刻。占空比与正脉宽通过「上升沿→紧随其后的
        下降沿」成对计算，并对周期做夹紧。
        """
        t = np.asarray(t, dtype=float)
        y = np.asarray(y, dtype=float)
        t, y = _dedupe_xy(t, y)
        if y.size < 4:
            return None
        lo = float(np.min(y))
        hi = float(np.max(y))
        out = {"rise": None, "fall": None, "duty": None, "width": None,
               "neg_width": None}
        # 用直方图众数法估计高/低电平（标准双电平测量）
        high, low = WaveformPanel._hist_levels(y)
        if high is None or low is None or high - low <= 1e-12:
            high, low = hi, lo
        amp = high - low
        # 上升/下降时间（高/低电平的 10%–90%，而非极值）
        l10 = low + 0.1 * amp
        l90 = low + 0.9 * amp
        if amp > 1e-12:
            t10r = _cross_times(t, y, l10, rising=True)
            t90r = _cross_times(t, y, l90, rising=True)
            if t10r.size and t90r.size:
                target = t90r[-1]
                smaller = t10r[t10r < target]
                if smaller.size:
                    out["rise"] = target - smaller[-1]
            t90f = _cross_times(t, y, l90, rising=False)
            t10f = _cross_times(t, y, l10, rising=False)
            if t90f.size and t10f.size:
                target = t10f[-1]
                smaller = t90f[t90f < target]
                if smaller.size:
                    out["fall"] = target - smaller[-1]
        # 正脉宽 / 占空比：中值电平（高/低的50%）上升沿与紧随其后的下降沿成对
        mid = (high + low) / 2.0
        rise = _cross_times(t, y, mid, rising=True)
        fall = _cross_times(t, y, mid, rising=False)
        widths = []
        j = 0
        for r in rise:
            while j < len(fall) and fall[j] <= r:
                j += 1
            if j >= len(fall):
                break
            w = float(fall[j] - r)
            if w > 0:
                widths.append(w)
        # 周期：相邻上升沿间隔（中位数，抗边界毛刺）
        periods = [float(rise[i + 1] - rise[i]) for i in range(len(rise) - 1)
                   if rise[i + 1] > rise[i]]
        if widths:
            width = float(np.median(widths))
            if periods:
                period = float(np.median(periods))
                # 单个正脉宽不应超过周期（边界配对误差的保险夹紧）
                width = min(width, period)
                if period > 0:
                    out["duty"] = min(1.0, max(0.0, width / period))
                    out["neg_width"] = max(0.0, period - width)
            out["width"] = width
        return out

    # ------------------------------------------------------------- 光标
    def _on_mouse_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.cursor.handle_clicked(event.scenePos()):
            event.accept()

    def _on_mouse_moved(self, event):
        if self.cursor.mode == MODE_OFF:
            return
        pos = event[0]
        shape = self.cursor.handle_moved(pos)
        try:
            viewport = self.plot.viewport()
            if shape is not None:
                viewport.setCursor(shape)
            else:
                viewport.unsetCursor()
        except Exception:  # noqa: BLE001
            pass

    def eventFilter(self, obj, event):
        t = event.type()
        # 光标拖拽必须在鼠标按下时启动，原代码仅在 sigMouseClicked（释放时）
        # 调用 handle_clicked，导致 _drag 设置太晚、拖拽完全不工作。
        if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self.cursor.mode not in (MODE_OFF, MODE_AUTO) and obj is self.plot.viewport():
                try:
                    scene_pos = self.plot.mapToScene(event.position().toPoint())
                    if self.cursor.handle_clicked(scene_pos):
                        event.accept()
                        return True
                except Exception:  # noqa: BLE001
                    pass
        if t == QEvent.Type.MouseButtonRelease:
            if self.cursor.mode != MODE_OFF:
                self.cursor.handle_released()
                self._update_cursor_readout()
        elif t == QEvent.Type.KeyPress:
            from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QAbstractSpinBox
            focus_widget = QApplication.focusWidget()
            is_edit = focus_widget is not None and isinstance(
                focus_widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox))
            if isinstance(focus_widget, QComboBox) and focus_widget.isEditable():
                is_edit = True
            if self.cursor.mode != MODE_OFF and not is_edit:
                if self.cursor.handle_key_press(event):
                    event.accept()
                    return True
        elif t == QEvent.Type.Wheel and obj is self.plot.viewport():
            if (self.cursor.mode not in (MODE_OFF, MODE_AUTO)
                    and self.cursor.handle_wheel(event.angleDelta().y())):
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def _update_cursor_readout(self):
        if self.cursor.mode == MODE_OFF:
            self.lb_cursor.setText("")
        else:
            self.lb_cursor.setText(self.cursor.readout_summary())

    # ------------------------------------------------------------- 控制回调
    def _on_timebase(self):
        self.knob_tb.blockSignals(True)
        self.knob_tb.setValue(float(self.cb_timebase.currentIndex()))
        self.knob_tb.blockSignals(False)
        self._update_hpos_range()
        self._mark_dirty()

    def _on_knob_timebase(self, v):
        idx = int(round(v))
        if idx != self.cb_timebase.currentIndex():
            self.cb_timebase.blockSignals(True)
            self.cb_timebase.setCurrentIndex(idx)
            self.cb_timebase.blockSignals(False)
        self._update_hpos_range()
        self._mark_dirty()

    def _on_trig_spin(self, v):
        self.knob_trig.blockSignals(True)
        self.knob_trig.setValue(v)
        self.knob_trig.blockSignals(False)
        self._update_trig_marker()
        self._mark_dirty()

    def _on_trig_line_dragged(self, line):
        """TRIG-03 修复：鼠标拖拽触发线时，同步到触发电平文本框和旋钮。
        BUG-FIX：加 _trig_line_updating 递归锁，避免信号循环。"""
        if getattr(self, "_trig_line_updating", False):
            return
        v = float(line.value())
        if abs(v - self.sp_trig_level.value()) > 1e-9:
            self._trig_line_updating = True
            try:
                self.sp_trig_level.blockSignals(True)
                self.sp_trig_level.setValue(v)
                self.sp_trig_level.blockSignals(False)
                self.knob_trig.blockSignals(True)
                self.knob_trig.setValue(v)
                self.knob_trig.blockSignals(False)
                self._mark_dirty()
            finally:
                self._trig_line_updating = False

    def _on_knob_trig_level(self, v):
        if abs(v - self.sp_trig_level.value()) > 1e-9:
            self.sp_trig_level.blockSignals(True)
            self.sp_trig_level.setValue(v)
            self.sp_trig_level.blockSignals(False)
        self._update_trig_marker()
        self._mark_dirty()

    # ------------------------------------------------------------- 垂直灵敏度/垂直位置
    def _set_v_div(self, ch, v_div):
        """设置通道垂直灵敏度（V/div），同步衍生 offset 并刷新显示/触发范围。
        用户手动调整后停用自动垂直灵敏度。支持数学通道 key(str)。"""
        if v_div is None or v_div <= 0:
            return
        spec = self._spec_of(ch)
        if spec is None:
            return
        self._vdiv_auto = False
        spec["v_div"] = float(v_div)
        row = self._channel_rows.get(ch)
        if row is not None:
            row.set_scale(v_div)
        self._update_y_range()
        if ch == self._trig_ch_key():
            self._sync_trig_range()
        # 拖动通道标签时立即更新标签位置（不等待刷新循环，确保拖动流畅）
        ch_label = self._ch_labels.get(ch)
        if ch_label is not None and ch_label.isVisible():
            try:
                y_ref = float(self._display_y(ch, 0.0))
                ch_label.setPos(ch_label.pos().x(), y_ref)
            except Exception:  # noqa: BLE001
                pass
        self._mark_dirty()

    def _set_v_pos(self, ch, v_pos):
        """设置通道垂直位置（div），同步衍生 offset 并刷新显示。AC 耦合时忽略。
        用户手动调整后停用自动垂直灵敏度（避免自动调档干扰微调）。"""
        try:
            v_pos = float(v_pos)
        except (TypeError, ValueError):
            return
        spec = self._spec_of(ch)
        if spec is None:
            return
        self._vdiv_auto = False
        is_ac = (not self._is_math(ch)) and spec.get("coupling") == "ac"
        if is_ac:
            v_pos = 0.0
        # 限制在 ±5 div
        v_pos = max(-V_POS_RANGE, min(V_POS_RANGE, v_pos))
        spec["v_pos"] = v_pos
        row = self._channel_rows.get(ch)
        if row is not None:
            row.set_offset(v_pos)
        if ch == self._trig_ch_key():
            self._sync_trig_range()
        # 拖动通道标签时立即更新标签位置（不等待刷新循环，确保拖动流畅）
        ch_label = self._ch_labels.get(ch)
        if ch_label is not None and ch_label.isVisible():
            try:
                y_ref = float(self._display_y(ch, 0.0))
                ch_label.setPos(ch_label.pos().x(), y_ref)
            except Exception:  # noqa: BLE001
                pass
        self._mark_dirty()

    def _on_scale_combo(self, ch, cb):
        """垂直灵敏度下拉改变：解析 '50 mV/div' 或纯数字，更新通道 V/div。"""
        v = _parse_vdiv_text(cb.currentText())
        if v is None or v <= 0:
            return
        self._set_v_div(ch, v)

    def _on_offset_combo(self, ch, cb):
        """垂直位置下拉改变：解析 '+2.00 div' 或纯数字，更新通道位置(div)。"""
        try:
            v = float(cb.currentText().replace(" div", "").replace("div", ""))
        except (TypeError, ValueError):
            return
        self._set_v_pos(ch, v)

    def _on_scale_spin(self, ch, v):
        self._set_v_div(ch, v)

    def _on_offset_spin(self, ch, v):
        self._set_v_pos(ch, v)

    # ------------------------------------------------------------- Y 轴范围（标准示波器）
    def _main_ch_key(self):
        """主控通道：触发源 > 第一个启用通道 > None。"""
        src = self._trig_ch_key()
        if src != -1 and self._spec_of(src) is not None:
            return src
        for ch, info in self.channels.items():
            if info.get("enabled", True):
                return ch
        return None

    def _main_v_div(self):
        """主控通道垂直灵敏度（V/div）。"""
        k = self._main_ch_key()
        if k is None:
            return 1.0
        spec = self._spec_of(k)
        if spec is None:
            return 1.0
        return max(float(spec.get("v_div", 1.0) or 1.0), 1e-9)

    def _update_reference_markers(self):
        """示波器专业参考元素同步（每次重绘后调用）：
        - 通道 0V 垂直参考点（GroundRefItem）：位置 = 该通道 0V 显示值，
          垂直位置变化时随之上下移动；
        - 通道标签（Channel Identifier）：叠加在 0V 参考点短横线上方，带通道颜色；
        - 水平时间参考点（t=0 / 触发点）：屏幕顶部向下箭头，位于窗口水平中心；
        - 中心虚线：垂直中心线在 t=0，水平中心线在 0V（格线中心参考）。
        数据窗口/触发/时基/垂直位置变化时全部跟随，不影响任何数据与测量。"""
        try:
            pi = self.plot.getPlotItem()
            view_box = pi.vb if pi is not None else None
            if view_box is None:
                return
            xr, y_range = view_box.viewRange()
            x0, x1 = float(xr[0]), float(xr[1])
            y0, y1 = float(y_range[0]), float(y_range[1])
            span_x = (x1 - x0) or 1.0
            span_y = (y1 - y0) or 1.0
            # 栅格 = 中心十字实线 + 大格交叉点(11×11) + 小格点(每大格9个=10小格)
            # 移除密集点线(DotLine)，改用离散散点，符合标准示波器栅格规范。
            if getattr(self, "_grid_dots", None) is not None:
                _x_lines = [x0 + i * span_x / 10.0 for i in range(11)]
                _y_lines = [y0 + j * span_y / 10.0 for j in range(11)]
                _cx = _x_lines[5]
                _cy = _y_lines[5]
                _nan = float("nan")
                try:
                    # 中心十字实线（唯一实线，最上层）
                    self._grid_cross.setData(
                        [_cx, _cx, _nan, _x_lines[0], _x_lines[-1]],
                        [_y_lines[0], _y_lines[-1], _nan, _cy, _cy])
                    # 大格交叉点（11×11 = 10大格，size=5，较亮）
                    _px_major = np.repeat(np.asarray(_x_lines, dtype=float), 11)
                    _py_major = np.tile(np.asarray(_y_lines, dtype=float), 11)
                    self._grid_dots.setData(x=_px_major, y=_py_major)
                    # 小格点只在大格经纬线上（11条水平线 + 11条垂直线），
                    # 每大格之间9个小点 = 10小格。不要大格内部的点（不在大格线上的点）。
                    # 水平大格线上的小格点：y=大格y位置，x=小格x位置
                    # 垂直大格线上的小格点：x=大格x位置，y=小格y位置
                    # 大格交叉点已由 _grid_dots（大点）显示，此处不重复。
                    if getattr(self, "_grid_minor_dots", None) is not None:
                        _minor_x = []
                        _minor_y = []
                        # 水平大格线上的小格点（11条水平线 × 每线90个小格点）
                        for j in range(11):
                            y_line = _y_lines[j]
                            for i in range(10):
                                minor_dx = (_x_lines[i+1] - _x_lines[i]) / 10.0
                                for k in range(1, 10):
                                    _minor_x.append(_x_lines[i] + k * minor_dx)
                                    _minor_y.append(y_line)
                        # 垂直大格线上的小格点（11条垂直线 × 每线90个小格点）
                        for i in range(11):
                            x_line = _x_lines[i]
                            for j in range(10):
                                minor_dy = (_y_lines[j+1] - _y_lines[j]) / 10.0
                                for k in range(1, 10):
                                    _minor_x.append(x_line)
                                    _minor_y.append(_y_lines[j] + k * minor_dy)
                        self._grid_minor_dots.setData(
                            x=np.asarray(_minor_x, dtype=float),
                            y=np.asarray(_minor_y, dtype=float))
                except Exception:  # noqa: BLE001
                    pass
            # X 轴为相对屏幕中心坐标（格线固定）→ 参考元素也用相对坐标
            # ch1..chN 标签移到波形显示区域最左侧（x = 数据窗口左缘，贴 Y 轴）
            x_left = x0
            # t=0 触发点：水平位置决定其相对屏幕中心的位置（水平位置=0 时位于正中央）
            t0x = float(getattr(self, "h_pos", 0.0))
            # T 标记上移到波形显示区域的最顶部（数据窗口顶部 = 可视区顶）
            y_top = y1
            _t0_ref = getattr(self, "_t0_ref", None)
            if _t0_ref is not None:
                try:
                    _t0_ref.setPos(t0x, y_top)
                    _t0_ref.setVisible(True)
                except Exception:  # noqa: BLE001
                    pass
            # T 标记改为「⬇」箭头后不再需要额外竖线 → _t0_line 隐藏；
            # 中心虚线十字一并隐藏（背景不能有除波形之外的任何线条）
            _t0_line = getattr(self, "_t0_line", None)
            if _t0_line is not None:
                try:
                    _t0_line.setVisible(False)
                except Exception:  # noqa: BLE001
                    pass
            if self._center_vline is not None:
                self._center_vline.setVisible(False)
            if self._center_hline is not None:
                self._center_hline.setVisible(False)
            # 各通道 0V 参考点（左侧带箭头短横线，位置 = 该通道 0V，随垂直位置移动）
            # 通道标签固定屏幕左侧按通道编号纵向排列（真实示波器
            # Channel Identifier 风格：C1 顶部、C2 下方，带通道颜色，永不重叠）；
            # 0V 参考线（GroundRef）仍在 0V 位置（垂直位置相同时多条 0V 线重叠为
            # 真实示波器正常行为，但标签纵向错开、不再互相覆盖）。
            ch_idx = 0
            for ch, item in list(self._ground_refs.items()):
                spec = self._spec_of(ch)
                if spec is None or not spec.get("enabled"):
                    item.setVisible(False)
                    ch_label = self._ch_labels.get(ch)
                    if ch_label is not None:
                        ch_label.setVisible(False)
                    continue
                try:
                    y_ref = float(self._display_y(ch, 0.0))
                except Exception:  # noqa: BLE001
                    y_ref = 0.0
                # 0V 处不再绘制长参考横线（GroundRef 隐藏），
                # 只保留一个「➡ch1」小箭头通道标签（箭头很小）。
                # ➡ch1..chN 的「➡」左侧与波形显示区域左侧完全重合
                # （x = 数据窗口左缘 x0，不加任何偏移）；无论是显示一个通道还是
                # 显示全部通道，全部贴最左（0V 相同时标签上下重合属正常示波器表现）
                item.setVisible(False)
                ch_label = self._ch_labels.get(ch)
                if ch_label is not None:
                    ch_label.setPos(x_left, y_ref)
                    ch_label.setVisible(True)
                    ch_idx += 1
        except Exception:  # noqa: BLE001
            pass

    def _update_y_range(self):
        """Y 轴范围 = 中心为垂直位置 0，向上/向下各 5 格 → ±5×垂直灵敏度。
        v_div 恒为 V/div；Y 轴按 Y 轴单位显示：±5×v_div / y_gain（Y轴单位）。
        标准示波器：正极值 = 灵敏度×5，负极值 = −灵敏度×5。"""
        v_div = self._main_v_div()
        y_gain = self._y_mag()
        half = V_POS_RANGE * v_div / y_gain if y_gain else 5.0 * v_div
        self.plot.setYRange(-half, half, padding=0)
        self.plot.disableAutoRange(axis=1)
        # 软件初始状态及全程移除坐标刻度显示（Y 轴刻度清空 +
        # 轴已隐藏双保险，任何环境下波形区都不显示坐标刻度数值与刻度线）
        try:
            axis = self.plot.getAxis("left")
            axis.setTicks([])
        except Exception:  # noqa: BLE001
            pass

    def _auto_vdiv_apply(self):
        """自动垂直灵敏度（默认开启，修复固定 Y 轴后波形不可见）。
        主通道波形与屏幕严重不匹配（出屏 >9.5 格 或 不可见 <0.4 格）时，
        按信号 Vpp 自动 1-2-5 向上取整选档，使波形约占 7 格（10格×70%）屏高。
        带限频（0.5s）与档位防抖，避免实时数据抖动导致 Y 轴跳动；
        用户手动调 V/div / Position 或按 Auto 后停用自动。"""
        if not getattr(self, "_vdiv_auto", False):
            return
        k = self._main_ch_key()
        if k is None:
            return
        spec = self._spec_of(k)
        if spec is None:
            return
        try:
            _t, y = self._get_coupled_arrays(k)
        except Exception:  # noqa: BLE001
            return
        if y is None or len(y) < 8:
            return
        y = np.asarray(y, dtype=float)
        vpp = float(np.ptp(y))
        if not np.isfinite(vpp) or vpp <= 0:
            return
        # v_div 恒为 V/div；vpp 换算到伏特后再判定占屏比例
        ch_gain = self._ch_mag(k)
        vpp_voltage = vpp * ch_gain
        mid_voltage = (float(np.max(y)) + float(np.min(y))) * 0.5 * ch_gain
        current_vdiv = max(float(spec.get("v_div", 1.0) or 1.0), 1e-9)
        # 当前屏幕可视高度 = 10 格 × 灵敏度(V)；波形占屏比例（含 DC 偏置影响）
        span_need = max(vpp_voltage, 2.0 * abs(mid_voltage))
        ratio = span_need / (10.0 * current_vdiv) if current_vdiv > 0 else 0.0
        if AUTO_RATIO_MIN <= ratio <= AUTO_RATIO_MAX:
            return   # 波形占屏 0.4~9.5 格：无需调整（防抖）
        needed_div = max(vpp_voltage / 7.0, abs(mid_voltage) / V_POS_RANGE)
        v_div = self._round_to_125(needed_div)
        v_div = max(V_DIV_STEPS[0], min(V_DIV_STEPS[-1], v_div))
        if abs(v_div - current_vdiv) / current_vdiv < AUTO_VDIV_TOL:
            return
        now = time.monotonic()
        if now - getattr(self, "_last_vdiv_auto_t", 0.0) < AUTO_DEBOUNCE_S:
            return
        self._last_vdiv_auto_t = now
        # 直接写档位（不经 _set_v_div，避免停用自动标志）
        spec["v_div"] = float(v_div)
        row = self._channel_rows.get(k)
        if row is not None:
            row.set_scale(v_div)
        self._update_y_range()

    def _on_channel_unit_changed(self, ch, text):
        """单位列修改：更新通道单位，同步所有相关显示和计算。
        支持数学通道 key(str)。
        数学通道默认单位自动跟随第一个出现的通道(CH1)——当 CH1 单位被修改时，
        所有仍未手动改过单位(unit_auto=True)的数学通道同步更新单位与 UI；用户手动
        修改某数学通道单位后该通道置 unit_auto=False，不再跟随。"""
        unit = self._normalize_unit(text.strip() or "V")
        spec = self._spec_of(ch)
        if spec is not None:
            spec["unit"] = unit
            # 手动修改过单位的通道取消自动跟随（数学通道 unit_auto 生效）
            if isinstance(ch, str):
                spec["unit_auto"] = False
            # 物理通道单位改变 → 表达式中**第一个引用该通道**的
            # unit_auto 数学通道跟随其单位（如 M1=ch2+1 跟随 ch2，M1=ch3+ch1 跟随 ch3）
            if isinstance(ch, int):
                synced = False
                for mkey, mspec in self.maths.items():
                    if not mspec.get("unit_auto", False) or not mspec.get("expr"):
                        continue
                    if first_ch_in_expr(mspec["expr"]) == ch:
                        mspec["unit"] = unit
                        row = self._channel_rows.get(mkey)
                        if row is not None:
                            row.set_unit(unit)
                        synced = True
                if synced:
                    self._apply_left_axis_label()
                    self._mark_dirty()
                    self._update_measures()
            # 同步测量面板单位（如果测量源是该通道）
            if self._meas_ch_key() == ch:
                self.v_unit = unit
                if hasattr(self, "ed_unit"):
                    self.ed_unit.blockSignals(True)
                    self.ed_unit.setText(unit)
                    self.ed_unit.blockSignals(False)
                self._apply_left_axis_label()
                self._update_measures()
            # 同步光标测量单位（如果光标源是该通道）
            # 注意：光标管理器实例属性名是 self.cursor（cursor 是 QWidget 内建方法，
            # 不能用 hasattr 判断——QWidget.cursor() 恒存在，会遮蔽 CursorManager）。
            # 修复：原判断 getattr(self,"curs",None) 恒为 None 导致单位变化时
            # 光标读数从不刷新；实例化时必已创建 self.cursor，直接判断源即可。
            if self.cursor.source == ch:
                self.cursor._update_readout()
            # Y 轴单位随打开的通道集合变化而更新（无论该通道是否为测量源）
            self._apply_left_axis_label()
            self._mark_dirty()

    def _on_knob_hpos(self, v):
        self.h_pos = float(v)
        self._mark_dirty()

    def _on_meas_ch_changed(self):
        # 测量源改变时，同步单位为该通道的单位（单位唯一来源是通道单位列）
        ch = self._meas_ch_key()
        spec = self._spec_of(ch)
        if spec is not None:
            unit = spec.get("unit", "V")
            self.v_unit = unit
            if hasattr(self, "ed_unit"):
                self.ed_unit.blockSignals(True)
                self.ed_unit.setText(unit)
                self.ed_unit.blockSignals(False)
            self._apply_left_axis_label()
        self._update_measures()
        self._mark_dirty()

    def _on_trig_src_changed(self):
        """触发源切换：若触发已使能（常规/单次），触发电平跟随新源波形中心。"""
        if self.mode in ("normal", "single"):
            self._set_trig_level_center()
        self._mark_dirty()

    def _on_trig_mode(self, index):
        # BUG-FIX：idx 可能为 -1（clear 后），越界会取到 "single"，需夹紧
        if index < 0 or index > 2:
            return
        new_mode = ["auto", "normal", "single"][index]
        if new_mode == "single":
            self.mode = "single"
            self._arm_single()
        else:
            resume = (self.mode == "single" and self.single_done)
            self.mode = new_mode
            self.single_armed = False
            self.single_done = False
            self._trig_arm_t = None
            self._last_stable_trig = None  # 切换模式时重置触发防抖基准
            self._auto_no_trig_count = 0   # 重置Auto无触发计数
            if resume:
                self.running = True
                if not self.btn_run.isChecked():
                    self.btn_run.setChecked(True)
                self._update_run_btn_text()
                self.lb_status.setText(trf("scope.status_running", n=self._sample_count()))
        # TRIG-CENTER：常规/单次触发模式使能时，触发电平默认设为触发源通道波形中心
        if new_mode != "auto":
            self._set_trig_level_center()
        self._update_trig_marker()
        self._mark_dirty()

    def _arm_single(self):
        self.single_armed = True
        self.single_done = False
        self.running = True
        self._trig_arm_t = self._last_rel_time()
        self.btn_run.setChecked(True)
        self._update_run_btn_text()
        self.lb_status.setText(tr("scope.status_single_wait"))
        self._mark_dirty()

    def _last_rel_time(self):
        last = None
        for ch in self.channels:
            ring_buffer = self._t.get(ch)
            if ring_buffer is not None and ring_buffer.count:
                v = ring_buffer.last()
                if last is None or v > last:
                    last = v
        return last

    def _sample_count(self):
        b = self._t.get(0)
        return len(b) if b is not None else 0

    def _on_run(self, checked):
        self.running = checked
        if checked and self.mode == "single" and self.single_done:
            self._arm_single()
        else:
            if checked:
                self.lb_status.setText(trf("scope.status_running", n=self._sample_count()))
            else:
                self.lb_status.setText(tr("scope.status_paused"))
        self._update_run_btn_text()
        self._mark_dirty()

    def _on_single(self):
        self.mode = "single"
        self._arm_single()
        if self.cb_trig_mode.currentIndex() != 2:
            self.cb_trig_mode.blockSignals(True)
            self.cb_trig_mode.setCurrentIndex(2)
            self.cb_trig_mode.blockSignals(False)

    # ------------------------------------------------------------- 导出
    def _on_view_range_changed(self, *args):
        """波形图 X/Y 范围变化 → 触发旋钮极值实时同步为 Y 轴可视极值。
        带防抖：用单次 QTimer 延迟合并连续的范围变化事件，避免高频重入。"""
        if getattr(self, "_range_debounce", None) is not None:
            try:
                self._range_debounce.stop()
            except Exception:  # noqa: BLE001
                pass
        self._range_debounce = QTimer(self)
        self._range_debounce.setSingleShot(True)
        self._range_debounce.setInterval(60)
        self._range_debounce.timeout.connect(self._sync_trig_range)
        self._range_debounce.start()

    def _on_plot_context_menu(self, pos):
        """波形图本地化右键菜单：复制图像 / 存 PNG / 导出 CSV / Auto / 清屏。"""
        menu = QMenu(self)
        a_copy = menu.addAction(tr("scope.menu.copy"))
        a_png = menu.addAction(tr("scope.menu.save_png"))
        menu.addSeparator()
        a_csv = menu.addAction(tr("scope.menu.export_csv"))
        a_npz = menu.addAction(tr("scope.menu.export_npz"))
        a_bin = menu.addAction(tr("scope.menu.export_bin"))
        a_auto = menu.addAction(tr("scope.menu.auto"))
        menu.addSeparator()
        a_clear = menu.addAction(tr("scope.menu.clear"))
        chosen = menu.exec(self.plot.mapToGlobal(pos))
        menu.deleteLater()
        if chosen == a_copy:
            self._copy_image()
        elif chosen == a_png:
            self.export_png()
        elif chosen == a_csv:
            self.export_csv()
        elif chosen == a_npz:
            self.export_npz()
        elif chosen == a_bin:
            self.export_bin()
        elif chosen == a_auto:
            self._on_auto()
        elif chosen == a_clear:
            self.clear()

    def _copy_image(self):
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setPixmap(self.plot.grab())

    def export_png(self):
        """把当前波形图保存为 PNG 图片（含所有已打开曲线与格线）。"""
        path, _ = QFileDialog.getSaveFileName(self, tr("scope.png_title"), "waveform.png",
                                              tr("save.png_ok"))
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            if self.plot.grab().save(path, "PNG"):
                from .export_dialogs import show_saved_dialog
                show_saved_dialog(
                    self, tr("export.title"),
                    trf("scope.png_done", path=path), path)
            else:
                QMessageBox.critical(self, tr("export.failed"), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("export.failed"), str(exc))

    def export_csv(self):
        """导出全部已打开通道（物理 + 已启用数学）的耦合数据为 CSV。

        每通道两列 <名称>_t / <名称>_y；通道间按行对齐，短通道补空。
        """
        import csv
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(self, tr("export.csv_title"), "waveform.csv",
                                              tr("save.csv_ok"))
        if not path:
            return
        try:
            data = {}
            cols = []
            # 导出所有已打开通道：物理通道（enabled）+ 启用数学通道
            channels = [(ch, info) for ch, info in self.channels.items()
                        if info.get("enabled", True)]
            for mkey, mspec in self.maths.items():
                if mspec.get("enabled", False):
                    channels.append((mkey, mspec))
            for ch, info in channels:
                t, y = self._get_coupled_arrays(ch)
                if y.size:
                    # 导出耦合数据（DC原样 / AC去直流）
                    data[ch] = (t, y)
                    cols.append(info["name"] + "_t")
                    cols.append(info["name"] + "_y")
            if not data:
                QMessageBox.information(self, tr("export.title"), tr("export.no_data"))
                return
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                maxlen = max(v[1].size for v in data.values())
                for i in range(maxlen):
                    row = []
                    for _ch, (t, y) in data.items():
                        if i < len(y):
                            row += [f"{t[i]:.6f}", f"{y[i]:.6f}"]
                        else:
                            row += ["", ""]
                    w.writerow(row)
            from .export_dialogs import show_saved_dialog
            show_saved_dialog(self, tr("export.title"), trf("export.done", path=path), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("export.failed"), str(exc))

    def export_npz(self):
        """导出为 NumPy NPZ（.npz）：每通道两个数组 <name>_t / <name>_y。"""
        path, _ = QFileDialog.getSaveFileName(self, tr("export.npz_title"), "waveform.npz",
                                              tr("save.npz_ok"))
        if not path:
            return
        if not path.lower().endswith(".npz"):
            path += ".npz"
        try:
            out = {}
            # 导出所有已打开通道：物理通道（enabled）+ 启用数学通道
            channels = [(ch, info) for ch, info in self.channels.items()
                        if info.get("enabled", True)]
            for mkey, mspec in self.maths.items():
                if mspec.get("enabled", False):
                    channels.append((mkey, mspec))
            for ch, info in channels:
                t, y = self._get_coupled_arrays(ch)
                if y.size:
                    out[f"{info['name']}_t"] = np.asarray(t, dtype=float)
                    # NPZ导出耦合数据
                    out[f"{info['name']}_y"] = np.asarray(y, dtype=float)
            if not out:
                QMessageBox.information(self, tr("export.title"), tr("export.no_data"))
                return
            np.savez_compressed(path, **out)
            from .export_dialogs import show_saved_dialog
            show_saved_dialog(self, tr("export.title"), trf("export.done", path=path), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("export.failed"), str(exc))

    def export_bin(self):
        """导出为二进制（.bin）：float32 小端，逐通道 [N][x0,y0,x1,y1,...] 交错写入。"""
        path, _ = QFileDialog.getSaveFileName(self, tr("export.bin_title"), "waveform.bin",
                                              tr("save.bin_ok"))
        if not path:
            return
        if not path.lower().endswith(".bin"):
            path += ".bin"
        try:
            blocks = []
            for ch in self.channels:
                t, y = self._get_coupled_arrays(ch)
                if y.size == 0:
                    continue
                # BIN导出耦合数据
                y_vec = np.asarray(y, dtype=np.float32)
                time_vec = np.asarray(t, dtype=np.float32)
                interleaved = np.empty(time_vec.size * 2, dtype=np.float32)
                interleaved[0::2] = time_vec
                interleaved[1::2] = y_vec
                n = np.array([time_vec.size], dtype=np.uint32)
                blocks.append((n.tobytes(), interleaved.tobytes()))
            if not blocks:
                QMessageBox.information(self, tr("export.title"), tr("export.no_data"))
                return
            with open(path, "wb") as f:
                for header, body in blocks:
                    f.write(header)
                    f.write(body)
            from .export_dialogs import show_saved_dialog
            show_saved_dialog(self, tr("export.title"), trf("export.done", path=path), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("export.failed"), str(exc))


class DistPanel(QWidget):
    """通道数值分布（直方图）面板：每通道一个小图，含启用的数学通道。

    - 小图数量随通道数自动排成近似方阵，所有通道一页显示。
    - 每个小图：自适应柱宽直方图 + 高斯（正态）拟合曲线 + 统计学标准读数
      （均值 μ / 标准差 σ / 样本数 N / 最小值 / 最大值 / 偏度 / 峰度）。
    - 支持单个小图与全部小图的 PNG 导出（含统计读数一并保存）。
    - 每 2 秒刷新一次（遵循实时示波器分布图逻辑）。
    """

    # 直方图单通道最大参与点数：大数据时步进抽取，避免每 2 秒全量重算造成卡顿
    _HIST_MAX_POINTS = 200_000

    def __init__(self, dh: DataHub, parent=None):
        super().__init__(parent)
        self.dh = dh              # 数据唯一来源（DataHub 数据总线），只读
        self._dirty = True
        self._layout_sig = None       # 已建布局的通道键序列（tuple）
        self._plots = []              # list[pg.PlotWidget]
        self._bars = {}               # key -> pg.BarGraphItem（直方图柱）
        self._curves = {}             # key -> pg.PlotDataItem（高斯拟合曲线）
        self._stats = {}              # key -> QLabel（统计学读数）
        self._cells = {}              # key -> QWidget（plot + 读数，用于整格导出）
        self._sigma_lines = {}        # key -> dict(3s_neg, 3s_pos) 3σ参考线
        self._sigma_texts = {}        # key -> dict(3s_neg, 3s_pos) 3σ线顶部指示文本
        self._dist_reset = {}         # key -> (epoch_t0, 相对时间阈值)；清屏/换格式后 epoch 变化自动失效
        self._hist_cache = {}         # key -> dict（最近一次直方图数据点，用于 CSV 导出）
        self._build_ui()
        self.retranslate()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000)       # 每 2 秒刷新一次分布图
        # 跟随波形主面板的数据上限：主面板改变时同步下拉框
        self.dh.max_points_changed.connect(self._sync_limit_combo)

    def _mark_dirty(self):
        self._dirty = True

    def _traces(self):
        """仅显示已勾选显示的迹线：模拟通道(启用) + 启用的数学通道，实时动态跟随选中情况。"""
        keys = [ch for ch, info in self.dh.channels.items() if info.get("enabled")]
        for key, spec in self.dh.maths.items():
            if spec.get("enabled"):
                keys.append(key)
        return keys

    def _build_ui(self):
        root = QVBoxLayout(self)
        top_bar = QHBoxLayout()
        self.lb_title = QLabel()
        self.lb_title.setStyleSheet("font-weight:600;")
        top_bar.addWidget(self.lb_title)
        top_bar.addStretch(1)
        self.lb_limit = QLabel()
        top_bar.addWidget(self.lb_limit)
        self.cb_limit = QComboBox()
        for label, val in POINT_LIMITS:
            self.cb_limit.addItem(label, val)
        self.cb_limit.currentIndexChanged.connect(self._on_limit_changed)
        top_bar.addWidget(self.cb_limit)
        self.btn_all = QPushButton()
        self.btn_all.clicked.connect(self._export_all)
        top_bar.addWidget(self.btn_all)
        root.addLayout(top_bar)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        root.addWidget(self.grid_host, 1)
        self.lb_note = QLabel()
        self.lb_note.setWordWrap(True)
        self.lb_note.setStyleSheet("color:#9aa4b2;font-size:11px;")
        root.addWidget(self.lb_note)

    def retranslate(self):
        self.lb_title.setText(tr("dist.title"))
        self.lb_limit.setText(tr("dist.limit"))
        self.cb_limit.setToolTip(tr("scope.limit_tip"))
        self.btn_all.setText(tr("dist.save_all"))
        self.btn_all.setToolTip(tr("dist.save_all_tip"))
        self.lb_note.setText(tr("dist.ac_note"))
        self._sync_limit_combo(self.dh.max_points)

    def apply_theme(self, theme: str):
        """把主题应用到分布图（各子图格线/背景/曲线色）。"""
        from .app_theme import style_plot
        for p in self._plots:
            style_plot(p, theme)
        self._dirty = True

    def _tick(self):
        try:
            if not self.isVisible() or self.window().isMinimized():
                return
            self.refresh()   # 每 2 秒刷新一次（仅当前页可见时），布局随通道/数学开关实时增减
        except Exception as exc:
            _log_refresh_error("DistPanel._tick", exc)

    def shutdown(self):
        """窗口关闭前停止本面板刷新计时器（BUG-O 清理）。"""
        self._timer.stop()

    def showEvent(self, event):
        """切换到分布图页签时立即刷新一次，无需等待下一个 2 秒周期。"""
        super().showEvent(event)
        try:
            self.refresh()
        except Exception as exc:
            _log_refresh_error("DistPanel.showEvent", exc)

    # ------------------------------------------------------------- 数据上限同步
    def _on_limit_changed(self, _idx):
        val = self.cb_limit.itemData(self.cb_limit.currentIndex())
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = MAX_POINTS
        self.dh.set_max_points(val)

    def _sync_limit_combo(self, value):
        idx = -1
        for i in range(self.cb_limit.count()):
            if self.cb_limit.itemData(i) == value:
                idx = i
                break
        self.cb_limit.blockSignals(True)
        if idx >= 0:
            self.cb_limit.setCurrentIndex(idx)
        self.cb_limit.blockSignals(False)

    # ------------------------------------------------------------- 布局
    def _ensure_layout(self):
        keys = tuple(self._traces())
        if keys == self._layout_sig:
            return
        # 清空旧布局与旧图
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._plots = []
        self._bars = {}
        self._curves = {}
        self._stats = {}
        self._sigma_texts = {}
        self._cells = {}
        self._sigma_lines = {}
        n = len(keys)
        if n == 0:
            self._layout_sig = keys
            return
        cols = max(1, int(math.ceil(math.sqrt(n))))
        rows = max(1, int(math.ceil(n / cols)))
        for idx, key in enumerate(keys):
            spec = self.dh._spec_of(key)
            name = spec["name"] if spec else (key if isinstance(key, str) else f"ch{key + 1}")
            color = spec["color"] if spec else "#00c8ff"

            plot_widget = pg.PlotWidget()
            plot_widget.showGrid(x=True, y=True, alpha=0.15)
            plot_widget.setMouseEnabled(False, False)
            try:
                plot_widget.setMenuEnabled(False)
            except Exception:  # noqa: BLE001
                pass
            plot_widget.setLabel("bottom", tr("dist.x_value"))
            plot_widget.setLabel("left", tr("dist.y_count"))
            plot_widget.setTitle(name, color=color)
            qcolor = QColor(color)
            bar = pg.BarGraphItem(x=[], height=[], width=0,
                                  brush=pg.mkBrush(
                    QColor(qcolor.red(), qcolor.green(), qcolor.blue(), 210)),
                                  pen=pg.mkPen(color, width=1))
            curve = plot_widget.plot(pen=pg.mkPen(QColor(255, 255, 255, 210), width=1.6))
            plot_widget.addItem(bar)

            # 3σ 参考线（动态更新位置）+ 顶部指示文本
            sigma_lines = {}
            sigma_texts = {}
            for label, color in [("3s_neg", "#ff6b6b"), ("3s_pos", "#ff6b6b")]:
                line = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine))
                line.setZValue(5)
                plot_widget.addItem(line)
                sigma_lines[label] = line
                # 线顶部的指示文本
                txt = pg.TextItem("", anchor=(0.5, 1), color=color)
                txt.setZValue(6)
                plot_widget.addItem(txt)
                sigma_texts[label] = txt
            self._sigma_lines[key] = sigma_lines
            self._sigma_texts[key] = sigma_texts

            # 每个小图带一条本地化右键菜单（单图保存/复制）
            plot_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            plot_widget.customContextMenuRequested.connect(
                lambda pos, k=key: self._one_context_menu(k, pos))

            stat = QLabel()
            stat.setWordWrap(True)
            stat.setStyleSheet(
                "color:#c8d2df;font-size:9px;background:rgba(20,24,30,170);"
                "border-radius:3px;padding:2px 4px;")
            stat.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

            cell = QWidget()
            cell_vbox = QVBoxLayout(cell)
            cell_vbox.setContentsMargins(0, 0, 0, 0)
            cell_vbox.setSpacing(2)
            cell_vbox.addWidget(plot_widget, 1)
            cell_vbox.addWidget(stat)

            self._plots.append(plot_widget)
            self._bars[key] = bar
            self._curves[key] = curve
            self._stats[key] = stat
            self._cells[key] = cell
            self.grid.addWidget(cell, idx // cols, idx % cols)
        for r in range(rows):
            self.grid.setRowStretch(r, 1)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        self._layout_sig = keys

    def _tr(self, key, default=""):
        spec = self.dh._spec_of(key)
        return spec["name"] if spec else default

    # ------------------------------------------------------------- 刷新
    def refresh(self):
        """分布图刷新：若启用数学通道先触发数据层重算，再重绘全部迹线直方图。"""
        self._ensure_layout()
        # DIST-01 修复：数学通道数据只在波形页 _draw_window 中计算，
        # 切到分布图页时若波形页未重绘，数学通道数据为旧值。
        # 此处若有启用的数学通道，主动触发一次重算，保证与模拟通道刷新一致。
        if any(s.get("enabled") for s in self.dh.maths.values()):
            self.dh.compute_math()
        for key in self._bars.keys():
            spec = self.dh._spec_of(key)
            if spec is None:
                continue
            # DIST 隔离优化：分布图只需最近 _HIST_MAX_POINTS×4 点参与统计，
            # 用 get_coupled_tail 避免把整条 FIFO 缓存（可达 80M/通道）全量复制，
            # 防止大数据缓存下主线程内存/GC 压力拖垮界面（含 FFT 大点数联动场景）。
            t, y = self.dh.get_coupled_tail(key, self._HIST_MAX_POINTS * 4)
            y = np.asarray(y, dtype=float)
            if y.size:
                reset = self._dist_reset.get(key)
                if reset is not None and reset[0] == self.dh.t0:
                    t = np.asarray(t, dtype=float)
                    y = y[t > reset[1]]
                # 分布图使用耦合数据（DC原样 / AC去直流）
                y_disp = y
            else:
                y_disp = np.array([], dtype=float)
            self._set_histogram(key, self._bars[key], self._curves[key], self._stats[key],
                                self._sigma_lines.get(key, {}), self._sigma_texts.get(key, {}), y_disp)

    def _set_histogram(self, key, bar, curve, stat_label, sigma_lines, sigma_texts, y_disp):
        """自适应柱宽直方图 + 高斯拟合 + 统计学读数（向量化）。"""
        self._hist_cache.pop(key, None)   # 导出 CSV 用最新一次直方图数据点
        y_disp = np.asarray(y_disp, dtype=float)
        y_disp = y_disp[np.isfinite(y_disp)]
        point_count = int(y_disp.size)
        if y_disp.size < 2:
            bar.setOpts(x=[], height=[], width=0)
            curve.setData([], [])
            stat_label.setText(tr("dist.no_data"))
            # 无数据时隐藏 3σ 参考线与指示文本，避免残留
            if sigma_lines:
                for line in sigma_lines.values():
                    line.setVisible(False)
                for txt in sigma_texts.values():
                    txt.setVisible(False)
            return
        # BUG-12 修复：统计量与 Scott 柱宽必须基于原始全量数据计算，
        # 步进抽取仅用于直方图绘制，避免柱宽估计偏大、统计量偏差。
        mean_val = float(np.mean(y_disp))
        std = float(np.std(y_disp))
        min_val = float(np.min(y_disp))
        max_val = float(np.max(y_disp))

        ptp = max_val - min_val
        if std > 1e-12:
            bin_width = 3.5 * std / (float(point_count) ** (1.0 / 3.0))   # Scott 规则（原始点数）
        else:
            bin_width = max(ptp / 50.0, 1e-9)
        # 大数据步进抽取，保证每 2 秒刷新不卡顿（仅影响绘制，不影响统计）
        if point_count > self._HIST_MAX_POINTS:
            step = int(math.ceil(point_count / self._HIST_MAX_POINTS))
            y_disp = y_disp[::step]
        if bin_width <= 0 or not math.isfinite(bin_width):
            bin_width = 1e-9
        lo, hi = min_val, max_val
        if hi - lo < 1e-12:
            lo -= abs(lo) * 0.1 + 1e-6
            hi += abs(hi) * 0.1 + 1e-6
        nbins = max(5, min(200, int(math.ceil((hi - lo) / bin_width))))
        counts, edges = np.histogram(y_disp, bins=nbins, range=(lo, hi))
        centers = (edges[:-1] + edges[1:]) / 2.0
        width = float(edges[1] - edges[0])
        bar.setOpts(x=centers, height=counts, width=width * 0.82)   # 收窄柱宽，柱间留缝更唯美
        # 缓存直方图数据点（bin 中心 / 计数 / 统计量），供右键导出 CSV
        self._hist_cache[key] = {
            "centers": np.asarray(centers, dtype=float),
            "counts": np.asarray(counts, dtype=float),
            "width": float(width), "mean_val": float(mean_val), "std": float(std),
            "point_count": int(point_count), "min_val": float(min_val), "max_val": float(max_val),
        }

        # 更新 3σ 参考线位置及顶部指示文本（动态更新）。
        # 【BUG-20 修复】counts 必须在 np.histogram 计算后才存在，
        # 旧代码在 histogram 之前引用 counts，NameError 被 try/except 吞掉，
        # 导致 y_text 恒为 1.0、3σ 文本位置固定错误。现移到 histogram 之后计算。
        if sigma_lines and std > 1e-12:
            positions = {"3s_neg": mean_val - 3 * std, "3s_pos": mean_val + 3 * std}
            labels = {"3s_neg": "-3σ", "3s_pos": "+3σ"}
            # 文本放在直方图内部顶部（最大计数的90%位置），避免影响Y轴自动范围
            try:
                max_count = float(np.max(counts)) if counts.size > 0 else 1.0
                y_text = max_count * 0.9
            except Exception:
                y_text = 1.0
            for label, pos in positions.items():
                sigma_lines[label].setPos(pos)
                sigma_lines[label].setVisible(True)
                if label in sigma_texts:
                    txt = sigma_texts[label]
                    txt.setText(labels[label] + " " + _fmt_num(pos))
                    txt.setPos(pos, y_text)
                    txt.setVisible(True)
        elif sigma_lines:
            for line in sigma_lines.values():
                line.setVisible(False)
            for txt in sigma_texts.values():
                txt.setVisible(False)

        # 高斯（正态）拟合曲线：按直方图面积等比例缩放，叠加在柱顶
        if std > 1e-12:
            gauss_x = np.linspace(lo, hi, 256)
            scale = float(np.sum(counts)) * width / (std * math.sqrt(2.0 * math.pi))
            gauss_y = scale * np.exp(-0.5 * ((gauss_x - mean_val) / std) ** 2)
            curve.setData(gauss_x, gauss_y)
        else:
            curve.setData([], [])

        # 偏度 / 峰度（超额峰度）
        z = (y_disp - mean_val) / std if std > 1e-12 else (y_disp - mean_val)
        skew = float(np.mean(z ** 3))
        kurtosis = float(np.mean(((y_disp - mean_val) / (std if std > 1e-12 else 1.0)) ** 4)) - 3.0

        # 扩展统计指标：集中趋势、离散程度、分位数
        median = float(np.median(y_disp))
        q1_val = float(np.percentile(y_disp, 25))
        q3_val = float(np.percentile(y_disp, 75))
        iqr = q3_val - q1_val
        variance = float(np.var(y_disp))
        data_range = max_val - min_val
        # MAD: 中位数绝对偏差
        mad = float(np.median(np.abs(y_disp - median)))
        # 变异系数 CV = σ/μ
        coef_var = (std / abs(mean_val)) if abs(mean_val) > 1e-12 else float('inf')
        # 均值标准误差 SEM = σ/√N
        sem = std / math.sqrt(point_count) if point_count > 0 else 0.0
        # 众数：直方图中最高柱的中心值
        if counts.size > 0:
            mode_idx = int(np.argmax(counts))
            mode_val = float(centers[mode_idx]) if mode_idx < len(centers) else mean_val
        else:
            mode_val = mean_val
        # 切尾均值（去掉首尾10%）
        trim_pct = 0.1
        y_sorted = np.sort(y_disp)
        trim_n = int(point_count * trim_pct)
        if trim_n > 0 and point_count - 2 * trim_n > 0:
            trim_mean = float(np.mean(y_sorted[trim_n:point_count - trim_n]))
        else:
            trim_mean = mean_val
        # 几何均值（仅对正数有效）
        if np.all(y_disp > 0):
            geo_mean = float(np.exp(np.mean(np.log(y_disp))))
        else:
            geo_mean = float('nan')

        # 统计信息显示：N放第一行第一列，然后按四类分组
        def format_value(v):
            """把直方图统计值格式化为文本（保留单位后缀）。"""
            if not math.isfinite(v):
                return "N/A"
            return _fmt_num(v)

        lines = []
        # 第一行：样本数量（第一行第一列）
        lines.append(tr("dist.stats_n") + "=" + str(point_count))
        # 集中趋势
        lines.append(
            tr("dist.cat_central") + ": "
            + tr("dist.stats_mean") + "=" + format_value(mean_val) + "  "
            + tr("dist.stats_median") + "=" + format_value(median) + "  "
            + tr("dist.stats_mode") + "=" + format_value(mode_val) + "  "
            + tr("dist.stats_trim_mean") + "=" + format_value(trim_mean) + "  "
            + tr("dist.stats_geo_mean") + "=" + format_value(geo_mean))
        # 离散程度
        lines.append(
            tr("dist.cat_dispersion") + ": "
            + tr("dist.stats_var") + "=" + format_value(variance) + "  "
            + tr("dist.stats_std") + "=" + format_value(std) + "  "
            + tr("dist.stats_range") + "=" + format_value(data_range) + "  "
            + tr("dist.stats_iqr") + "=" + format_value(iqr) + "  "
            + tr("dist.stats_mad") + "=" + format_value(mad) + "  "
            + tr("dist.stats_cv") + "=" + format_value(coef_var) + "  "
            + tr("dist.stats_sem") + "=" + format_value(sem))
        # 分布形态
        lines.append(
            tr("dist.cat_shape") + ": "
            + tr("dist.stats_skew") + "=" + f"{skew:.3g}" + "  "
            + tr("dist.stats_kurt") + "=" + f"{kurtosis:.3g}")
        # 分位数与边界（含 3σ 范围）
        s3_low = mean_val - 3 * std if std > 1e-12 else mean_val
        s3_high = mean_val + 3 * std if std > 1e-12 else mean_val
        lines.append(
            tr("dist.cat_quantile") + ": "
            + tr("dist.stats_min") + "=" + format_value(min_val) + "  "
            + tr("dist.stats_q1") + "=" + format_value(q1_val) + "  "
            + tr("dist.stats_q3") + "=" + format_value(q3_val) + "  "
            + tr("dist.stats_max") + "=" + format_value(max_val) + "  "
            + tr("dist.stats_3sigma") + "=[" + format_value(s3_low) + "," + format_value(s3_high) + "]")

        stat_label.setText("\n".join(lines))

    # ------------------------------------------------------------- 导出
    def _one_context_menu(self, key, position):
        """构建分布图单元格的右键菜单并处理动作（复位/存 PNG/导出 CSV/复制图像）。"""
        cell = self._cells.get(key)
        if cell is None:
            return
        name = self._tr(key)
        menu = QMenu(self)
        a_reset = menu.addAction(tr("dist.reset"))
        a_png = menu.addAction(tr("dist.save_one"))
        a_csv = menu.addAction(tr("dist.export_csv"))
        a_copy = menu.addAction(tr("dist.copy"))
        chosen = menu.exec(cell.mapToGlobal(position))
        menu.deleteLater()
        if chosen == a_reset:
            self._reset_channel(key)
            return
        if chosen == a_csv:
            self._export_csv(key)
            return
        if chosen == a_png:
            default = f"dist_{name.replace(' ', '_')}.png"
            path, _ = QFileDialog.getSaveFileName(self, tr("dist.png_title"), default,
                                                  tr("save.png_ok"))
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                self._save_cell(cell, path)
        elif chosen == a_copy:
            clip = QApplication.clipboard()
            if clip is not None:
                clip.setPixmap(cell.grab())

    def _export_csv(self, key):
        """导出当前显示图像的分布图数据点（直方图 bin：bin 中心值, 计数）。
        每行一个数据点，含表头；UTF-8 BOM 保证 Excel 直接打开不乱码。"""
        data = self._hist_cache.get(key)
        if data is None or data["centers"].size == 0:
            QMessageBox.information(self, tr("export.title"), tr("dist.no_data"))
            return
        try:
            import csv
            name = self._tr(key)
            default = f"dist_{name.replace(' ', '_')}.csv"
            path, _ = QFileDialog.getSaveFileName(self, tr("dist.csv_title"), default,
                                                  tr("save.csv_ok"))
            if not path:
                return
            if not path.lower().endswith(".csv"):
                path += ".csv"
            centers = data["centers"]
            counts = data["counts"]
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["# Distribution CSV", self._tr(key)])
                w.writerow(["# samples", data["point_count"]])
                w.writerow(["# mean", f"{data['mean_val']:.12g}"])
                w.writerow(["# std", f"{data['std']:.12g}"])
                w.writerow(["# bin_width", f"{data['width']:.12g}"])
                w.writerow(["bin_center", "count"])
                for c, n in zip(centers, counts):
                    w.writerow([f"{float(c):.12g}", int(round(float(n)))])
            from .export_dialogs import show_saved_dialog
            show_saved_dialog(self, tr("export.title"), trf("dist.csv_done", path=path), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("export.failed"), str(exc))

    def _reset_channel(self, key):
        """复位：清空本通道分布图，从当前时刻重新开始累积。"""
        t, _y = self.dh.get_arrays(key)
        if t.size:
            self._dist_reset[key] = (self.dh.t0, float(t[-1]))
        else:
            self._dist_reset.pop(key, None)
        self._dirty = True
        self.refresh()

    def _save_cell(self, cell, path):
        """将单个分布图单元格保存为 PNG，完成后弹出成功对话框。"""
        try:
            if cell.grab().save(path, "PNG"):
                from .export_dialogs import show_saved_dialog
                show_saved_dialog(
                    self, tr("export.title"),
                    trf("scope.png_done", path=path), path)
            else:
                QMessageBox.critical(self, tr("export.failed"), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("export.failed"), str(exc))

    def _export_all(self):
        """导出所有分布图通道的直方图数据（bin 中心值 + 计数）为 CSV。"""
        n = len(self._cells)
        if n == 0:
            QMessageBox.information(self, tr("export.title"), tr("dist.no_data"))
            return
        directory = QFileDialog.getExistingDirectory(self, tr("dist.dir_title"))
        if not directory:
            return
        saved = 0
        for key, cell in self._cells.items():
            name = self._tr(key)
            path = os.path.join(directory, f"dist_{name.replace(' ', '_')}.png")
            try:
                if cell.grab().save(path, "PNG"):
                    saved += 1
            except Exception:  # noqa: BLE001
                continue
        from .export_dialogs import show_saved_dialog
        show_saved_dialog(self, tr("export.title"),
                          trf("dist.all_done", n=saved, path=directory), directory)