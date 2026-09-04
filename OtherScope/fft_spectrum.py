# -*- coding: utf-8 -*-
"""FFT 频谱分析面板（独立模块）。

【设计原则】
- 本模块与 串口终端 / 波形示波器 / 分布图 完全独立：不引用任何其它窗口的内部实现。
- 数据引用：仅从 DataHub 只读读取「耦合数据」副本（get_coupled_tail），
  串口终端仍是唯一写入方，本窗口对数据源只有只读权限。
- 采样率来源：由用户显式输入「ADC 采样率」（数值 + 单位 Hz/kHz/MHz），
  FFT 的频率轴 / 奈奎斯特频率 / 频率分辨率全部基于该采样率解析，
  与串口波特率、数据缓存大小完全解耦。
- 刷新机制：独立 QTimer（500ms），仅当前页可见时刷新；FFT 点数上限 512K，
  主线程 numpy.fft.rfft 计算毫秒级完成，无需后台线程，杜绝线程共享数据。

【FFT 处理管线】（对应 FFT 设计原理）
1. 去直流（DC Removal）：x - mean(x)，消除 0Hz 巨大分量，避免掩盖微弱信号。
2. 加窗（Window）：矩形 / 汉宁 / 汉明 / 布莱克曼 / 平顶，压制频谱泄漏（旁瓣）。
3. 蝶形运算（FFT）：numpy.fft.rfft —— 基2 Cooley-Tukey 算法；实序列利用
   共轭对称性只计算 0~N/2 一半谱线（等价于报告所述“实数填充 + 半谱”优化）。
4. 幅值转换：线性 Magnitude = sqrt(Re² + Im²) 或 dB = 20·log10(Magnitude)。
5. 频率映射：f = k·(fs/N)，fs 为用户输入的 ADC 采样率。
6. 峰值检测：抛物线插值精确定位谱峰。
"""

from __future__ import annotations

import math
import os
import traceback as _tb

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QCheckBox, QLineEdit, QFileDialog, QMenu)

from .translations import tr, trf
from .data_hub import DataHub

# ---------------------------------------------------------------- 常量
# FFT 点数（2 的幂，512 ~ 512K；上限 512K 保证主线程 rfft 毫秒级完成）
FFT_POINTS = [512, 1024, 2048, 4096, 8192, 16384, 32768,
              65536, 131072, 262144, 524288]
# ADC 采样率单位
FS_UNITS = [("Hz", 1.0), ("kHz", 1e3), ("MHz", 1e6)]

# 崩溃日志（本模块独立维护，不依赖其它窗口）
_CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "OtherScope_crash.log")


def _log_err(where, error):
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as file_handle:
            file_handle.write(f"\n==== 刷新异常 @ {where} ====\n")
            _tb.print_exc(file=file_handle)
    except Exception:
        # 崩溃日志写盘失败不能影响正常刷新流程：静默忽略
        pass


