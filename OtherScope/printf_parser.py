# -*- coding: utf-8 -*-
"""printf 风格格式串解析器。

把用户约定的格式（例如 "ch1:%fmv"）编译成正则表达式，从串口收到的每一行文本中
提取数值通道。数值通道（%f / %d / %x 等）按出现顺序自动编号为 ch1、ch2…

支持常见的转换说明符：%d %i %u %o %x %X %f %e %E %g %G %a %A %c %s %p，以及
flags / width / .precision / length（如 %.2f、%6d、%lf、%llx）和 %% 转义。
"""

from __future__ import annotations

import math
import re

# 转换说明符：%[flags][width][.precision][length]conversion
_CONV_RE = re.compile(
    r"%(?P<flags>[-+ 0#]*)(?P<width>\*|\d+)?(?:\.(?P<precision>\*|\d+))?"
    r"(?P<length>hh|ll|h|l|j|z|t|L)?(?P<conv>[diuoxXfFeEgGaAcspn%])"
)

# ---------------------------------------------------------------------------
# 自动识别：从一批接收文本行推断 printf 格式串
# ---------------------------------------------------------------------------
# 数值 token 分类正则（按优先级：十六进制 > 浮点 > 科学计数 > 整数）。
# 覆盖 0x1A / -0x2B、120.3 / .5 / -20.、1.5e-3、25e3、-20、42 等常见下位机输出。
# 前置 (?<![A-Za-z0-9_]) 边界：排除 "ch1" / "adc0" 等标识符里的序号数字被误判为
# 数值字段（"ch1:120.3mv" 中只有 120.3 是数据，"ch1" 是通道名前缀）。
_AUTO_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:(?P<hex>[+-]?0[xX][0-9a-fA-F]+)"
    r"|(?P<flt>[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<exp>[+-]?\d+[eE][+-]?\d+)"
    r"|(?P<int>[+-]?\d+))"
)


def _tokenize_line(line: str):
    """把一行拆成交替 token：('lit', 字面量) / ('num', 数值文本)。

    返回 (pieces, num_tokens)：
    - pieces：交替序列 ``[lit0, num0, lit1, num1, ..., litK]``（K 个数值字段，
      首尾均为字面量，可为空串）；
    - num_tokens：按出现顺序的数值文本列表。
    """
    pieces = []
    toks = []
    last_end = 0
    for m in _AUTO_NUM_RE.finditer(line):
        pieces.append(("lit", line[last_end:m.start()]))
        pieces.append(("num", m.group()))
        toks.append(m.group())
        last_end = m.end()
    pieces.append(("lit", line[last_end:]))
    return pieces, toks


def _lcp(strings):
    """多字符串的最长公共前缀；空列表返回空串。"""
    if not strings:
        return ""
    s0 = min(strings, key=len)
    for i, ch in enumerate(s0):
        for s in strings:
            if s[i] != ch:
                return s0[:i]
    return s0


