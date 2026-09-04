# -*- coding: utf-8 -*-
"""安全数学表达式求值器（自研，供 Math 通道的自定义表达式使用）。

设计要点：
- 绝不使用 ``eval``/``exec``：先做词法分析，再经「调度场算法」转换为逆波兰式（RPN），
  最后用 numpy 向量化计算，既能对大数组高效求值，也从根本上杜绝代码注入。
- 支持：四则运算 + - * /、乘方 ^、括号、一元负号；函数 abs/sqrt/log/ln/lg/exp/
  sin/cos/tan/pow/min/max；逻辑运算 not/and/or/xor（按 0 阈值二值化）；微积分
  diff（微分）/integ(integral)（积分，单位采样间隔）；数字滤波 lowpass/highpass
  （2 参：信号、归一化截止频率）/bandpass/bandstop（3 参：信号、归一化中心频率、
  归一化带宽）；常量 pi、e；通道变量 ch1..chN（含 0 前缀，如 ch01）。
- 变量为 numpy 数组或标量，运算结果与输入最长数组等长（自动广播）。
"""

from __future__ import annotations

import math
import re

import numpy as np

from .digital_filters import (
    lowpass as _f_lowpass,
    highpass as _f_highpass,
    bandpass as _f_bandpass,
    bandstop as _f_bandstop,
)


def _logic_not(a):
    """逻辑非：按 0 阈值二值化后取反，输出 0/1。"""
    return (~(np.asarray(a, dtype=float) > 0)).astype(float)


def _logic_and(a, b):
    return ((np.asarray(a, dtype=float) > 0) & (np.asarray(b, dtype=float) > 0)).astype(float)


def _logic_or(a, b):
    return ((np.asarray(a, dtype=float) > 0) | (np.asarray(b, dtype=float) > 0)).astype(float)


def _logic_xor(a, b):
    return ((np.asarray(a, dtype=float) > 0) ^ (np.asarray(b, dtype=float) > 0)).astype(float)


def _diff(a):
    """微分（单位采样间隔）：np.gradient 保长，避免返回长度错位。"""
    a = np.asarray(a, dtype=float)
    if a.ndim == 0 or a.size < 2:
        return np.zeros_like(a)
    return np.gradient(a)


def _integ(a):
    """积分（单位采样间隔的累加和）：保持与输入等长。"""
    a = np.asarray(a, dtype=float)
    if a.ndim == 0:
        return a
    return np.cumsum(a)


def _lowpass(x, wn):
    """低通滤波：x 为信号，wn 为归一化截止频率 (0, 1)。"""
    return _f_lowpass(np.asarray(x, dtype=float), float(wn))


def _highpass(x, wn):
    """高通滤波：x 为信号，wn 为归一化截止频率 (0, 1)。"""
    return _f_highpass(np.asarray(x, dtype=float), float(wn))


def _bandpass(x, w0, bw):
    """带通滤波：x 为信号，w0 为中心频率，bw 为带宽（均为归一化频率）。"""
    return _f_bandpass(np.asarray(x, dtype=float), float(w0), float(bw))


def _bandstop(x, w0, bw):
    """带阻滤波（陷波）：x 为信号，w0 为中心频率，bw 为带宽（均为归一化频率）。"""
    return _f_bandstop(np.asarray(x, dtype=float), float(w0), float(bw))


# 内置函数：名称 -> 计算函数（1 参 / 2 参 / 3 参三组）
_FUNCS_1 = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    # BUG-11 修复：log 保持十进制对数（向后兼容），新增 loge/log10 明确语义，
    # 避免与 C/Python/MATLAB 中 log=自然对数的惯例混淆。自然对数用 ln 或 loge。
    "log": np.log10,
    "lg": np.log10,
    "log10": np.log10,
    "ln": np.log,
    "loge": np.log,
    "exp": np.exp,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "not": _logic_not,
    "diff": _diff,
    "integ": _integ,
    "integral": _integ,
}
_FUNCS_2 = {
    "pow": np.power,
    "min": np.minimum,
    "max": np.maximum,
    "and": _logic_and,
    "or": _logic_or,
    "xor": _logic_xor,
    # 滤波（截止频率为归一化频率 0~1，1 = 奈奎斯特）
    "lowpass": _lowpass,
    "highpass": _highpass,
}
_FUNCS_3 = {
    "bandpass": _bandpass,
    "bandstop": _bandstop,
}

_CONSTANTS = {"pi": math.pi, "e": math.e}

