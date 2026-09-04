# -*- coding: utf-8 -*-
"""可复用的数值调节控件。

``PlusMinusBox``：纯数值输入框（可带单位后缀）。数值调整方式统一为两种：
1. 键盘直接键入（含 QDoubleValidator 校验）；
2. 鼠标悬停在控件正上方时滚动滚轮微调（步长 = ``step``）。

采用「数值 + 单位」布局，数值居中且随位数自然增宽；移除了传统 SpinBox 的上下
箭头与旧版「＋ / −」按钮（当前 UI 下箭头渲染不出），避免遮挡。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QEvent, QSize
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QLabel

from .translations import tr


class PlusMinusBox(QWidget):
    """数值输入 +（可选）单位的控件。

    API 兼容 QDoubleSpinBox 常用子集：value/valueChanged/setValue/setRange/
    setDecimals/setSingleStep/setSuffix/minimum/maximum/blockSignals。
    """

    valueChanged = Signal(float)

    def __init__(self, min_value=0.0, max_value=100.0, value=0.0, decimals=2,
                 step=1.0, suffix="", parent=None):
        super().__init__(parent)
        self._minimum = float(min_value)
        self._maximum = float(max_value)
        self._value = float(self._clamp(value))
        self._decimals = int(decimals)
        self._step = float(step)
        self._suffix = suffix or ""
        self._updating = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self.line_edit = QLineEdit()
        self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.line_edit.setFixedHeight(24)
        # validator 设置数值范围，用户输入超范围时即时拦截，
        # 而非失焦后才 clamp 回范围内。
        self._validator = QDoubleValidator()
        self._validator.setRange(self._minimum, self._maximum, self._decimals)
        self.line_edit.setValidator(self._validator)
        self.line_edit.editingFinished.connect(self._on_edit)
        self.line_edit.returnPressed.connect(self._on_edit)
        self.line_edit.setToolTip(tr("pmb.edit_tip"))
        self.line_edit.installEventFilter(self)   # 捕获滚轮：悬停控件即微调
        lay.addWidget(self.line_edit, 1)

        self.lb_unit = QLabel(self._suffix)
        self.lb_unit.setStyleSheet("color:#9aa4b2;")
        lay.addWidget(self.lb_unit)

        self._sync_text()

    # ------------------------------------------------------------- 工具
    def _clamp(self, v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        if self._maximum > self._minimum:
            return min(max(v, self._minimum), self._maximum)
        return v

    def _format(self, v):
        if self._decimals <= 0:
            return f"{round(v):d}"
        # 用 g 避免极小/极大数值被固定小数截断，且位宽随有效数字自然增长
        return f"{v:.{self._decimals}g}"

    def _sync_text(self):
        self._updating = True
        self.line_edit.setText(self._format(self._value))
        self._updating = False

    # ------------------------------------------------------------- API
    def value(self):
        return self._value

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum

    def setDecimals(self, decimals):
        self._decimals = int(decimals)
        self._validator.setDecimals(self._decimals)
        self._sync_text()

    def setSingleStep(self, step):
        self._step = float(step)

    def setSuffix(self, suffix):
        self._suffix = suffix or ""
        self.lb_unit.setText(self._suffix)

    def setRange(self, lo, hi):
        self._minimum = float(lo)
        self._maximum = float(hi)
        self._validator.setRange(self._minimum, self._maximum, self._decimals)
        self._value = self._clamp(self._value)
        self._sync_text()

    def setValue(self, v, emit=True):
        v = self._clamp(v)
        changed = v != self._value
        self._value = v
        self._sync_text()
        if changed and emit and not self.signalsBlocked():
            self.valueChanged.emit(self._value)

    # ------------------------------------------------------------- 交互
    def _step_up(self):
        self.setValue(self._value + self._step)

    def _step_down(self):
        self.setValue(self._value - self._step)

    def _on_edit(self):
        if self._updating:
            return
        txt = self.line_edit.text().strip()
        try:
            v = float(txt)
        except ValueError:
            v = self._value
        self.setValue(v)

    def _apply_wheel(self, delta):
        self.setValue(self._value + (self._step if delta > 0 else -self._step))

    def eventFilter(self, widget, event):
        # 仅在控件正上方（含编辑框）滚动滚轮时微调；键盘输入不受影响
        if widget is self.line_edit and event.type() == QEvent.Type.Wheel:
            self._apply_wheel(event.angleDelta().y())
            return True
        return super().eventFilter(widget, event)

    def wheelEvent(self, event):
        """鼠标滚轮步进调节：正旋增大、反旋减小，避免误触。"""
        delta = event.angleDelta().y()
        if delta:
            self._apply_wheel(delta)
            event.accept()
            return
        super().wheelEvent(event)

    def sizeHint(self):
        """按数值文本宽度给出建议尺寸，供表格列 ResizeToContents 自动增宽。"""
        metric = self.line_edit.fontMetrics()
        width = metric.horizontalAdvance(self._format(self._value)) + 34
        width += metric.horizontalAdvance(self._suffix) + 10
        width = max(width, 88)
        return QSize(width + 12, 26)

    def minimumSizeHint(self):
        return self.sizeHint()

    def retranslate(self):
        """语言切换后刷新编辑框提示（无箭头按钮，仅更新提示文案）。"""
        self.line_edit.setToolTip(tr("pmb.edit_tip"))