# ---------------------------------------------------------------- 计算引擎
class FftEngine(object):
    """FFT 纯计算引擎：输入时域耦合数据，输出频域频谱参数。

    纯静态方法、无状态、不持有任何缓存 —— 与 UI 完全解耦，
    可独立单元测试，绝不触碰 DataHub 内部数据。
    """

    @staticmethod
    def remove_dc(y):
        """去直流：减去均值，消除 0Hz 巨大分量（对应报告『去直流预处理』）。"""
        m = float(np.mean(y))
        return y - m

    @staticmethod
    def window(n, kind):
        """生成窗函数系数（长度 n）。kind: rect/hann/hamming/blackman/flattop。"""
        n = max(2, int(n))
        if kind == "hann":
            return np.hanning(n)
        if kind == "hamming":
            return np.hamming(n)
        if kind == "blackman":
            return np.blackman(n)
        if kind == "flattop":
            # 平顶窗：幅值精度最佳（对应报告「平顶幅值精度最佳」）
            a0, a1, a2, a3 = 0.21557895, 0.41663158, 0.277263158, 0.083578947
            x = np.linspace(0.0, 2.0 * np.pi, n)
            return a0 - a1 * np.cos(x) + a2 * np.cos(2.0 * x) - a3 * np.cos(3.0 * x)
        # rect（默认）：不加窗，旁瓣 -13dB，仅适合瞬态/整周期采样
        return np.ones(n)

    @staticmethod
    def fft_radix2(y):
        """自定义基2-时间抽取 FFT（numpy 向量化蝶形运算）。

        对应报告『数据位反转 + 多级蝶形迭代 + 原位运算』。
        返回完整复数频谱 X[k]（长度 N）。用于教学/性能对照，
        工程默认走 numpy.fft.rfft（更快且更省内存）。
        """
        y = np.asarray(y, dtype=float)
        n = y.shape[0]
        if n & (n - 1) != 0:
            raise ValueError("FFT length must be a power of 2")
        # 位反转重排（向量化：idx → 反转索引 → 重排，对应报告『数据位反转』）
        num_bits = n.bit_length() - 1
        idx = np.arange(n, dtype=np.int64)
        bit_reverse = np.zeros(n, dtype=np.int64)
        for b in range(num_bits):
            bit_reverse |= ((idx >> b) & 1) << (num_bits - 1 - b)
        x = np.array(y[bit_reverse], dtype=complex)
        # 多级蝶形（原位运算：写回 x 同一数组）
        length = 2
        while length <= n:
            ang = -2.0 * np.pi / length
            win_vals = np.exp(1j * ang * np.arange(length // 2))
            half = length // 2
            for i in range(0, n, length):
                # 取副本避免视图别名：x[i:i+half] 赋值会原地修改，
                # 若不 copy，第二步 even - t 会用到已覆盖的 even
                even = x[i:i + half].copy()
                odd = x[i + half:i + length].copy()
                t = odd * win_vals
                x[i:i + half] = even + t
                x[i + half:i + length] = even - t
            length <<= 1
        return x

    @staticmethod
    def compute(y, n_fft, fs, window_kind="hann", mode="amp", db=False,
                use_custom_fft=False):
        """完整 FFT 管线。

        参数：
            y         : 时域耦合数据（1-D float）
            n_fft     : FFT 点数（2 的幂）
            fs        : ADC 采样率（Hz，用户输入解析得到）
            window_kind: rect/hann/hamming/blackman/flattop
            mode      : amp/phase/real/imag
            db        : 纵轴 dB（对数）
            use_custom_fft: True 使用自定义基2蝶形（慢），默认 numpy.fft.rfft
        返回：
            dict: freq, display, peaks(list of (f,v)), n_used, dt,
                  fs, nyq, df（频率分辨率）
        """
        y = np.asarray(y, dtype=float)
        n = int(y.size)
        if n < 2:
            raise ValueError("insufficient data")
        # 1) 截取最近 n_fft 点（不足则用全部）
        num_used = min(n, int(n_fft))
        y = y[-num_used:]
        # 2) 去直流
        y = FftEngine.remove_dc(y)
        # 3) 加窗
        win = FftEngine.window(num_used, window_kind)
        windowed = y * win
        coherent = float(np.sum(win)) or 1.0
        # 4) 蝶形运算（FFT）
        if use_custom_fft and (num_used & (num_used - 1)) == 0:
            Y = FftEngine.fft_radix2(windowed)
            freq = np.fft.fftfreq(num_used, d=1.0 / fs)
            magnitude = np.abs(Y) * (2.0 / coherent)
            magnitude[0] = 0.0
        else:
            Y = np.fft.rfft(windowed)
            freq = np.fft.rfftfreq(num_used, d=1.0 / fs)
            magnitude = np.abs(Y) * (2.0 / coherent)
            if num_used % 2 == 0:
                magnitude[-1] *= 0.5
            magnitude[0] = 0.0
        # 5) 显示量转换
        if mode == "phase":
            display = np.angle(Y)
        elif mode == "real":
            display = Y.real
        elif mode == "imag":
            display = Y.imag
        else:  # amp
            display = magnitude
        if db:
            with np.errstate(divide="ignore", invalid="ignore"):
                display = 20.0 * np.log10(np.maximum(display, 1e-12))
        # 6) 峰值检测（抛物线插值）：仅考虑正频率半轴。
        #    自定义全谱 FFT 的负频率镜像峰与正峰幅值相同，若一并参与排序，
        #    top 峰可能落在负频率（如 -50Hz），造成读数错误——正半轴取峰即可。
        peak_mag = magnitude
        if use_custom_fft:
            peak_mag = magnitude.copy()
            peak_mag[freq < 0] = 0.0
        peaks = FftEngine._find_peaks(freq, peak_mag, top=8)
        dt_sec = (1.0 / fs) if fs > 0 else 0.0
        nyq = fs / 2.0 if fs > 0 else 0.0
        freq_resolution = (fs / num_used) if (fs > 0 and num_used > 0) else 0.0
        return {"freq": freq, "display": display, "peaks": peaks,
                "n_used": num_used, "dt": dt_sec, "fs": fs, "nyq": nyq, "df": freq_resolution}

    @staticmethod
    def _find_peaks(freq, magnitude, top=8):
        """局部极大值 + 抛物线插值精确定位谱峰，返回 [(f, v), ...] 按幅值降序。"""
        magnitude = np.asarray(magnitude, dtype=float)
        freq = np.asarray(freq, dtype=float)
        if magnitude.size < 3:
            return []
        # 局部极大值（排除边界与 0Hz）
        idx = np.where((magnitude[1:-1] > magnitude[:-2])
                       & (magnitude[1:-1] > magnitude[2:]))[0] + 1
        idx = idx[magnitude[idx] > 0]
        if idx.size == 0:
            return []
        # 取幅值最大的若干峰
        order = np.argsort(magnitude[idx])[::-1][:top]
        out = []
        for i in order:
            k = int(idx[i])
            if 1 <= k <= magnitude.size - 2:
                y0, y1, y2 = magnitude[k - 1], magnitude[k], magnitude[k + 1]
                denom = y0 - 2.0 * y1 + y2
                if abs(denom) > 1e-12:
                    delta = 0.5 * (y0 - y2) / denom
                else:
                    delta = 0.0
                delta = max(-0.5, min(0.5, delta))
                f = float(freq[k]) + delta * (float(freq[1]) - float(freq[0]))
                v = float(y1 - 0.25 * (y0 - y2) * delta)
            else:
                f, v = float(freq[k]), float(magnitude[k])
            out.append((f, v))
        out.sort(key=lambda p: -p[1])
        return out


# ---------------------------------------------------------------- UI 面板
class FftSpectrumPanel(QWidget):
    """FFT 频谱面板（全新独立实现）。

    数据流：DataHub(只读 get_coupled_tail) → FftEngine → 本窗口绘图。
    与其它窗口零共享内部状态；采样率完全由用户输入控制。
    """

    def __init__(self, dh: DataHub, parent=None):
        super().__init__(parent)
        self.dh = dh
        self._dirty = True
        self._seen_version = -1
        self._last_result = None
        self._channels = {}
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.apply_theme("dark")

    # ------------------------------------------------------------ UI 构建
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # 顶部控件行（ADC 采样率 + 参数）
        top = QHBoxLayout()
        top.setSpacing(6)
        # ADC 采样率：用户显式输入
        self.lb_samplerate = QLabel()
        self.ed_samplerate = QLineEdit("1000")
        self.ed_samplerate.setFixedWidth(80)
        self.ed_samplerate.setToolTip("")
        self.cb_fs_unit = QComboBox()
        for label, _m in FS_UNITS:
            self.cb_fs_unit.addItem(label)
        self.cb_fs_unit.setCurrentIndex(0)
        self.ed_samplerate.textChanged.connect(lambda _t: self._mark_dirty())
        self.cb_fs_unit.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        # 通道
        self.cb_channel = QComboBox()
        self.cb_channel.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        # 窗函数
        self.cb_win = QComboBox()
        for k, key in enumerate(("rect", "hann", "hamming", "blackman", "flattop")):
            self.cb_win.addItem(tr(f"fft.window.{key}"), key)
        self.cb_win.setCurrentIndex(1)  # 默认汉宁
        self.cb_win.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        # 显示模式
        self.cb_mode = QComboBox()
        for k, key in enumerate(("amp", "phase", "real", "imag")):
            self.cb_mode.addItem(tr(f"fft.mode.{key}"), key)
        self.cb_mode.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        # 点数
        self.cb_nfft = QComboBox()
        for v in FFT_POINTS:
            self.cb_nfft.addItem(_fmt_points(v), v)
        self.cb_nfft.setCurrentIndex(max(0, self.cb_nfft.findData(8192)))
        self.cb_nfft.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        # dB
        self.chk_db = QCheckBox()
        self.chk_db.setChecked(True)
        self.chk_db.toggled.connect(lambda _c: self._mark_dirty())
        # 连续刷新：勾选后定时器每 500ms 在数据更新时自动重算；未勾选则仅手动/切页刷新
        self.cb_cont = QCheckBox()
        self.cb_cont.setChecked(True)
        self.cb_cont.toggled.connect(lambda _c: self._mark_dirty())
        # 自动调整：一键把频谱调整到最合适的视觉观察状态
        self.btn_auto = QPushButton()
        self.btn_auto.clicked.connect(self._auto_scale)
        # 立即 FFT
        self.btn_now = QPushButton()
        self.btn_now.clicked.connect(self._force_refresh)
        # 复制 / 保存 PNG
        self.btn_copy = QPushButton()
        self.btn_copy.clicked.connect(self._copy_image)
        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self.export_png)

        for w in (self.lb_samplerate, self.ed_samplerate, self.cb_fs_unit, self.cb_channel,
                  self.cb_win, self.cb_mode, self.cb_nfft, self.chk_db,
                  self.cb_cont, self.btn_auto, self.btn_now,
                  self.btn_copy, self.btn_save):
            top.addWidget(w)
        top.addStretch(1)
        root.addLayout(top)

        # 频谱图
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setMenuEnabled(False)
        self.curve = self.plot.plot(pen=pg.mkPen("#22d3ee", width=1.2))
        self.pm_curve = self.plot.plot(pen=None, symbol="o",
                                       symbolSize=7, symbolBrush="#fbbf24",
                                       symbolPen=pg.mkPen("#fbbf24"))
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True)
        self.plot.setAutoVisible(y=True)
        self.plot.scene().contextMenu = None
        self.plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(self._on_plot_menu)
        root.addWidget(self.plot, 1)

        # 峰值列表
        self.lb_peaks = QLabel()
        self.lb_peaks.setWordWrap(True)
        self.lb_peaks.setStyleSheet("color:#c8d2df;font-size:9px;")
        root.addWidget(self.lb_peaks)

        # 采样率关系提示（fs / 奈奎斯特 / 频率分辨率）
        self.lb_info = QLabel()
        self.lb_info.setWordWrap(True)
        self.lb_info.setStyleSheet("color:#8a94a6;font-size:9px;")
        root.addWidget(self.lb_info)

    # ------------------------------------------------------------ 主题
    def apply_theme(self, theme):
        if theme == "light":
            bg_color, fg_color = "#ffffff", "#1f2937"
            self.plot.setBackground("#f8fafc")
        else:
            bg_color, fg_color = "#0b0e14", "#e5e7eb"
            self.plot.setBackground("#0b0e14")
        self.setStyleSheet(
            f"FftSpectrumPanel{{background:{bg_color};}}"
            f"FftSpectrumPanel QLabel{{color:{fg_color};}}")

    # ------------------------------------------------------------ 国际化
    def retranslate(self):
        """语言切换后重译本面板全部静态文本。"""
        self.lb_samplerate.setText(tr("fft.adc_fs"))
        self.cb_channel.setToolTip(tr("fft.ch_tip"))
        self.cb_win.setToolTip(tr("fft.window_tip"))
        self.cb_mode.setToolTip(tr("fft.mode_tip"))
        self.cb_nfft.setToolTip(tr("fft.points_tip"))
        self.cb_cont.setToolTip(tr("fft.cont_tip"))
        self.btn_auto.setToolTip(tr("fft.auto_tip"))
        self.chk_db.setText(tr("fft.db"))
        self.cb_cont.setText(tr("fft.cont"))
        self.btn_auto.setText(tr("fft.auto"))
        self.btn_now.setText(tr("fft.now"))
        self.btn_copy.setText(tr("fft.copy"))
        self.btn_save.setText(tr("fft.save_png"))
        self.plot.setLabel("bottom", tr("fft.x_freq"), units="Hz")
        # 重填下拉的翻译文本（保持 data）
        for i in range(self.cb_win.count()):
            key = self.cb_win.itemData(i)
            self.cb_win.setItemText(i, tr(f"fft.window.{key}"))
        for i in range(self.cb_mode.count()):
            key = self.cb_mode.itemData(i)
            self.cb_mode.setItemText(i, tr(f"fft.mode.{key}"))
        self.ed_samplerate.setToolTip(tr("fft.adc_fs_tip"))
        self._refresh_rel()
        self._mark_dirty()

    # ------------------------------------------------------------ 数据同步
    def sync_channels(self):
        """从 DataHub 同步通道列表（只读），保持本窗口通道下拉最新。"""
        self._channels = dict(self.dh.channels)
        # BUG-I 修复：同步列表加入启用的数学通道（M1-M4），FFT 支持对数学通道分析
        for mkey, mspec in self.dh.maths.items():
            if mspec.get("enabled", False):
                self._channels[mkey] = mspec
        current_text = self.cb_channel.currentText()
        self.cb_channel.blockSignals(True)
        self.cb_channel.clear()
        for key, spec in self._channels.items():
            self.cb_channel.addItem(spec.get("name", str(key)), key)
        if current_text:
            idx = self.cb_channel.findText(current_text)
            if idx >= 0:
                self.cb_channel.setCurrentIndex(idx)
        self.cb_channel.blockSignals(False)
        self._mark_dirty()

    # ------------------------------------------------------------ 刷新
    def _mark_dirty(self):
        self._dirty = True

    def _force_refresh(self):
        self._dirty = True
        try:
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            _log_err("FftSpectrumPanel._force_refresh", exc)

    def showEvent(self, event):
        super().showEvent(event)
        self._mark_dirty()
        try:
            self._tick()
        except Exception as exc:  # noqa: BLE001
            _log_err("FftSpectrumPanel.showEvent", exc)

    def _tick(self):
        if not self.isVisible():
            return
        # 仅「连续刷新」勾选时才由定时器自动重算；未勾选时保持静止，
        # 由「立即 FFT」/切换控件后的手动刷新或切页刷新驱动。
        if not self.cb_cont.isChecked():
            return
        try:
            if self._dirty or self._seen_version != self.dh.version:
                self.refresh()
        except Exception as exc:  # noqa: BLE001
            _log_err("FftSpectrumPanel._tick", exc)

    def refresh(self):
        """从 DataHub 只读取耦合数据 → FftEngine 计算 → 更新频谱图。"""
        self._dirty = False
        self._seen_version = self.dh.version
        if self.cb_channel.count() == 0:
            self._clear_display(tr("fft.no_channel"))
            return
        ch = self.cb_channel.currentData()
        if ch is None:
            ch = 0
        # 用户输入 ADC 采样率
        fs = self._parse_fs()
        if fs is None:
            self._clear_display(tr("fft.bad_fs"))
            return
        # 只读取最近所需点数（FIFO 尾部，独立取数，不复制全量）
        n_fft = int(self.cb_nfft.currentData() or 8192)
        t, y = self.dh.get_coupled_tail(ch, n_fft)
        if y.size < 2:
            self._clear_display(tr("fft.insufficient"))
            return
        try:
            res = FftEngine.compute(
                y, n_fft, fs,
                window_kind=str(self.cb_win.currentData() or "hann"),
                mode=str(self.cb_mode.currentData() or "amp"),
                db=self.chk_db.isChecked())
        except Exception as exc:  # noqa: BLE001
            self._clear_display(tr("fft.error") + f": {exc}")
            return
        self._last_result = res
        freq = res["freq"]
        display = res["display"]
        unit = self._ch_unit(ch)
        self.curve.setData(freq, display)
        # 纵轴标签
        mode = self.cb_mode.currentData() or "amp"
        if mode == "amp":
            self.plot.setLabel("left", tr("fft.y_mag"),
                               units=("dB" if self.chk_db.isChecked() else unit))
        elif mode == "phase":
            self.plot.setLabel("left", tr("fft.y_phase"), units="°")
        else:
            self.plot.setLabel("left", tr(f"fft.mode.{mode}"),
                               units=unit)
        # 峰值
        peaks = res["peaks"]
        if peaks:
            peak_x = [p[0] for p in peaks]
            peak_y = [p[1] for p in peaks]
            self.pm_curve.setData(peak_x, peak_y)
            lines = [f"{f:.4g}Hz ({v:.4g}{'dB' if self.chk_db.isChecked() else unit})"
                     for f, v in peaks[:6]]
            self.lb_peaks.setText(tr("fft.peaks") + "  " + "  |  ".join(lines))
        else:
            self.pm_curve.clear()
            self.lb_peaks.setText(tr("fft.no_peak"))
        # 采样率关系提示（基于用户 ADC 采样率）
        self._last_fs = fs
        self._last_nfft = n_fft
        self._refresh_rel()

    def _parse_fs(self):
        """解析用户输入的 ADC 采样率（数值 × 单位），非法返回 None。"""
        try:
            val = float(self.ed_samplerate.text().strip())
        except ValueError:
            return None
        # BUG-M 修复：拦截 NaN/Inf（float("nan") 不抛异常且 nan<=0 为假）
        if not math.isfinite(val) or val <= 0:
            return None
        mult = FS_UNITS[self.cb_fs_unit.currentIndex()][1]
        return val * mult

    def _ch_unit(self, ch):
        """返回通道单位（物理与数学通道统一），用于 FFT Y 轴标签。"""
        spec = self.dh._spec_of(ch)
        if spec:
            return str(spec.get("unit", "V") or "V")
        return "V"

    def _refresh_rel(self):
        """显示 fs / 奈奎斯特 / 频率分辨率（基于用户 ADC 采样率，实时刷新）。"""
        fs = getattr(self, "_last_fs", 0.0)
        n_fft = getattr(self, "_last_nfft", 0)
        if fs > 0:
            nyq = fs / 2.0
            freq_resolution = (fs / n_fft) if n_fft > 0 else 0.0
            self.lb_info.setText(trf("fft.rel", fs=f"{fs:.4g}",
                                    nyq=f"{nyq:.4g}", df=f"{freq_resolution:.4g}"))
        else:
            self.lb_info.setText(tr("fft.rel_none"))

    def _auto_scale(self):
        """一键自动调整：把当前频谱图缩放到最合适的视觉观察状态。
        - Y 轴：幅度/dB 以最高峰为基准（dB 显示峰顶-100dB ~ 峰顶+5dB，
          线性显示 0 ~ 最高峰*1.05）；相位固定 ±π；实部/虚部按数据范围留 5% 边距。
        - X 轴：聚焦包含所有检测谱峰的频率区间（无峰时显示全频带 0 ~ fs/2）。
        """
        res = getattr(self, "_last_result", None)
        if res is None:
            return
        display = res.get("display")
        if display is None or display.size == 0:
            return
        mode = str(self.cb_mode.currentData() or "amp")
        db = self.chk_db.isChecked()
        valid = display[np.isfinite(display)]
        if valid.size == 0:
            return
        vmax = float(valid.max())
        vmin = float(valid.min())
        # ---- Y 轴 ----
        if mode == "phase":
            y_lo, y_hi = -np.pi, np.pi
        elif db:
            y_lo, y_hi = vmax - 100.0, vmax + 5.0
        elif mode == "amp":
            y_lo, y_hi = 0.0, vmax * 1.05
        else:
            span = (vmax - vmin) or 1.0
            y_lo, y_hi = vmin - span * 0.05, vmax + span * 0.05
        if y_hi - y_lo < 1e-12:
            y_lo, y_hi = y_lo - 1.0, y_hi + 1.0
        self.plot.setYRange(float(y_lo), float(y_hi))
        # ---- X 轴 ----
        peaks = res.get("peaks") or []
        nyq = res.get("nyq") or 0.0
        freq_resolution = res.get("df") or 0.0
        if peaks:
            # 只聚焦「显著峰」（幅值不低于主峰 10%），忽略微小噪声峰，
            # 使主频与真实谐波清晰可见而窗口不被噪声拉宽。
            peak_vmax = max(float(p[1]) for p in peaks)
            sig = [p for p in peaks if float(p[1]) >= peak_vmax * 0.1]
            if not sig:
                sig = peaks[:1]
            peak_freqs = [float(p[0]) for p in sig]
            freq_min, freq_max = min(peak_freqs), max(peak_freqs)
            span = freq_max - freq_min
            pad = max(span * 0.3, freq_resolution * 50.0, freq_min * 0.5, freq_resolution)
            x_lo = max(0.0, freq_min - pad)
            x_hi = min(nyq, freq_max + pad) if nyq > 0 else freq_max + pad
            if x_hi - x_lo < 1e-12:
                x_hi = x_lo + max(freq_resolution * 100.0, 1e-6)
            self.plot.setXRange(float(x_lo), float(x_hi))
        else:
            self.plot.setXRange(0.0, float(nyq) if nyq > 0 else 1.0)

    def _clear_display(self, info):
        self.curve.setData([], [])
        self.pm_curve.clear()
        self.lb_peaks.setText("")
        self.lb_info.setText(info)
        self._last_result = None

    # ------------------------------------------------------------ 导出/复制
    def _copy_image(self):
        """将当前频谱图复制到剪贴板。"""
        try:
            q_application_class = __import__(
                "PySide6.QtWidgets", fromlist=["QApplication"]).QApplication
            q_application_class.clipboard().setPixmap(
                self.plot.grab())
        except Exception as exc:  # noqa: BLE001
            _log_err("FftSpectrumPanel._copy_image", exc)

    def export_png(self):
        """将当前频谱图保存为 PNG，完成后弹出「打开/打开文件夹/确定」对话框。"""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("fft.png_title"), "fft.png", "PNG (*.png)")
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                if self.plot.grab().save(path, "PNG"):
                    from .export_dialogs import show_saved_dialog
                    show_saved_dialog(self, tr("fft.png_title"),
                                      trf("scope.png_done", path=path), path)
        except Exception as exc:  # noqa: BLE001
            _log_err("FftSpectrumPanel.export_png", exc)

    def _on_plot_menu(self, position):
        menu = QMenu(self)
        act_copy = QAction(tr("fft.copy"), self)
        act_copy.triggered.connect(self._copy_image)
        act_save = QAction(tr("fft.save_png"), self)
        act_save.triggered.connect(self.export_png)
        act_now = QAction(tr("fft.now"), self)
        act_now.triggered.connect(self._force_refresh)
        act_auto = QAction(tr("fft.auto"), self)
        act_auto.triggered.connect(self._auto_scale)
        menu.addAction(act_copy)
        menu.addAction(act_save)
        menu.addAction(act_auto)
        menu.addAction(act_now)
        menu.exec(self.plot.mapToGlobal(position))

    def shutdown(self):
        """程序退出时停止定时器。"""
        self._timer.stop()


# ---------------------------------------------------------------- 工具
def _fmt_points(v):
    v = int(v)
    if v >= 1024:
        for unit, div in (("M", 1048576), ("K", 1024)):
            if v % div == 0 and (v // div) in (1, 2, 4, 5, 8, 10, 16, 20,
                                               32, 40, 64, 80, 128, 160,
                                               256, 320, 512, 640):
                return f"{v // div}{unit}"
    return str(v)
