# -*- coding: utf-8 -*-
"""纯 NumPy 实现的数字滤波器（无需 SciPy，保持「仅 4 个依赖」）。

参照 Keysight / Tektronix 示波器数学通道的滤波运算（低通 / 高通 / 带通 / 带阻），
用 **巴特沃斯（Butterworth，最大平坦）** 原型 + 双线性变换设计 IIR 滤波器，
阶数默认为 2（带宽过渡区与计算开销的折中）。

设计要点：
- 截止频率统一按 **归一化频率** 给出：``fc ∈ (0, 1)``，其中 ``1.0`` 对应奈奎斯特
  频率（采样率的一半）。例如采样率 1000 S/s 时，奈奎斯特为 500 Hz，
  想要 100 Hz 低通即传 ``fc = 100/500 = 0.2``。
- 滤波采用转置直接 II 型结构，数值稳定；带通采用「低通串联高通」，带阻采用
  「低通与高通并联（原信号减带通）」，均为标准的四阶（2+2）级联实现。
"""

from __future__ import annotations

import math

import numpy as np


def _butterworth_poles(order):
    """巴特沃斯模拟原型极点：均匀分布在 s 平面左半单位圆上（负实部）。"""
    order = int(order)
    angles = np.pi / 2.0 + np.pi / (2.0 * order) + np.arange(order) * np.pi / order
    return np.exp(1j * angles)


def _bilinear_lowpass(order, wn):
    """低通：截止 wn（归一化）的巴特沃斯 IIR 系数 (b, a)。"""
    order = int(order)
    if not 0.0 < wn < 1.0:
        raise ValueError(f"截止频率必须位于 (0, 1)，收到 {wn!r}")
    omega_c = 2.0 * math.tan(math.pi * wn / 2.0)         # 双线性变换预畸变（fs=2 约定）
    poles = _butterworth_poles(order) * omega_c
    digital_poles = (2.0 + poles) / (2.0 - poles)              # 模拟极点 -> 数字极点
    gain = (omega_c ** order) / float(np.prod(2.0 - poles).real)
    # 分子 (1 + z^-1)^N，系数恰为 (z + 1)^N 的降幂排列
    b = (gain * np.poly(np.full(order, -1.0))).real
    a = np.poly(digital_poles).real
    return b, a


def _bilinear_highpass(order, wn):
    """高通：截止 wn（归一化）的巴特沃斯 IIR 系数 (b, a)。"""
    order = int(order)
    if not 0.0 < wn < 1.0:
        raise ValueError(f"截止频率必须位于 (0, 1)，收到 {wn!r}")
    omega_c = 2.0 * math.tan(math.pi * wn / 2.0)
    poles = _butterworth_poles(order) * omega_c
    digital_poles = (2.0 + poles) / (2.0 - poles)
    gain = (2.0 ** order) / float(np.prod(2.0 - poles).real)
    # 分子 (1 - z^-1)^N，系数恰为 (z - 1)^N 的降幂排列
    b = (gain * np.poly(np.full(order, 1.0))).real
    a = np.poly(digital_poles).real
    return b, a


def lfilter(b, a, x):
    """转置直接 II 型 IIR 滤波（等价于 scipy.signal.lfilter 的单段实现）。

    对任意阶数可用，但调用方通常传入阶数 ≤ 4 的系数，稳定且足够快。
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    x = np.asarray(x, dtype=float)
    if a.size == 0 or a[0] == 0.0:
        raise ValueError("a[0] 不能为 0")
    a0 = float(a[0])
    a = a / a0
    b = b / a0
    n = int(a.size) - 1                        # 滤波器阶数（差分方程反馈长度 - 1）
    if b.size < n + 1:
        b = np.pad(b, (0, n + 1 - b.size))
    z = np.zeros(n, dtype=float)               # 延迟线状态
    y = np.empty(x.size, dtype=float)
    for i in range(x.size):
        x_sample = x[i]
        y_sample = b[0] * x_sample + z[0]
        y[i] = y_sample
        for j in range(n - 1):
            z[j] = b[j + 1] * x_sample - a[j + 1] * y_sample + z[j + 1]
        z[n - 1] = b[n] * x_sample - a[n] * y_sample
    return y


def lowpass(x, wn, order=2):
    """低通滤波：保留 0~wn（归一化）以下频率成分。"""
    b, a = _bilinear_lowpass(order, wn)
    return lfilter(b, a, np.asarray(x, dtype=float))


def highpass(x, wn, order=2):
    """高通滤波：保留 wn（归一化）以上频率成分。"""
    b, a = _bilinear_highpass(order, wn)
    return lfilter(b, a, np.asarray(x, dtype=float))


def bandpass(x, w0, bw, order=2):
    """带通滤波：保留以 w0（归一化中心）为中心、bw 为带宽的频带。

    实现为「低通(w0+bw/2) 串联 高通(w0-bw/2)」，即标准 2+2 阶级联带通。
    """
    lo = w0 - bw / 2.0
    hi = w0 + bw / 2.0
    if not 0.0 < lo < hi < 1.0:
        raise ValueError(f"带通频带需满足 0 < " f"{w0 - bw / 2.0:.4g} < "
                         f"{w0 + bw / 2.0:.4g} < 1")
    y = np.asarray(x, dtype=float)
    y = lowpass(y, hi, order)
    y = highpass(y, lo, order)
    return y


def bandstop(x, w0, bw, order=2):
    """带阻滤波（陷波）：抑制以 w0（归一化中心）为中心的频带。

    实现为「低通(w0-bw/2) 与 高通(w0+bw/2) 并联」，即原信号经带通后反相叠加。
    """
    lo = w0 - bw / 2.0
    hi = w0 + bw / 2.0
    if not 0.0 < lo < hi < 1.0:
        raise ValueError(f"带阻频带需满足 0 < " f"{w0 - bw / 2.0:.4g} < "
                         f"{w0 + bw / 2.0:.4g} < 1")
    y = np.asarray(x, dtype=float)
    return y - bandpass(y, w0, bw, order)