_NUMBER_RE = re.compile(r"\d+\.?\d*([eE][-+]?\d+)?|\.\d+([eE][-+]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 通道变量：ch1..chN 或 ch01..chNN（通道号从 1 起）
_CH_RE = re.compile(r"^ch(\d{1,3})$")


def _tokenize(expr: str):
    """词法分析：返回 token 序列。一元负号输入时折叠为 '-' 的「一元」token。"""
    tokens = []
    i, n = 0, len(expr)
    prev_is_operand = False   # 上一个 token 是否可作为操作数（用于区分一元/二元减号）
    while i < n:
        ch = expr[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            m = _NUMBER_RE.match(expr, i)
            if not m:
                raise ValueError(f"非法数字开头：{expr[i:]!r}")
            tokens.append(("num", float(m.group())))
            i = m.end()
            prev_is_operand = True
            continue
        if ch.isalpha() or ch == "_":
            m = _IDENT_RE.match(expr, i)
            name = m.group()
            i = m.end()
            # 函数名（后跟左括号）视为函数，否则视为变量 / 常量
            func_match = (name in _FUNCS_1 or name in _FUNCS_2
                          or name in _FUNCS_3)
            if i < n and expr[i] == "(" and func_match:
                tokens.append(("func", name))
                prev_is_operand = False
            elif name in _CONSTANTS:
                tokens.append(("num", _CONSTANTS[name]))
                prev_is_operand = True
            else:
                if not _CH_RE.match(name):
                    raise ValueError(f"未知变量：{name!r}")
                tokens.append(("var", name))
                prev_is_operand = True
            continue
        if ch == "+":
            # 一元正号等价无操作（+ch1 ≡ ch1）：操作数位置之后才是二元加号；
            # 一元位置的 + 直接跳过，避免被误判为缺操作数的二元加号（BUG-R 关联）
            if prev_is_operand:
                tokens.append(("op", "+"))
                prev_is_operand = False
            i += 1
            continue
        if ch == "-":
            if not prev_is_operand:
                tokens.append(("op", "u-"))      # 一元负号
            else:
                tokens.append(("op", "-"))
            i += 1
            prev_is_operand = False
            continue
        if ch in "*/^":
            tokens.append(("op", ch))
            i += 1
            prev_is_operand = False
            continue
        if ch == "(":
            tokens.append(("lp",))
            i += 1
            prev_is_operand = False
            continue
        if ch == ")":
            tokens.append(("rp",))
            i += 1
            prev_is_operand = True
            continue
        if ch == ",":
            tokens.append(("comma",))
            i += 1
            continue
        raise ValueError(f"非法字符：{ch!r}")
    return tokens


# 运算符优先级与结合性（数值越高越先计算）
_PREC = {"u-": 4, "^": 3, "*": 2, "/": 2, "+": 1, "-": 1}
_RIGHT_ASSOC = {"^"}


def _to_rpn(tokens):
    """调度场算法：中缀 token 序列 -> 逆波兰式。"""
    out = []
    stack = []
    for token in tokens:
        kind = token[0]
        if kind in ("num", "var"):
            out.append(token)
        elif kind == "func":
            stack.append(token)
        elif kind == "comma":
            # 弹出直到最近的左括号（函数参数分隔）
            while stack and stack[-1][0] != "lp":
                out.append(stack.pop())
            if not stack:
                raise ValueError("逗号位置错误")
        elif kind == "op":
            prec = _PREC[token[1]]
            while stack and stack[-1][0] == "op":
                top_prec = _PREC[stack[-1][1]]
                if (top_prec > prec) or (top_prec == prec and token[1] not in _RIGHT_ASSOC):
                    out.append(stack.pop())
                else:
                    break
            stack.append(token)
        elif kind == "lp":
            # 记录左括号入栈时的 out 长度，用于精确判定该括号组是否「空括号」：
            # 不能以 rp 时刻的 out 长度判定（单操作数括号如 (ch1)/(1) 会误报）。
            stack.append(("lp", len(out)))
        elif kind == "rp":
            while stack and stack[-1][0] != "lp":
                out.append(stack.pop())
            if not stack:
                raise ValueError("括号不匹配：缺少左括号")
            group_start = stack.pop()[1]
            if stack and stack[-1][0] == "func":
                out.append(stack.pop())
            elif len(out) == group_start:
                # 括号组内未产生任何操作数（如 "()"）无计算意义，必须拦截，
                # 保证校验（validate）与求值（evaluate）语义一致。
                raise ValueError("空括号不合法")
        else:
            raise ValueError(f"未知 token：{token!r}")
    while stack:
        top = stack.pop()
        if top[0] == "lp":
            raise ValueError("括号不匹配：缺少右括号")
        out.append(top)
    return out


# RPN 各 token 需要的操作数/参数个数（与 evaluate 求值语义一致）
_RPN_ARITY = {"u-": 1, "+": 2, "-": 2, "*": 2, "/": 2, "^": 2}
_RPN_ARITY.update({name: 1 for name in _FUNCS_1})
_RPN_ARITY.update({name: 2 for name in _FUNCS_2})
_RPN_ARITY.update({name: 3 for name in _FUNCS_3})


def _check_rpn(rpn):
    """静态校验 RPN 的操作数/参数数量是否合法（与 evaluate 求值语义一致）。
    BUG-R：validate 此前仅做 _to_rpn 语法检查，尾部运算符/缺运算符/多余操作数
    等「evaluate 必抛」的非法表达式会被误放行，造成校验与计算不一致。"""
    depth = 0
    for token in rpn:
        kind = token[0]
        if kind in ("num", "var"):
            depth += 1
        elif kind == "op":
            need = _RPN_ARITY[token[1]]
            if depth < need:
                raise ValueError("运算符缺少操作数")
            depth = depth - need + 1
        elif kind == "func":
            need = _RPN_ARITY[token[1]]
            if depth < need:
                raise ValueError(f"{token[1]} 缺少参数")
            depth = depth - need + 1
        else:
            raise ValueError(f"未知 RPN token：{token!r}")
    if depth != 1:
        raise ValueError("表达式存在多余操作数")


def _as_array(v):
    """把标量/数组统一为 float 数组；标量保持标量以支持广播。"""
    if isinstance(v, np.ndarray):
        return v.astype(float, copy=False)
    return float(v)


def evaluate(expr: str, env: dict) -> np.ndarray:
    """在给定环境下求值表达式，返回 numpy 数组（或标量）。

    :param expr: 数学表达式，如 "ch1 + ch2 * 0.5"、"sin(ch1)*3 + 1"。
    :param env: 变量映射，如 {"ch1": array, "ch2": array}；键为 "ch1".."chN"。
    :raises ValueError: 表达式非法 / 变量缺失 / 除零等。
    """
    if expr is None:
        raise ValueError("表达式为空")
    expr = str(expr).strip()
    if not expr:
        raise ValueError("表达式为空")
    tokens = _tokenize(expr)
    rpn = _to_rpn(tokens)
    stack: list = []
    for token in rpn:
        kind = token[0]
        if kind == "num":
            stack.append(token[1])
        elif kind == "var":
            if token[1] not in env:
                raise ValueError(f"变量缺失：{token[1]!r}")
            stack.append(env[token[1]])
        elif kind == "op":
            if len(stack) < (1 if token[1] == "u-" else 2):
                raise ValueError("运算符缺少操作数")
            if token[1] == "u-":
                a = _as_array(stack.pop())
                stack.append(-a)
            else:
                b = _as_array(stack.pop())
                a = _as_array(stack.pop())
                if token[1] == "+":
                    stack.append(a + b)
                elif token[1] == "-":
                    stack.append(a - b)
                elif token[1] == "*":
                    stack.append(a * b)
                elif token[1] == "/":
                    # 除零/无效运算：静默置为 inf/NaN，由 DataHub.compute_math
                    # 的非有限值防护捕获并标记表达式错误（不向终端抛警告）。
                    with np.errstate(divide="ignore", invalid="ignore"):
                        stack.append(a / b)
                elif token[1] == "^":
                    stack.append(np.power(a, b))
                else:
                    raise ValueError(f"未知运算符：{token[1]}")
        elif kind == "func":
            name = token[1]
            if name in _FUNCS_1:
                if not stack:
                    raise ValueError(f"{name} 缺少参数")
                stack.append(_FUNCS_1[name](_as_array(stack.pop())))
            elif name in _FUNCS_2:
                if len(stack) < 2:
                    raise ValueError(f"{name} 缺少参数")
                b = _as_array(stack.pop())
                a = _as_array(stack.pop())
                stack.append(_FUNCS_2[name](a, b))
            elif name in _FUNCS_3:
                if len(stack) < 3:
                    raise ValueError(f"{name} 缺少参数")
                ch = _as_array(stack.pop())
                b = _as_array(stack.pop())
                a = _as_array(stack.pop())
                stack.append(_FUNCS_3[name](a, b, ch))
            else:
                raise ValueError(f"未知函数：{name!r}")
        else:
            raise ValueError(f"未知 RPN token：{token!r}")
    if len(stack) != 1:
        raise ValueError("表达式存在多余操作数")
    return stack[0]


def validate(expr: str) -> list:
    """返回表达式中引用的变量名列表（如 ["ch1","ch2"]），非法时抛出 ValueError。

    供 UI 在应用前提示错误，也可用于判断表达式引用了哪些通道。
    """
    tokens = _tokenize(str(expr).strip())
    rpn = _to_rpn(tokens)      # 校验语法
    _check_rpn(rpn)            # BUG-R：校验操作数/参数数量（与 evaluate 一致）
    vars_ = []
    for token in tokens:
        if token[0] == "var":
            if token[1] not in vars_:
                vars_.append(token[1])
    return vars_