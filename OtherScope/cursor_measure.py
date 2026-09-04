# -*- coding: utf-8 -*-
"""专业 X/Y 光标测量系统（CursorManager）。

参照 Keysight / R&S / Tektronix 的物理示波器光标规范：

- 四种状态：OFF / Manual（手动）/ Track（跟踪）/ Auto（自动）。
- 光标是**屏幕坐标的图形覆盖层**：Pan/Zoom 时屏幕位置绝对不变（以归一化分数
  坐标定位，随 ``sigRangeChanged`` 重映射数据坐标）；仅拖拽、键盘方向键、滚轮
  或 ``Set to Screen`` / ``Set to Wave`` 改变其位置。
- ``Track Scaling`` 开关：开启后缩放时不再屏幕锚定，而是按数据值锚定
  （光标相对波形的相位位置保持不变）。
- ``Coupling`` 联动：移动 X1 时 X2 同步以保持 ΔX，移动 Y1 时 Y2 同步以保持 ΔY。
- 读数面板（右下角半透明悬浮窗）：X1/X2/ΔX/1/ΔX/Y1/Y2/ΔY，3 位有效数字，
  单位自适应（s/ms/µs/ns、Hz/kHz/MHz、V/mV/µV 由 v_unit 决定）。

本模块不顶层导入 oscilloscope（避免循环导入），所需格式化函数在运行时懒导入。
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QObject, Signal, QPointF
from PySide6.QtWidgets import QLabel, QApplication

MODE_OFF = 0
MODE_MANUAL = 1
MODE_TRACK = 2
MODE_AUTO = 3

_COLORS = {
    "x1": "#ffaa00",   # 高亮橙黄
    "x2": "#00ffaa",   # 亮绿
    "y1": "#ffaa00",
    "y2": "#00ffaa",
}

_HIT_PX = 10            # 命中区域：10 像素
_FINE_STEP = 0.01       # 滚轮细调步长（归一化屏幕比例）
_COARSE_STEP = 0.1      # Shift/键盘粗调步长


class CursorManager(QObject):
    """管理四条 InfiniteLine 光标（X1/X2 竖线、Y1/Y2 横线）与读数面板。"""

    cursorMoved = Signal()

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.plot = panel.plot
        self.view_box = panel.plot.getPlotItem().vb

        self.mode = MODE_OFF
        self.source = None          # 测量源键（int 通道 / str 数学通道）
        self.active = "x1"          # 键盘循环激活对象
        self.track_scaling = False
        self.coupling = False
        self._frac = {"x1": 1 / 3.0, "x2": 2 / 3.0, "y1": 1 / 3.0, "y2": 2 / 3.0}
        self._visible = {"x1": True, "x2": True, "y1": True, "y2": True}
        self._drag = None           # 拖拽中的对象名
        self._hover = None          # 悬停命中的对象名
        self._auto_version = -1     # Auto 模式特征位置的缓存版本
        self._anchor = {"x1": None, "x2": None, "y1": None, "y2": None}
        # Track Scaling（数据锚定）锚点：X 光标存绝对时间，Y 光标存物理值。

        self.lines = {}
        for name, color in _COLORS.items():
            self.lines[name] = pg.InfiniteLine(
                angle=90 if name.startswith("x") else 0, movable=False,
                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine))
            self.plot.addItem(self.lines[name], ignoreBounds=True)

        # 读数面板：右下角半透明悬浮窗（不拦截鼠标事件，避免影响拖拽/缩放）
        self.readout = QLabel(self.plot.viewport())
        self.readout.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.readout.setStyleSheet(
            "QLabel{background:rgba(14,16,22,208);color:#e6edf5;"
            "font-family:Consolas,'Courier New',monospace;font-size:12px;"
            "padding:6px 9px;border:1px solid rgba(255,255,255,26);border-radius:4px;}")
        self.readout.hide()

        self.view_box.sigRangeChanged.connect(self._on_range_changed)
        self._apply_visibility()
        self._sync_positions()

    # ------------------------------------------------------------- 公共接口
    def enable(self):
        """显式启用（若处于 OFF 则切到 Manual）。"""
        if self.mode == MODE_OFF:
            self.set_mode(MODE_MANUAL)

    def disable(self):
        self.set_mode(MODE_OFF)

    def set_mode(self, mode):
        """设置光标测量模式并同步相关状态。

        Args:
            mode: 模式常量（MODE_OFF/MODE_MANUAL/MODE_TRACK/MODE_AUTO）。

        Returns:
            None。
        """
        self.mode = int(mode)
        try:
            if self.mode == MODE_TRACK:
                self._sync_track()
            elif self.mode == MODE_AUTO:
                self._auto_refresh(force=True)
            else:
                self._sync_positions()
        except Exception:  # noqa: BLE001 —— 特征定位失败不阻断光标显示
            pass
        # 无论特征定位是否成功，都必须刷新可见性与读数，避免光标“显示不出来”
        self._apply_visibility()
        self._place_readout()
        if self.track_scaling:
            self._snapshot_anchor()
        self._emit()

    def set_source(self, key):
        """设置光标测量源（物理通道 int / 数学通道 str）。"""
        self.source = key
        if self.mode == MODE_TRACK:
            self._sync_track()
        elif self.mode == MODE_AUTO:
            self._auto_refresh(force=True)
        self._emit()

    def set_line_visible(self, name, checked):
        self._visible[name] = bool(checked)
        self._apply_visibility()
        self._emit()

    def set_track_scaling(self, on):
        """切换跟踪光标锚定方式（屏幕锚定 / 数据锚定）。

        开启：快照当前各光标线的数据坐标（X=绝对时间、Y=物理值）为锚点，
        此后缩放/平移（时基、水平位置、触发窗口、垂直灵敏度变化）时由
        ``_remap_anchored`` 按锚点数据坐标重算显示位置，光标相对波形的
        相位位置保持不变（数据锚定，Keysight Track 语义）。
        关闭：由当前线位置反推屏幕分数，恢复屏幕锚定（Pan/Zoom 时线
        固定在屏幕位置不动）。
        """
        self.track_scaling = bool(on)
        if self.track_scaling:
            self._snapshot_anchor()
        else:
            self._frac_from_lines()

    def _snapshot_anchor(self):
        """快照当前各光标线的数据坐标（Track Scaling 锚点）。

        X 光标存绝对时间（相对屏幕中心坐标 + 屏幕中心绝对时间），
        Y 光标存物理值（显示值经逆换算回通道单位）。
        Auto 模式的特征定位不参与锚定（其本身按数据更新周期刷新）。
        """
        if self.mode == MODE_AUTO:
            return
        for name, line in self.lines.items():
            try:
                if name.startswith("x"):
                    self._anchor[name] = self._abs_x(float(line.value()))
                else:
                    self._anchor[name] = self.panel._disp_to_phys(
                        self.source, float(line.value()))
            except Exception:  # noqa: BLE001
                self._anchor[name] = None

    def _remap_anchored(self):
        """数据锚定重映射：按快照的数据坐标重算光标显示位置。

        由波形绘制层在视图中心（``_last_center``）与垂直换算参数
        （v_div/v_pos）更新为最新值后调用，使缩放/平移时光标相对波形的
        相位位置保持不变。仅在 Track Scaling 开启且非 Auto 模式时生效。
        """
        if not self.track_scaling or self.mode == MODE_AUTO:
            return
        for name, line in self.lines.items():
            anchor = self._anchor.get(name)
            if anchor is None:
                continue
            try:
                if name.startswith("x"):
                    line.setValue(self._rel_x(anchor))
                else:
                    line.setValue(self.panel._phys_to_disp(self.source, anchor))
            except Exception:  # noqa: BLE001 —— 换算异常时保持原位置，不阻断
                continue

    def set_coupling(self, on):
        self.coupling = bool(on)

    # ------------------------------------------------------------- 坐标工具
    def _in_view(self, scene_pos):
        return self.view_box.sceneBoundingRect().contains(scene_pos)

    def _view_range(self):
        try:
            return self.view_box.viewRange()
        except Exception:  # noqa: BLE001
            return ([0.0, 1.0], [0.0, 1.0])

    def _rel_x(self, x_abs):
        """固定屏幕坐标系：绝对时间 → 相对屏幕中心坐标（X 轴显示坐标）。"""
        try:
            return float(x_abs) - float(self.panel._last_center)
        except Exception:  # noqa: BLE001
            return x_abs

    def _abs_x(self, x_rel):
        """固定屏幕坐标系：相对屏幕中心坐标 → 绝对时间（用于搜索数据）。"""
        try:
            return float(x_rel) + float(self.panel._last_center)
        except Exception:  # noqa: BLE001
            return x_rel

    def _set_frac(self, name, frac, clip=True):
        if clip:
            frac = min(max(frac, 0.0), 1.0)
        self._frac[name] = frac

    def _line_scene_pos(self, name):
        line = self.lines[name]
        try:
            if name.startswith("x"):
                return self.view_box.mapViewToScene(QPointF(line.value(), 0.0))
            return self.view_box.mapViewToScene(QPointF(0.0, line.value()))
        except Exception:  # noqa: BLE001
            return None

    def _hit_name(self, scene_pos):
        best, best_d = None, 1e18
        for name, line in self.lines.items():
            if not line.isVisible():
                continue
            line_label = self._line_scene_pos(name)
            if line_label is None:
                continue
            distance = (abs(line_label.x() - scene_pos.x()) if name.startswith("x")
                        else abs(line_label.y() - scene_pos.y()))
            if distance < best_d:
                best_d, best = distance, name
        return best if best is not None and best_d <= _HIT_PX else None

    def _sync_positions(self):
        rx, y_range = self._view_range()
        for name, line in self.lines.items():
            frac = self._frac[name]
            if name.startswith("x"):
                line.setValue(rx[0] + frac * (rx[1] - rx[0]))
            else:
                line.setValue(y_range[0] + frac * (y_range[1] - y_range[0]))
        self._update_highlight()

    def _frac_from_lines(self):
        rx, y_range = self._view_range()
        for name, line in self.lines.items():
            if name.startswith("x"):
                denom = (rx[1] - rx[0]) or 1.0
                self._frac[name] = (line.value() - rx[0]) / denom
            else:
                denom = (y_range[1] - y_range[0]) or 1.0
                self._frac[name] = (line.value() - y_range[0]) / denom

    def _update_highlight(self):
        for name, line in self.lines.items():
            highlighted = ((self.mode == MODE_MANUAL and name == self.active)
                           or (self.mode == MODE_TRACK and name in ("x1", "y1")))
            line.setPen(pg.mkPen(_COLORS[name], width=2 if highlighted else 1,
                               style=Qt.PenStyle.DashLine))

    def _apply_visibility(self):
        if self.mode == MODE_OFF:
            for line in self.lines.values():
                line.setVisible(False)
            self.readout.hide()
            return
        for name, line in self.lines.items():
            if self.mode == MODE_TRACK:
                line.setVisible(name in ("x1", "y1"))
            elif self.mode == MODE_AUTO:
                line.setVisible(True)
            else:   # Manual
                line.setVisible(self._visible.get(name, True))
        self.readout.show()
        self._place_readout()

    def _on_range_changed(self, *_args):
        if self.mode in (MODE_OFF, MODE_AUTO):
            return                                  # OFF 隐藏；Auto 特征位置数据锚定
        if self.track_scaling:
            # Track Scaling（数据锚定）：此处视图中心尚未更新到最新值，
            # 不做重映射（避免用旧中心错误换算），由波形绘制层在重绘后
            # 调用 _remap_anchored 按锚点数据坐标完成跟随。
            return
        if self.mode == MODE_TRACK:
            self._sync_track()
            return
        self._sync_positions()                      # Manual：屏幕锚定，Pan/Zoom 坐标不动

    # ------------------------------------------------------------- 模式行为
    def _sync_track(self):
        if self.source is None:
            self._sync_positions()
            return
        try:
            t, y = self.panel._get_arrays_deduped(self.source)
        except Exception:  # noqa: BLE001
            t, y = None, None
        if t is None or t.size < 1 or self.panel._spec_of(self.source) is None:
            self._sync_positions()
            return
        rx, _ry = self._view_range()
        xtarget = rx[0] + self._frac["x1"] * (rx[1] - rx[0])
        x_abs = self._abs_x(xtarget)   # 相对坐标 → 绝对时间搜索数据
        idx = int(np.searchsorted(t, x_abs))
        idx = min(max(idx, 0), int(t.size - 1))
        if idx > 0 and abs(float(t[idx - 1]) - x_abs) < abs(float(t[idx]) - x_abs):
            idx -= 1
        x_val = float(t[idx])
        y_disp = np.asarray(self.panel._display_y(self.source, np.asarray(y, dtype=float)),
                        dtype=float)
        self.lines["x1"].setValue(self._rel_x(x_val))
        self.lines["y1"].setValue(float(y_disp[idx]))
        self._update_highlight()

    def _auto_refresh(self, force=False):
        if self.mode != MODE_AUTO:
            return
        if not force and self._auto_version == self.panel.version:
            return
        self._auto_version = self.panel.version
        if self.source is None:
            return
        try:
            t, y = self.panel._get_arrays_deduped(self.source)
        except Exception:  # noqa: BLE001
            return
        if t.size < 2 or self.panel._spec_of(self.source) is None:
            return
        y_disp = np.asarray(self.panel._display_y(self.source, np.asarray(y, dtype=float)),
                        dtype=float)
        imin, imax = int(np.argmin(y_disp)), int(np.argmax(y_disp))
        self.lines["y1"].setValue(float(y_disp[imin]))
        self.lines["y2"].setValue(float(y_disp[imax]))
        self.lines["x1"].setValue(self._rel_x(float(t[imin])))
        self.lines["x2"].setValue(self._rel_x(float(t[imax])))
        self._emit()

    def set_to_screen(self):
        self._frac = {"x1": 1 / 3.0, "x2": 2 / 3.0, "y1": 1 / 3.0, "y2": 2 / 3.0}
        self._sync_positions()
        if self.track_scaling:
            self._snapshot_anchor()
        self._emit()

    def set_to_wave(self):
        """对齐当前屏幕可视波形（修复原"对齐异常"）。
        - Y 光标对齐可视窗口内波形 min/max（显示值，含垂直位置平移）；
        - X 光标对齐物理值上升过零点（y<0→y>=0，真实周期起始），
          不再使用含垂直位置偏移的显示值过零点（原实现 DC 偏移非零时
          对不到真实周期起点），且仅限当前可视窗口，避免吸附屏幕外过零点。"""
        if self.source is None:
            return
        try:
            t, y = self.panel._get_arrays_deduped(self.source)
        except Exception:  # noqa: BLE001
            return
        if t.size < 2 or self.panel._spec_of(self.source) is None:
            return
        # 仅限可视窗口（X 轴为相对坐标，搜索数据需转回绝对时间）
        rx, _ = self._view_range()
        idx_start = int(np.searchsorted(t, self._abs_x(rx[0]), side="left"))
        idx_end = int(np.searchsorted(t, self._abs_x(rx[1]), side="right"))
        if idx_end <= idx_start:
            idx_start, idx_end = 0, int(t.size)
        t = t[idx_start:idx_end]
        y = y[idx_start:idx_end]
        if t.size < 2:
            return
        y = np.asarray(y, dtype=float)
        y_disp = np.asarray(self.panel._display_y(self.source, y), dtype=float)
        self.lines["y1"].setValue(float(np.min(y_disp)))
        self.lines["y2"].setValue(float(np.max(y_disp)))
        # X 光标对齐信号均值上升过零点（相对均值，对含 DC 偏置信号同样对齐真实周期起点）
        y_mean = float(np.mean(y)) if y.size else 0.0
        base = y - y_mean
        idx = np.flatnonzero((base[:-1] < 0.0) & (base[1:] >= 0.0))
        if idx.size >= 2:
            x1, x2 = float(t[idx[0]]), float(t[idx[1]])
        elif idx.size == 1:
            x1, x2 = float(t[idx[0]]), float(t[-1])
        else:
            x1, x2 = float(t[0]), float(t[-1])
        self.lines["x1"].setValue(self._rel_x(x1))
        self.lines["x2"].setValue(self._rel_x(x2))
        self._frac_from_lines()
        if self.track_scaling:
            self._snapshot_anchor()
        self._emit()

    # ------------------------------------------------------------- 鼠标交互
    def handle_clicked(self, scene_pos):
        """处理场景点击：命中光标线则进入拖拽。

        Args:
            scene_pos: 场景坐标点。

        Returns:
            bool：True 表示事件已消费。
        """
        if self.mode in (MODE_OFF, MODE_AUTO):
            return False
        if not self._in_view(scene_pos):
            return False
        if self.mode == MODE_TRACK:
            self._drag = "x1"
            self._move_track(scene_pos)
            return True
        name = self._hit_name(scene_pos)
        if name is not None:
            self._drag = name
            self.active = name
            self._update_highlight()
            return True
        return False

    def handle_moved(self, scene_pos):
        """处理鼠标移动：拖拽光标线或更新悬停高亮。

        Args:
            scene_pos: 场景坐标点。

        Returns:
            None 或拖拽目标名（str）。
        """
        if self.mode in (MODE_OFF, MODE_AUTO) or not self._in_view(scene_pos):
            return None
        if self._drag is not None:
            if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._drag = None
                return None
            self._move_active(scene_pos)
            self._emit()
            return self._drag_shape(self._drag)
        if self.mode == MODE_TRACK:
            self._move_track(scene_pos)
            self._emit()
            return Qt.CursorShape.CrossCursor
        name = self._hit_name(scene_pos)
        self._hover = name
        return self._drag_shape(name) if name is not None else None

    def handle_released(self):
        """鼠标释放：结束拖拽并清除悬停状态。"""
        self._drag = None
        self._hover = None

    @staticmethod
    def _drag_shape(name):
        if name is None:
            return None
        return (Qt.CursorShape.SizeHorCursor if name.startswith("x")
                else Qt.CursorShape.SizeVerCursor)

    def _move_active(self, scene_pos):
        name = self._drag
        if name is None:
            return
        view = self.view_box.mapSceneToView(scene_pos)
        rx, y_range = self._view_range()
        if name.startswith("x"):
            denom = (rx[1] - rx[0]) or 1.0
            frac = (view.x() - rx[0]) / denom
            old = self._frac[name]
            self._set_frac(name, frac)
            if self.coupling:
                other = "x2" if name == "x1" else "x1"
                self._set_frac(other, self._frac[other] + (frac - old))
        else:
            denom = (y_range[1] - y_range[0]) or 1.0
            frac = (view.y() - y_range[0]) / denom
            old = self._frac[name]
            self._set_frac(name, frac)
            if self.coupling:
                other = "y2" if name == "y1" else "y1"
                self._set_frac(other, self._frac[other] + (frac - old))
        self._sync_positions()
        if self.track_scaling:
            self._snapshot_anchor()

    def _move_track(self, scene_pos):
        view = self.view_box.mapSceneToView(scene_pos)
        rx, _ry = self._view_range()
        denom = (rx[1] - rx[0]) or 1.0
        self._set_frac("x1", (view.x() - rx[0]) / denom)
        self._sync_track()
        if self.track_scaling:
            self._snapshot_anchor()

    # ------------------------------------------------------------- 键盘 / 滚轮
    def handle_key_press(self, event):
        """处理按键：Esc 取消、Tab 切换光标、方向键微调。

        Args:
            event: QKeyEvent 事件对象。

        Returns:
            bool：True 表示事件已消费。
        """
        if self.mode in (MODE_OFF, MODE_AUTO):
            return False
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._drag = None
            self._hover = None
            self.active = "x1"
            self._update_highlight()
            return True
        if key == Qt.Key.Key_Tab:
            self._cycle_active()
            return True
        coarse = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = _COARSE_STEP if coarse else _FINE_STEP
        name = self._active_target(key)
        if name is None:
            return False
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._set_frac(name, self._frac[name] - step)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._set_frac(name, self._frac[name] + step)
        else:
            return False
        self._sync_positions()
        if self.track_scaling:
            self._snapshot_anchor()
        self._emit()
        return True

    def _cycle_active(self):
        order = ["x1", "x2", "y1", "y2"]
        if self.active in order:
            self.active = order[(order.index(self.active) + 1) % 4]
        else:
            self.active = "x1"
        self._update_highlight()
        self.cursorMoved.emit()

    def _active_target(self, key):
        """方向键对应的可调对象：激活的 X 光标响应水平，Y 光标响应垂直。"""
        if self.mode == MODE_TRACK:
            return "x1" if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) else None
        if (key in (Qt.Key.Key_Left, Qt.Key.Key_Right)
                and self.active in ("x1", "x2")):
            return self.active
        if (key in (Qt.Key.Key_Up, Qt.Key.Key_Down)
                and self.active in ("y1", "y2")):
            return self.active
        return None

    def handle_wheel(self, delta_y):
        """处理滚轮：悬停光标线上时微调其位置。

        Args:
            delta_y: 滚轮增量（正上负下）。

        Returns:
            bool：True 表示事件已消费。
        """
        if self.mode in (MODE_OFF, MODE_AUTO):
            return False
        name = self._hover          # 仅在悬停到光标线上时微调，其余交由 ViewBox 缩放
        if name is None:
            return False
        step = _FINE_STEP * (1.0 if delta_y > 0 else -1.0)
        self._set_frac(name, self._frac[name] + step)
        if self.mode == MODE_TRACK:
            self._sync_track()
        else:
            self._sync_positions()
        if self.track_scaling:
            self._snapshot_anchor()
        self._emit()
        return True

    # ------------------------------------------------------------- 读数
    def _emit(self):
        self._update_readout()
        self.cursorMoved.emit()

    def _update_readout(self):
        self.readout.setText(self.readout_text())
        self._place_readout()

    def _readout_values(self):
        from .oscilloscope import _fmt_time, _fmt_freq, _amp
        # 单位唯一来源是光标源通道的单位列
        spec = self.panel._spec_of(self.source) if self.source is not None else None
        unit = spec.get("unit", "V") if spec is not None else self.panel.v_unit
        dash = "---"

        def tv(line):
            return line.value() if line.isVisible() else None

        # 光标线存储的是显示值（Y轴单位，含垂直位置平移），需转换为物理值：
        # 统一反解：物理 = (显示×Y轴系数 − 垂直位置×垂直灵敏度) / 通道系数
        def to_phys(v):
            """把显示坐标值换算回物理值（含单位逆变换）。"""
            if v is None:
                return None
            return self.panel._disp_to_phys(self.source, v)

        x1v, x2v = tv(self.lines["x1"]), tv(self.lines["x2"])
        y1v, y2v = to_phys(tv(self.lines["y1"])), to_phys(tv(self.lines["y2"]))
        out = {
            # 光标 X 值存相对坐标，读数显示绝对时间
            "x1": _fmt_time(self._abs_x(x1v)) if x1v is not None else dash,
            "x2": _fmt_time(self._abs_x(x2v)) if x2v is not None else dash,
            "y1": _amp(y1v, unit) if y1v is not None else dash,
            "y2": _amp(y2v, unit) if y2v is not None else dash,
            "dx": dash, "freq": dash, "dy": dash,
        }
        if x1v is not None and x2v is not None:
            dt_sec = abs(x2v - x1v)
            out["dx"] = _fmt_time(dt_sec)
            out["freq"] = _fmt_freq(1.0 / dt_sec if dt_sec > 0 else 0.0)
        if y1v is not None and y2v is not None:
            out["dy"] = _amp(abs(y2v - y1v), unit)
        return out

    def readout_text(self):
        """生成光标测量读数文本（X/Y 位置与差值，完成单位换算与格式拼接）。"""
        v = self._readout_values()
        return (f"X1    {v['x1']}\n"
                f"X2    {v['x2']}\n"
                f"ΔX    {v['dx']}\n"
                f"1/ΔX  {v['freq']}\n"
                f"Y1    {v['y1']}\n"
                f"Y2    {v['y2']}\n"
                f"ΔY    {v['dy']}")

    def readout_summary(self):
        """生成单行测量摘要（Δt / 1/Δt / ΔY）。"""
        v = self._readout_values()
        return f"Δt={v['dx']}  1/Δt={v['freq']}  ΔY={v['dy']}"

    def _place_readout(self):
        viewport = self.plot.viewport()
        if viewport is None:
            return
        self.readout.adjustSize()
        w, h = self.readout.width(), self.readout.height()
        self.readout.move(max(0, viewport.width() - w - 12),
                          max(0, viewport.height() - h - 12))
        self.readout.raise_()