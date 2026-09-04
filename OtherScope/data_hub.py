# -*- coding: utf-8 -*-
"""数据总线（DataHub）：串口数据的唯一数据源。

架构约定（满足多窗口解耦要求）：
- 串口终端解析出的每一帧数据，唯一通过 ``append_frame`` 写入本对象；
- 波形示波器 / FFT 频谱 / 分布图三个窗口各自独立，只通过只读接口
  （``get_arrays`` / ``get_coupled_arrays`` / ``compute_math``）获取数据副本，
  互不直接引用，实现 4 窗口代码解耦；
- 窗口 / 控件之间通过本对象的公共属性与信号（``data_updated`` /
  ``max_points_changed``）通信（数据总线 / 邮箱模式），保证实时性；
- 环形缓冲 ``_Buf``、通用去重/格式化工具亦随数据层迁移至此，
  避免 oscilloscope.py 与 data_bus.py 相互导入造成循环依赖。
"""

from __future__ import annotations

import math
import re

import numpy as np
from collections import deque

from PySide6.QtCore import QObject, Signal

from .math_expression import evaluate as math_eval

# 每通道默认数据上限（FIFO 环形缓存容量，可被界面控件改小/改大）
MAX_POINTS = 100_000
MIN_POINT_LIMIT = 1_000
# 绝对安全边界：全局缓存上限 10G（每点 16 字节 × 通道数，80M×8 通道≈10G）
MAX_POINT_LIMIT = 80_000_000

# 数据上限档位（label 用于展示，value 为每通道最多保存的点数，先进先出覆盖）
POINT_LIMITS = [("1 K", 1_000), ("10 K", 10_000), ("100 K", 100_000),
                ("500 K", 500_000), ("1 M", 1_000_000), ("10 M", 10_000_000),
                ("40 M", 40_000_000), ("80 M", 80_000_000)]

# 通道默认颜色（8 通道循环）
CH_COLORS = ["#00c8ff", "#ffd000", "#00ff8c", "#ff5c5c",
             "#d07cff", "#ff9f40", "#40ffd0", "#ff4fd8"]

# 数学通道默认颜色
DEFAULT_MATH_COLORS = ["#ff8df2", "#8dffb0", "#ffb26b", "#6bb4ff"]

# AC 耦合去直流窗口：以**最近 AC_WIN 点的滑动均值**作为直流电平估计，
# 输出 = 原始值 - 直流估计（只保留 AC 分量）。
# 物理通道与数学通道必须共用同一套算法与常数，保证 M1=ch1 等派生通道
# 在 DC/AC 任意耦合组合下与物理通道波形完全一致（统一框架）。
# 选择滑窗均值而非一阶低通(EMA)：滑窗均值是**纯因果**函数——第 i 点的
# 直流估计只依赖 [i-AC_WIN+1, i] 的历史数据，在线逐点与全量重放天然逐点
# 相等（EMA 则因初值约定不同产生与在线不一致的暂态），且对短记录立即居中，
# 无"大直流逐步恢复"的缓变偏移。
AC_WIN = 10000


def ac_online(win_sum, win_q, sample):
    """在线 AC 耦合单点（O(1)）：维护最近 AC_WIN 点滑窗均值。

    Args:
        win_sum: 当前滑窗内原始值之和（float）。
        win_q: collections.deque，滑窗内原始值（最长 AC_WIN）。
        sample: 当前采样值。

    Returns:
        (coupled, new_sum, new_q)：coupled = sample - 滑窗均值；
        new_sum/new_q 为更新后的滑窗状态（供下次调用传入）。
    """
    sample = float(sample)
    win_q.append(sample)
    win_sum += sample
    if len(win_q) > AC_WIN:
        win_sum -= win_q.popleft()
    mean = win_sum / len(win_q)
    return sample - mean, win_sum, win_q