def recognize_printf_format(lines, max_sample: int = 200,
                            min_success_ratio: float = 0.3):
    """从一批文本行自动推断 printf 格式串（用于「自动识别」按钮）。

    策略：
    1. 取最近 ``max_sample`` 行非空文本，逐行抽取数值 token（十六进制/浮点/
       科学计数/整数），记录每行的字段数；
    2. 以出现次数最多的字段数为「众数」，仅取字段数=众数的行做一致样本；
    3. 逐列判定转换说明符：全为整数→``%d``；全为十六进制→``%x``；其余→``%f``；
    4. 各字面量位置取一致样本的**最长公共前缀**（保留常量文本/通道名前缀/单位）；
    5. 组装格式串后用 :class:`FrameParser` 回验：须能解析
       ``>= min_success_ratio`` 的样本行且至少识别出 1 个数值通道，才算成功。

    Args:
        lines: 原始接收文本行（可含空行/噪声，函数内部自行过滤）。
        max_sample: 参与分析的最近行数上限。
        min_success_ratio: 回验通过所需的样本解析成功率（0~1）。

    Returns:
        ``(format_str, ok_count, total_count)``：
        - 识别成功时 format_str 为 printf 格式串，否则为 None；
        - ok_count 为回验中成功解析出数值通道的样本行数；
        - total_count 为参与分析的样本行总数。
    """
    clean = [ln.rstrip() for ln in lines if ln and ln.strip()]
    sample = clean[-max_sample:]
    if not sample:
        return None, 0, 0

    rows = []
    for ln in sample:
        pieces, toks = _tokenize_line(ln)
        if toks:
            rows.append((pieces, toks))
    if not rows:
        return None, 0, len(sample)

    # 字段数众数 → 只保留字段数一致的"规律行"
    counts = {}
    for _pieces, toks in rows:
        counts[len(toks)] = counts.get(len(toks), 0) + 1
    mode = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    consistent = [(p, t) for p, t in rows if len(t) == mode]
    if not consistent:
        return None, 0, len(sample)

    # 逐列判定转换说明符
    specs = []
    for col in range(mode):
        col_toks = [t[col] for _p, t in consistent]
        if all(re.fullmatch(r"[+-]?0[xX][0-9a-fA-F]+", x) for x in col_toks):
            specs.append("%x")
        elif all(re.fullmatch(r"[+-]?\d+", x) for x in col_toks):
            specs.append("%d")
        else:
            specs.append("%f")

    # 字面量位置取最长公共前缀（pieces 中 literal_j 位于索引 2*j）
    lits = []
    for j in range(mode + 1):
        seg = [p[2 * j][1] if len(p) > 2 * j else "" for p, _ in consistent]
        lits.append(_lcp(seg))

    parts = []
    for j in range(mode):
        parts.append(lits[j])
        parts.append(specs[j])
    parts.append(lits[mode])
    fmt = "".join(parts)

    # 用真实解析器回验：识别出的格式必须能解析足够比例的样本行
    parser = FrameParser(fmt)
    ok = sum(1 for ln in sample if parser.parse(ln))
    if ok and parser.num_channels > 0 and ok / len(sample) >= min_success_ratio:
        return fmt, ok, len(sample)
    return None, ok, len(sample)

_FLOAT = r"[+-]?(?:(?i:inf(?:inity)?|nan)|[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_HEX_FLOAT = (r"[-+]?(?:(?i:inf(?:inity)?|nan)"
              r"|0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)[pP][-+]?[0-9]+)")
_DEC = r"[+-]?[0-9]+"
_UINT = r"[0-9]+"
_HEX = r"(?:0[xX])?[0-9a-fA-F]+"


def _build_tokens(format_str: str):
    """把格式串拆成 token：('literal', 字面量) 或 ('conv', 完整说明文本)。"""
    tokens = []
    literal = []
    i, n = 0, len(format_str)

    def flush():
        if literal:
            tokens.append(("literal", "".join(literal)))
            literal.clear()

    while i < n:
        ch = format_str[i]
        if ch != "%":
            literal.append(ch)
            i += 1
            continue
        if i + 1 < n and format_str[i + 1] == "%":
            literal.append("%")
            i += 2
            continue
        m = _CONV_RE.match(format_str, i)
        if not m:
            literal.append(ch)
            i += 1
            continue
        conv = m.group("conv")
        if conv == "n":          # %n 不产生输出，跳过
            i = m.end()
            continue
        flush()
        if conv == "%":
            tokens.append(("literal", "%"))
        else:
            tokens.append(("conv", m.group()))
        i = m.end()
    flush()
    return tokens


