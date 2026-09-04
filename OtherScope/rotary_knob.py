# -*- coding: utf-8 -*-
"""虚拟旋钮控件（RotaryKnob）。

仿专业示波器：按住旋钮绕中心做圆周拖动（顺时针增大、逆时针减小），滚轮也可调节。
采用「左侧旋钮圆盘 + 右侧实时值(上)/名称(下)」的复合布局，实时值用 QLabel 展示，
彻底避免数值被圆盘绘制的标签遮挡；多个旋钮并排时以足够间距隔离，互不干扰。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel


class _Dial(QWidget):
    """仅负责绘制与鼠标交互的旋钮圆盘，读取/回写宿主 RotaryKnob 的状态。"""

    def __init__(self, knob, parent=None):
        super().__init__(parent)
        self.knob = knob
        self.setFixedSize(80, 80)
        self.setMouseTracking(True)

    # ------------------------------------------------------------- 角度
    def _screen_angle(self, pos):
        center_x = center_y = self.width() / 2.0
        delta_y = pos.y() - center_y
        delta_x = pos.x() - center_x
        return math.degrees(math.atan2(delta_y, delta_x))

    # ------------------------------------------------------------- 交互
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            knob = self.knob
            knob._dragging = True
            knob._last_angle = self._screen_angle(event.position())
            knob._start_val = knob._value
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        knob = self.knob
        if not knob._dragging:
            super().mouseMoveEvent(event)
            return
        pos = event.position()
        center_x = center_y = self.width() / 2.0
        if abs(pos.x() - center_x) < 1.0 and abs(pos.y() - center_y) < 1.0:
            event.accept()
            return
        cur = self._screen_angle(pos)
        delta_angle = knob._wrap_angle(cur - knob._last_angle)
        fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        knob._apply_angle_delta(delta_angle, fine)
        knob._last_angle = cur
        knob._start_val = knob._value
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.knob._dragging = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.knob._wheel_delta(event.angleDelta().y(), event.modifiers())
        event.accept()

    # ------------------------------------------------------------- 绘制
    def paintEvent(self, event):
        knob = self.knob
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x = center_y = self.width() / 2.0
        r = self.width() / 2.0 - 8
        rect = QRectF(center_x - r, center_y - r, r * 2, r * 2)

        pen_track = QPen(QColor("#2a2f3a"), 6)
        pen_track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_track)
        p.drawArc(rect, int(225 * 16), int(-270 * 16))

        frac_val = knob._frac()
        pen_val = QPen(QColor("#00c8ff"), 6)
        pen_val.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_val)
        p.drawArc(rect, int(225 * 16), int(-frac_val * 270 * 16))

        p.setPen(QPen(QColor("#3a4350"), 2))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            a = math.radians(knob._angle(frac))
            cos_a, sin_alpha = math.cos(a), math.sin(a)
            p.drawLine(QPointF(center_x + (r + 2) * cos_a, center_y - (r + 2) * sin_alpha),
                       QPointF(center_x + (r + 9) * cos_a, center_y - (r + 9) * sin_alpha))

        ang = math.radians(knob._angle(frac_val))
        needle_radius = r - 14
        p.setPen(QPen(QColor("#d8dee9"), 3))
        p.drawLine(QPointF(center_x, center_y),
                  QPointF(center_x + needle_radius * math.cos(ang),
                          center_y - needle_radius * math.sin(ang)))
        p.setPen(QPen(QColor("#d8dee9"), 1))
        p.setBrush(QColor("#2a2f3a"))
        p.drawEllipse(QPointF(center_x, center_y), 5, 5)
        p.end()


class RotaryKnob(QWidget):
    """可旋转拖动/滚轮的旋钮控件（旋钮左、值上名称下右）。"""

    valueChanged = Signal(float)

    def __init__(self, label="", min_value=0.0, max_value=1.0, value=0.5, unit="",
                 log=False, decimals=2, format_str=None, parent=None):
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self.log_scale = log
        self.decimals = decimals
        self.format_str = format_str
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        self._value = self._clamp(float(value))
        self._dragging = False
        self._last_angle = 0.0
        self._start_val = 0.0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._dial = _Dial(self)
        lay.addWidget(self._dial)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._lbl_value = QLabel()
        self._lbl_value.setStyleSheet("color:#00c8ff;font-weight:600;font-size:14px;")
        self._lbl_value.setAlignment(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_name = QLabel(self.label)
        self._lbl_name.setStyleSheet("color:#9aa4b2;font-size:11px;")
        self._lbl_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        col.addWidget(self._lbl_value)
        col.addWidget(self._lbl_name)
        lay.addLayout(col)
        lay.addStretch(1)

        self.setMouseTracking(True)
        self._width_hint = 190
        self.setFixedSize(self._width_hint, 88)
        self._sync_value_label()

    # ------------------------------------------------------------- 数值
    def _clamp(self, v):
        if self.max_value > self.min_value:
            return min(max(v, self.min_value), self.max_value)
        return v

    def value(self):
        return self._value

    def setValue(self, v, emit=True):
        v = self._clamp(float(v))
        if v == self._value:
            return
        self._value = v
        self._dial.update()
        self._sync_value_label()
        if emit and not self.signalsBlocked():
            self.valueChanged.emit(v)

    def setLabel(self, text):
        """更新旋钮名称标签（语言切换时同步 QLabel 文本）。

        Args:
            text: 新的标签文本。
        """
        self.label = str(text)
        if hasattr(self, "_lbl_name"):
            self._lbl_name.setText(self.label)
        self.update()

    def setRange(self, min_value, max_value):
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        old = self._value
        self._value = self._clamp(self._value)
        self._dial.update()
        self._sync_value_label()
        # 范围变化导致当前值被 clamp 时，emit valueChanged 通知外部。
        if self._value != old and not self.signalsBlocked():
            self.valueChanged.emit(self._value)

    # ------------------------------------------------------------- 标度
    def _frac_value(self, v):
        if self.max_value == self.min_value:
            return 0.0
        if self.log_scale:
            if self.min_value <= 0 or v <= 0:
                return 0.0
            lo = math.log10(self.min_value)
            hi = math.log10(self.max_value)
            return (math.log10(v) - lo) / (hi - lo)
        return (v - self.min_value) / (self.max_value - self.min_value)

    def _frac(self):
        return self._frac_value(self._value)

    def _from_frac(self, frac):
        frac = min(max(frac, 0.0), 1.0)
        if self.max_value == self.min_value:
            return self.min_value
        if self.log_scale:
            if self.min_value <= 0:
                return self.min_value
            lo = math.log10(self.min_value)
            hi = math.log10(self.max_value)
            return 10.0 ** (lo + (hi - lo) * frac)
        return self.min_value + (self.max_value - self.min_value) * frac

    @staticmethod
    def _wrap_angle(angle):
        angle = angle % 360.0
        if angle > 180.0:
            angle -= 360.0
        return angle

    @staticmethod
    def _angle(frac):
        return 225.0 - frac * 270.0

    def _value_text(self):
        if self.format_str is not None:
            txt = self.format_str(self._value)
        else:
            txt = f"{self._value:.{self.decimals}f}"
        if self.unit:
            txt += self.unit
        return txt

    def _sync_value_label(self):
        if hasattr(self, "_lbl_value"):
            self._lbl_value.setText(self._value_text())
            self._lbl_name.setText(self.label)

    # ------------------------------------------------------------- 交互
    def _apply_angle_delta(self, delta_angle, fine=False):
        if self.max_value == self.min_value:
            return
        delta_frac = delta_angle / 270.0 * (0.1 if fine else 1.0)
        self.setValue(self._from_frac(self._frac_value(self._start_val) + delta_frac))

    def _wheel_delta(self, delta, modifiers):
        if delta == 0:
            return
        fine = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        step = (delta / 120.0) * (0.1 if fine else 1.0)
        if self.log_scale:
            if self.min_value > 0:
                lo = math.log10(self.min_value)
                hi = math.log10(self.max_value)
                cur = math.log10(self._value) if self._value > 0 else lo
                cur += step * (hi - lo) / 40.0
                self.setValue(10.0 ** cur)
        else:
            self.setValue(self._value + step * (self.max_value - self.min_value) / 50.0)