def ac_replay(raw):
    """重放 AC 耦合（与在线 ac_online 逐点一致），返回耦合数组。

    逐点语义：coupled[i] = raw[i] - mean(raw[max(0, i-AC_WIN+1)..i])，
    与在线滑窗完全一致（同窗口、同纯因果规则）。用 cumsum 向量化，O(n)。
    物理通道切换耦合与数学通道耦合均走本函数，保证两处算法完全相同。
    """
    raw = np.asarray(raw, dtype=float)
    n = int(raw.size)
    if n == 0:
        return raw.copy()
    cs = np.empty(n + 1, dtype=float)
    cs[0] = 0.0
    np.cumsum(raw, out=cs[1:])
    start = np.arange(n, dtype=np.int64) - AC_WIN + 1
    start = np.maximum(start, 0)
    sums = cs[1:] - cs[start]
    counts = np.minimum(np.arange(1, n + 1, dtype=np.int64), AC_WIN)
    return raw - (sums / counts)


def _dedupe_xy(t, y):
    """按 t 严格递增去重（t 相同的点只保留第一个，保证绘图/插值/触发一致）。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if t.size < 2:
        return t, y
    keep = np.empty(t.size, dtype=bool)
    keep[0] = True
    keep[1:] = t[1:] > t[:-1]
    return t[keep], y[keep]


def _fmt_points(n):
    """把点数格式化为人类可读文本（如 100000 -> 100 K）。"""
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:g} M"
    if n >= 1_000:
        return f"{n / 1_000:g} K"
    return str(n)



_CH_TOKEN = re.compile(r"\bch([1-8])\b")


def first_ch_in_expr(expr):
    """返回数学表达式中**第一个引用的物理通道** key（0-7），无则返回 None。

    数学通道默认单位自动跟随表达式第一个出现的通道（如 M1=ch3+ch1
    → 跟随 ch3；M1=ch2+1 → 跟随 ch2；M1=ch1 → 跟随 ch1）。"""
    if not expr:
        return None
    token_match = _CH_TOKEN.search(expr)
    return int(token_match.group(1)) - 1 if token_match else None


def _unit_magnitude(unit):
    """把电压单位解析为量纲倍数（电子学单位制）：V=1, mV=1e-3,
    µV/uV=1e-6, nV=1e-9, kV=1e3, MV=1e6, GV=1e9；解析失败返回 1.0。
    用于数学表达式中多通道单位不一致时统一换算到伏特(V)。"""
    unit_str = (unit or "").strip()
    if not unit_str:
        return 1.0
    unit_str = unit_str.replace("μ", "u").replace("µ", "u")
    if not unit_str.endswith("V") and not unit_str.endswith("v"):
        return 1.0
    pre = unit_str[:-1]
    if pre == "":
        return 1.0
    unit_magnitudes = {"G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
             "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
    return unit_magnitudes.get(pre, unit_magnitudes.get(pre.lower(), 1.0))


class _Buf:
    """真正的环形缓存：O(1) 追加、O(n) 视图读取（读取结果带缓存）。

    旧实现满容后每次 append 都做一次 O(n) 的 `data[drop:]` 前移（约 200k 元素的
    memmove），是高采样率稳态下 GUI 卡顿的元凶。这里改为头/计数环形写入，
    仅在真正绕回时才拼接一次视图，并缓存到下一次 append 前，供一次重绘周期内
    反复读取复用，显著降低 CPU 压力。
    """

    __slots__ = ("data", "head_index", "count", "capacity", "_array")

    def __init__(self, capacity):
        self.capacity = max(16, int(capacity))
        self.data = np.empty(self.capacity, dtype=float)
        self.head_index = 0        # 下一个写入位置
        self.count = 0       # 当前有效元素数（≤ capacity）
        self._array = None     # array() 结果缓存，append 时失效

    def append(self, v):
        self.data[self.head_index] = v
        self.head_index += 1
        if self.head_index == self.capacity:
            self.head_index = 0
        if self.count < self.capacity:
            self.count += 1
        self._array = None

    def _build_array(self):
        if self.count == 0:
            return self.data[:0]
        # 未绕回（head==count）或恰好整圈回正（head==0）：内存本就按时间有序
        if self.head_index == 0 or self.count < self.capacity:
            return self.data[:self.count]
        # 已绕回：时间序 = [head:] + [:head]
        return np.concatenate(
            (self.data[self.head_index:], self.data[:self.head_index]))

    def array(self):
        if self._array is None:
            self._array = self._build_array()
        return self._array

    def last(self):
        if self.count == 0:
            return None
        idx = self.head_index - 1 if self.head_index > 0 else self.capacity - 1
        return self.data[idx]

    def clear(self):
        self.count = 0
        self.head_index = 0
        self._array = None

    def resize(self, capacity):
        """把容量调整为 capacity，保留最近 min(count, capacity) 个样本（先进先出语义）。"""
        capacity = max(16, int(capacity))
        if capacity == self.capacity:
            return
        order = self.array()                # 当前按时间有序的全部数据
        keep = order[-capacity:] if self.count > capacity else order
        self.capacity = capacity
        self.data = np.empty(capacity, dtype=float)
        n = int(keep.size)
        if n:
            self.data[:n] = keep
        self.head_index = n % capacity
        self.count = n
        self._array = None

    def __len__(self):
        return self.count


class DataHub(QObject):
    """串口数据唯一数据源（数据总线 / 邮箱）。

    串口终端解析出的每一帧数据唯一写入本对象；波形 / FFT / 分布图窗口通过
    只读接口获取数据副本，各自独立处理。窗口 / 控件之间通过本对象的公共
    属性与信号通信，互不直接引用。
    """

    data_updated = Signal(int)          # 数据版本变化（新帧写入 / 清屏 / 重算）
    max_points_changed = Signal(int)    # 数据上限变化

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = {}                # ch -> _Buf(时间)
        self._y = {}                # ch -> _Buf(原始电压)
        self._y_coupled = {}               # ch -> _Buf(耦合电压，DC原样/AC去直流)
        self.channels = {}          # ch(int) -> dict(通道配置规格)
        self.maths = {f"m{i + 1}": dict(name=f"M{i + 1}",
                                        color=DEFAULT_MATH_COLORS[i],
                                        expr="", enabled=False, visible=True,
                                        unit="V",
                                        # 数学通道默认单位自动跟随「第一个出现的通道(CH1)」，
                                        # 用户手动修改某数学通道单位后置 False，不再跟随。
                                        unit_auto=True,
                                        v_div=0.05, v_pos=0.0, coupling="dc")
                      for i in range(4)}
        self.version = 0            # 数据版本号，供各窗口判断是否需要重算
        self.t0 = None              # 首个采样时刻，作为 X 轴零点
        self.max_points = MAX_POINTS  # 每通道数据上限（FIFO 环形缓存容量）
        # AC 耦合滑窗均值状态（每通道单一状态，统一框架）。
        # 唯一权威来源：append_frame 在线更新（ac_online）；
        # 切换耦合时由 ac_replay 全量重放，与在线逐点完全一致。
        self._ac_win_sum = {}       # ch -> 滑窗内原始值之和（float）
        self._ac_win_q = {}         # ch -> collections.deque（滑窗内原始值，最长 AC_WIN）
        # 数学通道计算结果（纯 numpy 数组，非 _Buf）
        self._math_t = {}           # "m1" -> np.ndarray（相对时间）
        self._math_y = {}           # "m1" -> np.ndarray（原始表达式结果）
        self._math_y_coupled = {}   # "m1" -> np.ndarray（耦合后结果，DC 原样/AC 去直流）
        self._math_expr_error = {}  # "m1" -> 错误信息字符串
        self._math_sig_cache = None  # 上次计算签名，签名不变则复用结果
        # 数组缓存：避免一帧内对同一通道反复做 list->ndarray 全量转换

    # ------------------------------------------------------------- 数据写入（唯一入口）
    def append_frame(self, t, vals):
        """唯一写入入口：由串口终端调用，写入一帧 {通道序号: 数值}。"""
        if not vals or not math.isfinite(t):
            return
        if self.t0 is None:
            self.t0 = t
        self._ensure_data_dicts()
        rel = float(t) - self.t0
        for ch, v in vals.items():
            if ch not in self.channels:
                continue
            try:
                float_val = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(float_val):
                continue
            self._t[ch].append(rel)
            self._y[ch].append(float_val)
            # 统一耦合框架：AC 耦合 = 原始值 - 最近 AC_WIN 点滑窗均值
            # （纯因果，在线 ac_online 与重放 ac_replay 逐点一致）；
            # DC 耦合原样传入，不更新滑窗状态。
            if self.channels[ch].get("coupling") == "ac":
                win_sum = self._ac_win_sum.get(ch, 0.0)
                win_q = self._ac_win_q.setdefault(ch, deque())
                coupled, win_sum, win_q = ac_online(win_sum, win_q, float_val)
                self._y_coupled[ch].append(coupled)
                self._ac_win_sum[ch] = win_sum
            else:
                self._y_coupled[ch].append(float_val)
        self.version += 1
        self.data_updated.emit(self.version)

    def bulk_add(self, frames):
        """批量写入多帧（格式变化后按新格式重新解析历史数据用）。"""
        if not frames:
            return
        self._ensure_data_dicts()
        t0 = self.t0
        for t, vals in frames:
            if not vals or not math.isfinite(t):
                continue
            if t0 is None:
                t0 = t
            rel = float(t) - t0
            for ch, v in vals.items():
                if ch not in self.channels:
                    continue
                try:
                    float_val = float(v)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(float_val):
                    continue
                self._t[ch].append(rel)
                self._y[ch].append(float_val)
                if self.channels[ch].get("coupling") == "ac":
                    win_sum = self._ac_win_sum.get(ch, 0.0)
                    win_q = self._ac_win_q.setdefault(ch, deque())
                    (coupled, win_sum, win_q) = ac_online(
                        win_sum, win_q, float_val)
                    self._y_coupled[ch].append(coupled)
                    self._ac_win_sum[ch] = win_sum
                else:
                    self._y_coupled[ch].append(float_val)
        self.t0 = t0
        self.version += 1
        self.data_updated.emit(self.version)

    def clear_data(self):
        """清空所有数据缓冲（清屏 / 格式变更时调用）。

        清屏时**清空** AC 耦合滑窗状态（_ac_win_sum/_ac_win_q），
        新数据到来后从空窗重新建立滑窗均值；在线与重放（ac_replay）逐点
        一致，清屏后任意时刻 M1=ch1(AC) 与 ch1(AC) 波形完全一致。
        """
        for ch in list(self.channels):
            self._t[ch] = _Buf(self.max_points)
            self._y[ch] = _Buf(self.max_points)
            self._y_coupled[ch] = _Buf(self.max_points)
            self._ac_win_sum.pop(ch, None)
            self._ac_win_q.pop(ch, None)
        self.t0 = None
        self._math_t.clear()
        self._math_y.clear()
        self._math_y_coupled.clear()
        self._math_expr_error.clear()
        self.version += 1
        self.data_updated.emit(self.version)

    def setup_channels(self, n):
        """按通道数重建数据缓冲与通道配置（不包含 UI 重建）。

        容器用 clear() 清空而非重新赋值，保持 dict 引用稳定，
        以便 WaveformPanel 等消费方以引用方式共享（单一数据源、零魔法）。
        """
        self.version += 1
        self.channels.clear()
        self._ac_win_sum.clear()
        self._ac_win_q.clear()
        for i in range(max(0, int(n))):
            color = CH_COLORS[i % len(CH_COLORS)]
            self.channels[i] = dict(name=f"ch{i + 1}", color=color, enabled=True,
                                    v_div=0.05, v_pos=0.0,   # 默认50mV/div方便观察mV级信号(原1V/div)
                                    coupling="dc", unit="V")
        self._t.clear()
        self._y.clear()
        self._y_coupled.clear()
        for i in self.channels:
            self._t[i] = _Buf(self.max_points)
            self._y[i] = _Buf(self.max_points)
            self._y_coupled[i] = _Buf(self.max_points)
        self.t0 = None
        self._math_t.clear()
        self._math_y.clear()
        self._math_y_coupled.clear()
        self._math_expr_error.clear()
        self._math_sig_cache = None
        self.version += 1
        self.data_updated.emit(self.version)

    def _ensure_data_dicts(self):
        for ch in self.channels:
            self._t.setdefault(ch, _Buf(self.max_points))
            self._y.setdefault(ch, _Buf(self.max_points))
            self._y_coupled.setdefault(ch, _Buf(self.max_points))
            self._ac_win_sum.setdefault(ch, 0.0)
            self._ac_win_q.setdefault(ch, deque())

    def set_max_points(self, value):
        """把每通道 FIFO 容量调整为 value（夹紧到安全区间），先进先出保留最近数据。

        供波形 / FFT / 分布图等窗口同步数据上限时调用；改变后即时重建环形缓存
        并通知关联面板。
        """
        value = max(MIN_POINT_LIMIT, min(MAX_POINT_LIMIT, int(value)))
        need_rebuffer = value != self.max_points
        self.max_points = value
        if need_rebuffer:
            all_bufs = (list(self._t.values()) + list(self._y.values())
                        + list(self._y_coupled.values()))
            for ring_buf in all_bufs:
                if isinstance(ring_buf, _Buf):
                    ring_buf.resize(value)
            self.version += 1
            # 通知所有窗口及时按新上限刷新（数据语义已变化）
            self.data_updated.emit(self.version)
        self.max_points_changed.emit(value)

    # ------------------------------------------------------------- 耦合数据层



    def _recouple_channel(self, ch, notify=True):
        """重新计算单个通道的耦合数据（切换耦合模式时调用）。

        物理通道与数学通道共用同一重放算法 ac_replay（滑窗均值去直流），
        保证任意 DC/AC 组合下派生通道与物理通道波形完全一致（统一框架）：
        - DC 耦合：耦合数据 = 原始数据（原样拷贝），不清空滑窗状态；
        - AC 耦合：耦合数据 = 原始数据 - 最近 AC_WIN 点滑窗均值（纯因果，
          与在线 ac_online 逐点一致）。重放后用历史尾部重建在线滑窗状态，
          后续新帧从相同状态继续，无缝衔接。
        """
        if self._is_math(ch):
            raw = self._math_y.get(ch)
            if raw is None or len(raw) == 0:
                return
            raw = np.asarray(raw, dtype=float)
            if self.maths[ch].get("coupling", "dc") == "ac" and raw.size > 0:
                new_y = ac_replay(raw)
            else:
                new_y = raw.copy()
            self._math_y_coupled[ch] = new_y
            self.version += 1
            self._math_sig_cache = None
            if notify:
                self.data_updated.emit(self.version)
            return
        if ch not in self.channels:
            return
        raw = self._y[ch].array()
        n = int(raw.size)
        new_buf = _Buf(self.max_points)
        is_ac = self.channels[ch].get("coupling") == "ac"
        if is_ac and n > 0:
            new_y = ac_replay(raw)
            # 重建在线滑窗状态：以历史尾部（最近 AC_WIN 点）填充，使后续
            # append_frame 从与重放一致的滑窗均值继续（无缝衔接、无跳变）。
            self._rebuild_ac_win(ch, raw)
        else:
            new_y = raw.copy()
        if n:
            new_buf.data[:n] = new_y
            new_buf.count = n
            new_buf.head_index = n % self.max_points
            new_buf._array = new_y
        self._y_coupled[ch] = new_buf
        # 耦合数据变化 → 递增版本并使数学通道/数组缓存失效，
        # 否则物理通道切 AC/DC 后数学通道仍显示旧耦合数据（跨页面联动 bug）
        self.version += 1
        self._math_sig_cache = None
        # 通知各窗口（波形/FFT/分布）耦合数据已变化，及时刷新；
        # _recouple_all 批量调用时由外层统一通知一次，避免 N 通道 N 次刷新
        if notify:
            self.data_updated.emit(self.version)

    def _rebuild_ac_win(self, ch, raw):
        """用原始数据尾部重建通道 ch 的在线滑窗状态（最近 AC_WIN 点）。"""
        raw = np.asarray(raw, dtype=float)
        tail = raw[-AC_WIN:] if raw.size > 0 else raw
        win_q = deque()
        win_sum = 0.0
        for v in tail:
            win_q.append(float(v))
            win_sum += float(v)
        self._ac_win_q[ch] = win_q
        self._ac_win_sum[ch] = win_sum

    def _recouple_all(self):
        """重新计算所有通道的耦合数据。"""
        for ch in self.channels:
            self._recouple_channel(ch, notify=False)
        self._math_sig_cache = None
        self.version += 1
        self.data_updated.emit(self.version)

    # ------------------------------------------------------------- 只读接口
    def _is_math(self, ch):
        return isinstance(ch, str) and ch in self.maths

    def _spec_of(self, ch):
        """统一取通道显示规格：模拟通道 ch(int) 或数学通道 key(str)。"""
        if isinstance(ch, str) and ch in self.maths:
            return self.maths[ch]
        return self.channels.get(ch)

    def get_arrays(self, ch):
        """返回原始数据只读视图（t, y）。返回数组被设为只读，
        任何误写都会立即抛异常而非静默污染内部环形缓存
        （修复：FFT/分布图等消费方若原地修改视图会污染其它窗口数据）。
        """
        empty = np.empty(0, dtype=float)
        if self._is_math(ch):
            t = self._math_t.get(ch)
            y = self._math_y.get(ch)
            if t is None or y is None or len(t) == 0:
                return empty, empty
            t = np.asarray(t, dtype=float)
            y = np.asarray(y, dtype=float)
        else:
            t_buf = self._t.get(ch)
            y_buf = self._y.get(ch)
            if t_buf is None or y_buf is None or t_buf.count == 0:
                return empty, empty
            t = t_buf.array()
            y = y_buf.array()
        for arr in (t, y):
            if arr.flags.writeable:
                arr.setflags(write=False)
        return t, y

    def get_coupled_arrays(self, ch):
        """获取耦合后的数据副本（DC 原样 / AC 去直流），所有功能的统一数据源。

        物理通道返回 _y_coupled（append_frame 在线计算 / 切换耦合时重放）；
        数学通道返回 _math_y_coupled（compute_math 计算原始结果后按自身耦合
        用与物理通道完全相同的 ac_replay 处理，保证 DC/AC 任意组合下
        与物理通道波形一致）。
        【数据安全】返回数组的副本，避免外部修改（如 FFT 大点数计算、数学通道
        插值）污染 _Buf 内部缓存，导致分布图 / 测量等其他功能读到损坏数据。
        """
        if self._is_math(ch):
            t = self._math_t.get(ch)
            y = self._math_y_coupled.get(ch)
            if t is None or y is None or len(t) == 0:
                empty = np.empty(0, dtype=float)
                return empty.copy(), empty.copy()
            return (np.array(t, dtype=float, copy=True),
                    np.array(y, dtype=float, copy=True))
        t_buf = self._t.get(ch)
        y_buf = self._y_coupled.get(ch)
        if t_buf is None or y_buf is None or t_buf.count == 0:
            empty = np.empty(0, dtype=float)
            return empty.copy(), empty.copy()
        return (np.array(t_buf.array(), dtype=float, copy=True),
                np.array(y_buf.array(), dtype=float, copy=True))

    def get_coupled_window(self, ch, t_lo, t_hi):
        """获取耦合数据在 [t_lo, t_hi] 时间窗口内的副本。

        用二分查找定位窗口边界，只复制窗口内点，替代整条 FIFO 全量复制，
        避免大数据缓存（最高 80M 点/通道）下波形绘制每帧复制 1GB+ 峰值。

        显示语义：波形绘制要求采样点连线延伸到屏幕左/右边缘（真实示波器
        行为，避免窗口边界落在两采样点之间时屏幕内侧出现无数据缺口），
        因此在窗口两侧各延伸一个采样点（存在时）。时基越小 / 采样率越低时
        窗口内点数越少，此延伸对「左半边显示不全」的修复越关键。
        """
        empty = np.empty(0, dtype=float)
        if self._is_math(ch):
            t, y = self.get_coupled_arrays(ch)
            if len(t) == 0:
                return empty, empty
            lo = int(np.searchsorted(t, t_lo, side="left"))
            hi = int(np.searchsorted(t, t_hi, side="right"))
            lo = max(0, lo - 1)
            hi = min(len(t), hi + 1)
            return (np.array(t[lo:hi], dtype=float, copy=True),
                np.array(y[lo:hi], dtype=float, copy=True))
        t_buf = self._t.get(ch)
        y_buf = self._y_coupled.get(ch)
        if t_buf is None or y_buf is None or t_buf.count == 0:
            return empty, empty
        t = t_buf.array()
        y = y_buf.array()
        lo = int(np.searchsorted(t, t_lo, side="left"))
        hi = int(np.searchsorted(t, t_hi, side="right"))
        lo = max(0, lo - 1)
        hi = min(len(t), hi + 1)
        return (np.array(t[lo:hi], dtype=float, copy=True),
                np.array(y[lo:hi], dtype=float, copy=True))

    def get_coupled_tail(self, ch, n):
        """获取耦合数据**最近 n 点**的副本（含去重语义：仅截取尾部）。

        适用场景：FFT / 分布图等只需要最近一段数据的消费方。
        若用 get_coupled_arrays 会把整条 FIFO 缓存（上限可达 80M 点/通道 ≈ 1.3GB）
        全量复制，FFT 大点数或大数据缓存下会造成主线程内存暴涨与卡顿，
        连带其它窗口（分布图）刷新异常（表现为读数异常/变 0）。
        这里只复制尾部 n 点，内存开销与 n 线性相关、与缓存总量无关。
        """
        if self._is_math(ch):
            t, y = self.get_coupled_arrays(ch)
            n = max(1, int(n))
            if t.size > n:
                return (np.array(t[-n:], dtype=float, copy=True),
                        np.array(y[-n:], dtype=float, copy=True))
            return t, y
        t_buf = self._t.get(ch)
        y_buf = self._y_coupled.get(ch)
        if t_buf is None or y_buf is None or t_buf.count == 0:
            empty = np.empty(0, dtype=float)
            return empty, empty
        n = max(1, int(n))
        t = t_buf.array()
        y = y_buf.array()
        if t.size <= n:
            return (np.array(t,
                dtype=float, copy=True), np.array(y, dtype=float, copy=True))
        return (np.array(t[-n:], dtype=float, copy=True),
                np.array(y[-n:], dtype=float, copy=True))

    # ------------------------------------------------------------- 数学通道
    def _clear_math_computed(self):
        """清空全部数学通道计算结果缓冲（含已禁用通道）。

        BUG-T 修复：此前仅清空启用通道的缓冲，被禁用的数学通道旧结果残留，
        导致数据层仍返回已禁用通道的过期数据（与 UI 隐藏不同步）。compute_math
        在重算前调用本方法，随后只重算启用通道，禁用通道自然保持为空。
        """
        for key in list(self._math_t.keys()):
            self._math_t.pop(key, None)
            self._math_y.pop(key, None)
            self._math_y_coupled.pop(key, None)

    def compute_math(self):
        """把启用且表达式合法的数学通道计算为独立数组（含耦合处理）。

        以第一个启用模拟通道去重后的时间轴为基准，把其它模拟通道线性插值到该
        网格后向量化求值，原始结果写入 ``_math_t/_math_y``；随后按各数学通道
        自身耦合用 ac_replay 处理写入 ``_math_y_coupled``（DC 原样 /
        AC 去直流，算法与物理通道完全一致）。表达式未变且数据版本未变时复用
        缓存，避免重复插值 / 求值开销；数学通道耦合纳入签名，切换耦合即重算。

        Returns:
            None（结果写入内部状态 _math_t/_math_y/_math_y_coupled，
            供 get_coupled_arrays 读取）。
        """
        # unit_auto 的数学通道，默认单位 = 表达式第一个引用通道的单位。
        for key, spec in self.maths.items():
            if spec.get("unit_auto", True) and spec.get("expr"):
                first_ch = first_ch_in_expr(spec["expr"])
                if first_ch is not None and first_ch in self.channels:
                    spec["unit"] = self.channels[first_ch].get("unit", "V")
        sig = (self.version,
               tuple((ch, info["enabled"], info.get("unit", "V"),
                      info.get("coupling", "dc")) for ch, info in self.channels.items()),
               tuple((k, s["enabled"], s["expr"], s.get("unit", "V"),
                      s.get("coupling", "dc")) for k, s in self.maths.items()))
        if sig == self._math_sig_cache:
            return
        self._math_sig_cache = sig
        # 表达式 / 数据版本变化：清除历史表达式错误，允许修正后重试
        self._math_expr_error.clear()
        ref = None
        for ch, info in self.channels.items():
            if info["enabled"]:
                t, y = self.get_coupled_arrays(ch)
                t, y = _dedupe_xy(t, y)
                if len(t) >= 2:
                    ref = t
                    break
        self._clear_math_computed()
        if ref is None:
            return
        variables = {}
        for ch, info in self.channels.items():
            if not info["enabled"]:
                continue
            t, y = self.get_coupled_arrays(ch)
            t, y = _dedupe_xy(t, y)
            if len(t) < 2:
                continue
            # 数学表达式中所有通道数据统一换算到伏特(V)，
            # 确保不同单位通道运算结果正确（如 ch1[V] + ch2[mV] = ch1 + ch2*0.001）。
            # 数学通道结果恒以 V 为单位，用户可在通道面板修改显示单位。
            magnitude = _unit_magnitude(info.get("unit", "V"))
            y_v = y * magnitude
            variables[f"ch{ch + 1}"] = (y_v if (len(t) == len(ref)
                                               and np.allclose(t, ref))
                                        else np.interp(ref, t, y_v))
        for key, spec in self.maths.items():
            if not spec["enabled"] or not spec["expr"]:
                continue
            if key in self._math_expr_error:
                continue
            try:
                res = math_eval(spec["expr"], variables)
            except (ValueError, ZeroDivisionError, TypeError):  # noqa: BLE001
                self._math_expr_error[key] = "eval"
                continue
            if isinstance(res, np.ndarray):
                arr = res.astype(float, copy=False)
            else:
                arr = float(res)
            if np.isscalar(arr):
                arr = np.full(len(ref), float(arr))
            if arr.shape != ref.shape:
                if arr.size == ref.size:
                    arr = arr.reshape(ref.shape)
                else:
                    continue
            # 数学结果须为有限数值：除零 / 溢出 / NaN 等非有限结果按表达式错误
            # 处理并跳过（此前 numpy 对除零静默返回 inf，波形显示为无效直线）。
            if not np.all(np.isfinite(arr)):
                self._math_expr_error[key] = "non_finite"
                continue
            # 数学运算结果恒为 V（variables 已统一换算），
            # 根据数学通道自身单位转换为通道单位值存储（与物理通道完全一致）。
            # 如通道单位 mV：arr(V) / 1e-3 = arr*1000 (mV)。
            math_mag = _unit_magnitude(spec.get("unit", "V"))
            if math_mag > 0:
                arr = arr / math_mag
            self._math_t[key] = ref
            self._math_y[key] = arr
            # 数学通道耦合（统一框架）：与物理通道共用 ac_replay（滑窗均值
            # 去直流），DC 原样；保证 M1=ch1(AC) 与 ch1(AC) 波形完全一致。
            if spec.get("coupling", "dc") == "ac" and arr.size > 0:
                self._math_y_coupled[key] = ac_replay(arr)
            else:
                self._math_y_coupled[key] = arr