def _spec_to_regex(spec: str):
    """返回 (正则片段, int 进制或 None)。正则片段含一个捕获组。"""
    conv = spec[-1]
    # BUG-15 修复：解析宽度修饰符，%s 支持 %Ns 限制最大字符数
    m = _CONV_RE.match(spec)
    width = m.group("width") if m else None
    if conv == "s":
        if width and width.isdigit():
            return r"(\S{1," + width + r"})", None
        return r"(\S+)", None
    if conv == "c":
        if width and width.isdigit():
            return r"(.{1," + width + r"})", None
        return r"(.)", None
    if conv == "u":
        return r"(" + _UINT + r")", 10
    if conv in "di":
        return r"(" + _DEC + r")", 10
    if conv == "o":
        return r"([0-7]+)", 8
    if conv in "xX":
        return r"(" + _HEX + r")", 16
    if conv in "aA":
        return r"(" + _HEX_FLOAT + r")", None
    if conv in "fFeEgG":
        return r"(" + _FLOAT + r")", None
    if conv == "p":
        return r"((?:0[xX])?[0-9a-fA-F]+|\(nil\))", 16
    return None, None


def _tiny_format(spec, v):
    """尽力按说明符格式化浮点数（供模拟/自检用），失败时安全返回占位。"""
    try:
        return spec % v
    except Exception:
        try:
            return repr(float(v))
        except Exception:
            return ""


def _safe_int(v):
    """把任意标量安全转成 int；非有限值/无法转换时返回 0。"""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(f):
        return 0
    return int(f)


def _format_uint(v, base=10, prefix=""):
    """按无符号语义回填（掩码到 64 位），保证 render→parse 往返闭合。"""
    MASK = 0xFFFFFFFFFFFFFFFF
    i = _safe_int(v)
    if i >= 0 and i > MASK:
        # float64 无法精确表示 >2^53 的整数，超出 64 位无符号范围时饱和而非
        # 掩码绕回（2^64 掩码会得 0，造成静默数据损坏）
        i = MASK
    masked = i & MASK
    spec = {10: "d", 8: "o", 16: "x"}[base]
    return prefix + format(masked, spec)


class FrameParser(object):
    """按 printf 格式串解析一行文本，输出 {通道序号: 数值}。

    数值通道按出现顺序从 0 开始编号，对应显示中的 ch1、ch2…
    """

    def __init__(self, format_str: str = "ch1:%fmv"):
        self.format = ""
        self.tokens = []
        self._regex = None
        self._convs = []     # 每个转换组：('float'|'int'|'str', spec, 进制或 None)
        self.channel_units = []  # 每个数值通道的单位（从格式串转换说明符后提取）
        self.num_channels = 0
        self.set_format(format_str)

    def set_format(self, format_str: str):
        """设置 printf 格式串并重建解析 token 与正则。

        Args:
            format_str: printf 风格格式串；空串视为无格式。

        Returns:
            None。
        """
        self.format = format_str or ""
        self.tokens = _build_tokens(self.format)
        parts = []
        convs = []
        units = []
        for idx, (kind, text) in enumerate(self.tokens):
            if kind == "literal":
                parts.append(re.escape(text))
            else:
                rx, base = _spec_to_regex(text)
                if rx is None:
                    continue
                parts.append(rx)
                c = text[-1]
                if c in "fFeEgGaA":
                    conv_kind = "float"
                elif c in "diuoxXp":
                    conv_kind = "int"
                else:
                    conv_kind = "str"
                convs.append((conv_kind, text, base))
                # 提取单位：转换说明符后紧跟的字母/符号序列（直到下一个转换说明符或非单位字符）
                unit = ""
                if conv_kind != "str" and idx + 1 < len(self.tokens):
                    next_tok = self.tokens[idx + 1]
                    if next_tok[0] == "literal":
                        # 取字面量开头的单位字符（字母、µ、Ω等），容忍前导空格
                        # （格式串常见 "V=%d mV" 带空格写法），遇到逗号/数字等停止
                        m = re.match(r"\s*([A-Za-zµΩμ]+)(\d*)", next_tok[1])
                        if m:
                            unit = m.group(1)
                            # BUG-35：多通道格式串（如 "ch1:%f ch2:%d"）中，
                            # 下一通道名前缀 "ch2" 的字母部分 "ch" 会被误判为单位。
                            # 形如 "chN"（通道名标签）时拒绝，保持默认单位 V。
                            if re.match(r"^[cC][hH]$", unit) and m.group(2):
                                unit = ""
                units.append(unit if conv_kind != "str" else "")
        self._convs = convs
        self.channel_units = units
        self.num_channels = sum(1 for c in convs if c[0] != "str")
        try:
            self._regex = re.compile("".join(parts))
        except re.error:
            self._regex = None

    def parse(self, line: str):
        """解析一行，返回 {通道序号(int): float}；无法匹配返回 None。"""
        if not self._regex or not isinstance(line, str):
            return None
        # BUG-05 修复：原 line.strip() 会移除行首空白，导致前缀含空白的格式串匹配失败。
        # 现仅去除行尾空白（行尾换行已由切行逻辑移除，此处处理 trailing spaces）。
        m = self._regex.search(line.rstrip())
        if not m:
            return None
        out = {}
        ch_num = 0
        for i, (kind, spec, base) in enumerate(self._convs):
            s = m.group(i + 1)
            if kind == "str":
                continue
            if s is None or s == "":
                ch_num += 1
                continue
            try:
                conv = spec[-1]
                if kind == "int":
                    # %p 匹配到 "(nil)" 文本已排除（正则为十六进制），无需特殊分支
                    v = float(int(s, base or 10))
                elif conv in "aA":
                    # C99 十六进制浮点需用 fromhex（float() 不认识 0x1.8p+1）
                    low = s.lower()
                    v = float(s) if low.startswith(("inf", "nan")) else float.fromhex(s)
                else:
                    v = float(s)
                # 超长数字 float() 会静默返回 inf；nan/inf 会污染波形/测量/FFT，一律丢弃
                if math.isfinite(v):
                    out[ch_num] = v
            except (ValueError, OverflowError):
                # 溢出/非法数值直接丢弃该通道，避免崩溃
                pass
            ch_num += 1
        return out if out else None

    def render(self, values):
        """把数值列表按格式串回填成一行文本（模拟数据源/自检用）。

        整数类说明符按「无符号/掩码」语义回填，负值/非有限值安全降级，
        确保 render 产出的文本能被自身 parse 回读（往返闭合）。
        """
        value_idx = 0
        parts = []
        for kind, text in self.tokens:
            if kind == "literal":
                parts.append(text)
                continue
            conv = text[-1]
            v = values[value_idx] if value_idx < len(values) else 0
            if conv in "fFeEgG":
                parts.append(_tiny_format(text, v))
                value_idx += 1
            elif conv in "aA":
                # C99 十六进制浮点：float.hex 输出可被 float.fromhex 回读
                parts.append(self._hex_float(v, upper=(conv == "A")))
                value_idx += 1
            elif conv == "u":
                parts.append(_format_uint(v, 10))
                value_idx += 1
            elif conv in "di":
                # 有符号整数：非有限值降级为 0，负数保留符号
                parts.append(str(_safe_int(v)))
                value_idx += 1
            elif conv == "o":
                parts.append(_format_uint(v, 8))
                value_idx += 1
            elif conv in "xX":
                out = _format_uint(v, 16)
                parts.append(out.upper() if conv == "X" else out)
                value_idx += 1
            elif conv == "p":
                parts.append(_format_uint(v, 16, prefix="0x"))
                value_idx += 1
            else:
                parts.append("?")
        return "".join(parts)

    @staticmethod
    def _hex_float(v, upper=False):
        """把数值格式化为 C99 十六进制浮点文本（含 nan/inf 安全降级）。"""
        try:
            s = float(v).hex()
        except (TypeError, ValueError, OverflowError):
            return "nan"
        return s.upper() if upper else s