# -*- coding: utf-8 -*-
"""终端交互组件：回车即发输入行、发送历史、快捷发送栏与编辑对话框。

参考 WindTerm 的交互习惯：
- 输入行内直接回车即发送，↑/↓ 键回溯发送历史，Esc 清空。
- 快捷发送栏可增删改移，每个条目独立配置 HEX 与行尾，退出程序后自动持久化。
"""

from __future__ import annotations

import copy
import json
import os

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QPalette
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QScrollArea,
    QDialog, QDialogButtonBox, QComboBox, QCheckBox, QPlainTextEdit,
    QFormLayout, QMenu, QMessageBox, QSizePolicy)

from .translations import tr

# 行尾选项：value 为稳定码（持久化与 newline_bytes 使用），display 为 i18n key
_NEWLINE_OPTIONS = [("无", "terminal.newline.none"), ("\\r\\n", None),
                    ("\\n", None), ("\\r", None)]
_NEWLINE_BYTES = {"无": b"", "\\r\\n": b"\r\n", "\\n": b"\n", "\\r": b"\r"}
_NEWLINE_CODES = [code for code, _ in _NEWLINE_OPTIONS]


def newline_bytes(code: str) -> bytes:
    """按新行标识返回对应的换行字节序列。

    Args:
        code: 新行标识（如 "无"/"CRLF"）。

    Returns:
        换行字节（bytes）；未知标识返回空。
    """
    return _NEWLINE_BYTES.get(code, b"")


def _newline_display(code: str) -> str:
    for nl_code, key in _NEWLINE_OPTIONS:
        if nl_code == code:
            return tr(key) if key else nl_code
    return code


# ---------------------------------------------------------------------------
# 校验算法：覆盖全球已公开的常用串口校验（XOR/SUM/LRC、CRC8/16/32、Adler/Fletcher）
# 全部对空输入统一返回 b""（不追加校验），与市面串口助手口径一致。
# ---------------------------------------------------------------------------
def xor8(data: bytes) -> bytes:
    """XOR8 校验：全部字节异或取低 8 位。

    Args:
        data: 待校验字节。

    Returns:
        校验字节；空输入返回空。
    """
    if not data:
        return b""     # 空输入不追加校验
    s = 0
    for b in data:
        s ^= b
    return bytes([s & 0xFF])


def sum8(data: bytes) -> bytes:
    """SUM8 校验：全部字节累加取低 8 位。

    Args:
        data: 待校验字节。

    Returns:
        校验字节；空输入返回空。
    """
    if not data:
        return b""
    return bytes([sum(data) & 0xFF])


def sum16(data: bytes) -> bytes:
    """SUM16 校验：全部字节累加取 16 位，低字节在前。

    Args:
        data: 待校验字节。

    Returns:
        双字节校验；空输入返回空。
    """
    if not data:
        return b""
    s = sum(data) & 0xFFFF
    return bytes([s & 0xFF, (s >> 8) & 0xFF])   # 低字节在前


def lrc(data: bytes) -> bytes:
    """LRC（纵向冗余校验，Modbus ASCII 口径）：8-bit 累加和的二进制补码。"""
    if not data:
        return b""
    return bytes([(-sum(data)) & 0xFF])


def parity_even(data: bytes) -> bytes:
    """整帧偶校验：数据全字节中 1 的个数为偶数返回 0x00，否则返回 0x01。"""
    if not data:
        return b""
    ones = sum(bin(b).count("1") for b in data)
    return bytes([0x00 if ones % 2 == 0 else 0x01])


def parity_odd(data: bytes) -> bytes:
    """整帧奇校验：数据全字节中 1 的个数为奇数返回 0x00，否则返回 0x01。"""
    if not data:
        return b""
    ones = sum(bin(b).count("1") for b in data)
    return bytes([0x00 if ones % 2 == 1 else 0x01])


def _reflect(value: int, bits: int) -> int:
    v = value & ((1 << bits) - 1)
    r = 0
    for _ in range(bits):
        r = (r << 1) | (v & 1)
        v >>= 1
    return r


def _crc8(data: bytes, poly: int, init: int, xorout: int, refin: bool) -> int:
    mask = 0xFF
    crc = init & mask
    if refin:
        p = _reflect(poly, 8)
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = ((crc >> 1) ^ p) & mask if (crc & 1) else (crc >> 1) & mask
    else:
        # 非反射（高位先出）：字节直接异或入低 8 位，随左移逐位进入 0x80 判断
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & mask if (crc & 0x80) else (crc << 1) & mask
    return (crc ^ xorout) & mask


def _crc16(data: bytes, poly: int, init: int, xorout: int, refin: bool) -> int:
    mask = 0xFFFF
    crc = init & mask
    if refin:
        p = _reflect(poly, 16)
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = ((crc >> 1) ^ p) & mask if (crc & 1) else (crc >> 1) & mask
    else:
        for b in data:
            crc ^= b << 8
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & mask if (crc & 0x8000) else (crc << 1) & mask
    return (crc ^ xorout) & mask


def _crc32(data: bytes, poly: int, init: int, xorout: int, refin: bool) -> int:
    mask = 0xFFFFFFFF
    crc = init & mask
    if refin:
        p = _reflect(poly, 32)
        for b in data:
            crc ^= b
            for _ in range(8):
                crc = ((crc >> 1) ^ p) & mask if (crc & 1) else (crc >> 1) & mask
    else:
        for b in data:
            crc ^= b << 24
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & mask if (crc & 0x80000000) else (crc << 1) & mask
    return (crc ^ xorout) & mask


def crc8_maxim(data: bytes) -> bytes:
    """CRC-8/MAXIM（多项式 0x31，初值 0x00，结果异或 0x00，低位先出）。返回 1 字节。"""
    if not data:
        return b""
    return bytes([_crc8(data, 0x31, 0x00, 0x00, True)])


def crc8_atm(data: bytes) -> bytes:
    """CRC-8/ATM（多项式 0x07，初值 0x00，结果异或 0x00，高位先出）。返回 1 字节。"""
    if not data:
        return b""
    return bytes([_crc8(data, 0x07, 0x00, 0x00, False)])


def crc16_modbus(data: bytes) -> bytes:
    """Modbus CRC-16，输出低字节在前（little-endian），与市面助手一致。"""
    if not data:
        return b""
    c = _crc16(data, 0x8005, 0xFFFF, 0x0000, True)
    return bytes([c & 0xFF, (c >> 8) & 0xFF])


def crc16_ccitt(data: bytes) -> bytes:
    """CRC-16/CCITT（多项式 0x1021，初值 0xFFFF，结果异或 0x0000，高位先出）。返回 2 字节，高字节在前。"""
    if not data:
        return b""
    c = _crc16(data, 0x1021, 0xFFFF, 0x0000, False)
    return bytes([(c >> 8) & 0xFF, c & 0xFF])   # 高字节在前


def crc16_xmodem(data: bytes) -> bytes:
    """CRC-16/XMODEM（多项式 0x1021，初值 0x0000，结果异或 0x0000，高位先出）。返回 2 字节，高字节在前。"""
    if not data:
        return b""
    c = _crc16(data, 0x1021, 0x0000, 0x0000, False)
    return bytes([(c >> 8) & 0xFF, c & 0xFF])


def crc16_ibm(data: bytes) -> bytes:
    """CRC-16/IBM（多项式 0x8005，初值 0x0000，结果异或 0x0000，低位先出）。返回 2 字节。"""
    if not data:
        return b""
    c = _crc16(data, 0x8005, 0x0000, 0x0000, True)
    return bytes([c & 0xFF, (c >> 8) & 0xFF])


def crc16_usb(data: bytes) -> bytes:
    """CRC-16/USB（多项式 0x8005，初值 0xFFFF，结果异或 0xFFFF，低位先出）。返回 2 字节。"""
    if not data:
        return b""
    c = _crc16(data, 0x8005, 0xFFFF, 0xFFFF, True)
    return bytes([c & 0xFF, (c >> 8) & 0xFF])


def crc16_dnp(data: bytes) -> bytes:
    """CRC-16/DNP（多项式 0x3D65，初值 0x0000，结果异或 0xFFFF，低位先出）。返回 2 字节。"""
    if not data:
        return b""
    c = _crc16(data, 0x3D65, 0x0000, 0xFFFF, True)
    return bytes([c & 0xFF, (c >> 8) & 0xFF])


def crc32(data: bytes) -> bytes:
    """CRC-32（多项式 0x04C11DB7，初值 0xFFFFFFFF，结果异或 0xFFFFFFFF，低位先出）。返回 4 字节，小端。"""
    if not data:
        return b""
    c = _crc32(data, 0x04C11DB7, 0xFFFFFFFF, 0xFFFFFFFF, True)
    return bytes([c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, (c >> 24) & 0xFF])


def crc32_mpeg2(data: bytes) -> bytes:
    """CRC-32/MPEG-2（多项式 0x04C11DB7，初值 0xFFFFFFFF，结果异或 0x0000，高位先出）。返回 4 字节，大端。"""
    if not data:
        return b""
    c = _crc32(data, 0x04C11DB7, 0xFFFFFFFF, 0x0000, False)
    return bytes([(c >> 24) & 0xFF, (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF])


def adler32(data: bytes) -> bytes:
    """Adler-32 校验（模 65521 的滑动累加和）。返回 4 字节，大端。"""
    if not data:
        return b""
    a, b = 1, 0
    for byte in data:
        a = (a + byte) % 65521
        b = (b + a) % 65521
    v = (b << 16) | a
    return bytes([(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def fletcher16(data: bytes) -> bytes:
    """Fletcher-16 校验（模 255 的双累加和）。返回 2 字节：sum1 低字节、sum2 高字节。"""
    if not data:
        return b""
    sum1, sum2 = 0, 0
    for byte in data:
        sum1 = (sum1 + byte) % 255
        sum2 = (sum2 + sum1) % 255
    return bytes([sum1 & 0xFF, sum2 & 0xFF])


def fletcher32(data: bytes) -> bytes:
    """Fletcher-32 校验（模 65535 的双累加和）。返回 4 字节，大端。"""
    if not data:
        return b""
    sum1, sum2 = 0, 0
    for byte in data:
        sum1 = (sum1 + byte) % 65535
        sum2 = (sum2 + sum1) % 65535
    v = (sum2 << 16) | sum1
    return bytes([(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


# 展示顺序即下拉框顺序（稳定键，用于持久化与 dispatch）
_CHECKSUM_ORDER = [
    "XOR8", "SUM8", "SUM16", "LRC",
    "CRC8-MAXIM", "CRC8-ATM",
    "CRC16-Modbus", "CRC16-CCITT", "CRC16-XMODEM", "CRC16-IBM", "CRC16-USB", "CRC16-DNP",
    "CRC32", "CRC32-MPEG2",
    "Adler32", "Fletcher-16", "Fletcher-32",
    "Parity-Even", "Parity-Odd",
]

_CHECKSUMS = {
    "XOR8": xor8,
    "SUM8": sum8,
    "SUM16": sum16,
    "LRC": lrc,
    "CRC8-MAXIM": crc8_maxim,
    "CRC8-ATM": crc8_atm,
    "CRC16-Modbus": crc16_modbus,
    "CRC16-CCITT": crc16_ccitt,
    "CRC16-XMODEM": crc16_xmodem,
    "CRC16-IBM": crc16_ibm,
    "CRC16-USB": crc16_usb,
    "CRC16-DNP": crc16_dnp,
    "CRC32": crc32,
    "CRC32-MPEG2": crc32_mpeg2,
    "Adler32": adler32,
    "Fletcher-16": fletcher16,
    "Fletcher-32": fletcher32,
    "Parity-Even": parity_even,
    "Parity-Odd": parity_odd,
}

CHECKSUM_NONE = "无"


def checksum_labels():
    """返回下拉框校验算法标签列表（含“无”），顺序与 _CHECKSUM_ORDER 一致。"""
    return [CHECKSUM_NONE] + _CHECKSUM_ORDER


def compute_checksum(data: bytes, label: str) -> bytes:
    """按指定校验算法计算校验值字节序列。

    Args:
        data: 待校验的原始字节。
        label: 校验算法名称；为空数据或不支持时返回空。

    Returns:
        校验值字节序列（bytes）；无数据 / 算法不存在时返回空字节。
    """
    if not data or label == CHECKSUM_NONE:
        return b""
    checksum_fn = _CHECKSUMS.get(label)
    return checksum_fn(data) if checksum_fn is not None else b""


def hex_to_bytes(text: str) -> bytes:
    """解析十六进制字符串（严格校验，非法输入抛 ValueError）。

    容忍常见书写习惯：空格、制表符、换行、逗号分隔；每个 token 可选单个
    0x/0X 前缀。字节间可不加分隔（如 "0a0d"），但位数必须为偶数。
    """
    import re
    out = bytearray()
    tokens = re.split(r"[\s,]+", text.strip())
    for token in tokens:
        if not token:
            continue
        if token[:2] in ("0x", "0X"):
            token = token[2:]
        if not token:
            raise ValueError("空的十六进制 token（如单独的 0x）")
        if len(token) % 2 != 0:
            raise ValueError(f"十六进制位数必须为偶数：{token!r}")
        try:
            out.extend(bytes.fromhex(token))
        except ValueError:
            raise ValueError(f"非法十六进制 token：{token!r}")
    return bytes(out)


def interpret_escapes(text: str, encoding: str = "utf-8") -> bytes:
    """按字节语义解释 C 风格转义，返回原始待发送字节。

    支持 \\r \\n \\t \\0 \\xHH \\uHHHH \\\\。`\\xHH` 生成单个原始字节（0x00–0xFF），
    与 SSCOM/WindTerm 的字节语义一致；`\\uHHHH` 生成对应 Unicode 字符后按 encoding 编码。
    未识别的反斜杠按字面保留，不会吞掉后续字符。
    """
    out = bytearray()
    buffer = []                     # 普通字符缓冲，遇转义时编码冲刷
    i, n = 0, len(text)
    hex_digits = set("0123456789abcdefABCDEF")

    def flush():
        if buffer:
            out.extend("".join(buffer).encode(encoding, errors="replace"))
            buffer.clear()

    while i < n:
        c = text[i]
        if c != "\\" or i + 1 >= n:
            buffer.append(c)
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "r":
            flush()
            out.extend(b"\r")
            i += 2
            continue
        if nxt == "n":
            flush()
            out.extend(b"\n")
            i += 2
            continue
        if nxt == "t":
            flush()
            out.extend(b"\t")
            i += 2
            continue
        if nxt == "0":
            flush()
            out.extend(b"\x00")
            i += 2
            continue
        if nxt == "\\":
            flush()
            out.extend(b"\\")
            i += 2
            continue
        if nxt == "x":
            h = text[i + 2:i + 4]
            if len(h) == 2 and all(ch in hex_digits for ch in h):
                flush()
                out.append(int(h, 16))
                i += 4
                continue
        if nxt == "u":
            h = text[i + 2:i + 6]
            if len(h) == 4 and all(ch in hex_digits for ch in h):
                code_point = int(h, 16)
                # 高代理：向前合并紧随其后的低代理 \uXXXX，还原补充平面字符
                if (0xD800 <= code_point <= 0xDBFF and i + 7 < n
                        and text[i + 6] == "\\" and text[i + 7] == "u"):
                    hex_high = text[i + 8:i + 12]
                    hex_valid = (len(hex_high) == 4
                                 and all(c in hex_digits for c in hex_high))
                    lo = int(hex_high, 16) if hex_valid else -1
                    if 0xDC00 <= lo <= 0xDFFF:
                        code_point = 0x10000 + ((code_point - 0xD800) << 10) + (lo - 0xDC00)
                        flush()
                        out.extend(chr(code_point).encode(encoding, errors="replace"))
                        i += 12
                        continue
                flush()
                out.extend(chr(code_point).encode(encoding, errors="replace"))
                i += 6
                continue
        buffer.append(c)              # 未识别转义：保留反斜杠本身
        i += 1
    flush()
    return bytes(out)


class SendLineEdit(QLineEdit):
    """支持发送历史回溯的发件输入行。"""

    submitted = Signal(str)   # 回车时发出当前文本

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []
        self._index = -1
        self._draft = ""      # 首次上翻前记住未发送草稿，回退到最新时找回
        self.setPlaceholderText(tr("terminal.input_placeholder"))

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            text = self.text()
            if text:
                self.record(text)
                self.submitted.emit(text)
                self.clear()
            return
        if key == Qt.Key.Key_Up:
            self._step_history(1)      # 向更旧
            return
        if key == Qt.Key.Key_Down:
            self._step_history(-1)     # 向更新
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            self._index = -1
            self._draft = ""
            return
        super().keyPressEvent(event)

    def record(self, text: str):
        """记录发送历史：去重后置于队首，限制历史长度上限。"""
        # 去重并置于队首，限制历史长度
        if text in self._history:
            self._history.remove(text)
        self._history.insert(0, text)
        self._history = self._history[:500]
        self._index = -1
        self._draft = ""

    def _step_history(self, delta: int):
        """delta>0 表示往更旧方向（↑），delta<0 往更新方向（↓）。"""
        if not self._history:
            return
        if self._index == -1:
            if delta > 0:
                self._draft = self.text()   # 记住未发送草稿，回退后仍可找回
                self._index = 0
            else:
                return
        else:
            self._index += delta
            if self._index < 0:
                self._index = -1
            elif self._index >= len(self._history):
                self._index = len(self._history) - 1
        if self._index == -1:
            self.setText(self._draft)
        else:
            self.setText(self._history[self._index])


class SendEdit(QPlainTextEdit):
    """多行发送输入框（cmd 风格）：Enter 发送、Shift+Enter 换行、↑/↓ 回溯历史、Esc 清空。

    相比单行输入框，多行能容纳更长命令与多字节 HEX 序列；高度随内容在
    [2, 8] 行之间自适应增长，解决「一行太小无法直接输入」的问题。
    """

    submitted = Signal(str)

    # 高度策略：不固定高度，由发送面板布局 stretch 控制——
    # 发送面板随分隔条伸缩时，输入行吸收全部高度变化（无空白）；
    # 只设最小高度保证至少可输入 2 行，内容更多时靠内部滚动条。
    _MIN_H = 60
    _MAX_H = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = []
        self._index = -1
        self._draft = ""
        self.setPlaceholderText(tr("terminal.input_placeholder"))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(self._MIN_H)
        self.textChanged.connect(self._sync_height)

    # ---- 兼容旧单行接口（text/setText/record/clear），便于测试与主窗口复用 ----
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str):
        self.setPlainText(text)

    def record(self, text: str):
        """记录发送历史：去重后置于队首，限制历史长度上限。"""
        if text in self._history:
            self._history.remove(text)
        self._history.insert(0, text)
        self._history = self._history[:500]
        self._index = -1
        self._draft = ""

    def _at_top(self) -> bool:
        c = self.textCursor()
        return c.blockNumber() == 0 and c.positionInBlock() == 0

    def _at_bottom(self) -> bool:
        c = self.textCursor()
        n = self.document().blockCount()
        last = self.document().findBlockByNumber(n - 1)
        return c.blockNumber() == n - 1 and c.positionInBlock() >= last.length()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)     # Shift+Enter：换行
                return
            text = self.toPlainText().rstrip("\n\r")
            if text:
                self.record(text)
                self.submitted.emit(text)
                self.clear()
            return
        if key == Qt.Key.Key_Up and self._at_top():
            self._step_history(1)                # 向更旧
            return
        if key == Qt.Key.Key_Down and self._at_bottom():
            self._step_history(-1)               # 向更新
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            self._index = -1
            self._draft = ""
            return
        super().keyPressEvent(event)

    def _step_history(self, delta: int):
        """delta>0 向更旧（↑），delta<0 向更新（↓）。"""
        if not self._history:
            return
        if self._index == -1:
            if delta > 0:
                self._draft = self.toPlainText()   # 记住未发送草稿
                self._index = 0
            else:
                return
        else:
            self._index += delta
            if self._index < 0:
                self._index = -1
            elif self._index >= len(self._history):
                self._index = len(self._history) - 1
        self.setPlainText(self._draft if self._index == -1 else self._history[self._index])
        c = self.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(c)

    def _sync_height(self):
        # 内容增多时放宽最小高度上限（发送面板可容纳时显示更多行），
        # 但始终可被发送面板压缩回 _MIN_H。
        doc_h = int(self.document().size().height())
        h = max(self._MIN_H, min(self._MAX_H, doc_h + 10))
        if abs(h - self.minimumHeight()) > 4:
            self.setMinimumHeight(h)


class QuickSendEditDialog(QDialog):
    """新增 / 编辑一条快捷发送项。"""

    def __init__(self, name="", data="", is_hex=False, newline="\\r\\n", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("quick.dlg_title"))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.ed_name = QLineEdit(name)
        self.ed_name.setPlaceholderText(tr("quick.name_ph"))
        form.addRow(tr("quick.name"), self.ed_name)
        self.ed_data = QPlainTextEdit(data)
        self.ed_data.setPlaceholderText(tr("quick.content_ph"))
        self.ed_data.setMinimumHeight(90)
        form.addRow(tr("quick.content"), self.ed_data)
        self.chk_hex = QCheckBox(tr("quick.as_hex"))
        self.chk_hex.setChecked(is_hex)
        form.addRow("", self.chk_hex)
        self.cb_nl = QComboBox()
        for code, key in _NEWLINE_OPTIONS:
            self.cb_nl.addItem(tr(key) if key else code, code)
        idx = self.cb_nl.findData(newline)
        if idx < 0:
            idx = self.cb_nl.findData("\\r\\n")
        self.cb_nl.setCurrentIndex(max(0, idx))
        form.addRow(tr("terminal.newline"), self.cb_nl)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("common.ok"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("common.cancel"))
        btns.accepted.connect(self._check_and_accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _check_and_accept(self):
        if not self.ed_name.text().strip():
            QMessageBox.warning(self, tr("common.warning"), tr("quick.warn_name"))
            return
        if self.chk_hex.isChecked():
            try:
                hex_to_bytes(self.ed_data.toPlainText())
            except ValueError:
                QMessageBox.warning(self, tr("common.warning"), tr("quick.warn_hex"))
                return
        self.accept()

    @property
    def item(self):
        return {
            "name": self.ed_name.text().strip(),
            "data": self.ed_data.toPlainText(),
            "hex": self.chk_hex.isChecked(),
            "newline": self.cb_nl.currentData() or "\\r\\n",
        }


class QuickSendBar(QScrollArea):
    """可横向滚动的快捷发送按钮栏，附一枚「快捷」管理按钮。"""

    send = Signal(object)      # 发送 item(dict)；由主窗口负责编码与写入
    dirty = Signal()           # 条目变化（用于去抖保存）

    def __init__(self, store_path=None, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFixedHeight(46)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.store_path = store_path or os.path.join(
            os.path.expanduser("~"), ".OtherScope", "quick_send.json")
        self.items = self._load()

        self._inner = QWidget()
        self._layout = QHBoxLayout(self._inner)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(4)
        self.setWidget(self._inner)
        self._rebuild()

    # ------------------------------------------------------------- 持久化
    def _load(self):
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return self._defaults()
            items = []
            for d in data:
                if not isinstance(d, dict):
                    continue
                name = d.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                raw_data = d.get("data")
                data_s = raw_data if isinstance(raw_data, str) else ""
                newline = d.get("newline")
                newline = newline if isinstance(newline, str) else "\\r\\n"
                if newline not in _NEWLINE_CODES:
                    newline = "\\r\\n"
                items.append({
                    "name": name.strip(),
                    "data": data_s,
                    "hex": d.get("hex") is True,   # 仅严格 True 才启用 HEX，避免字符串 "false" 被误判
                    "newline": newline,
                })
            return items
        except FileNotFoundError:
            return self._defaults()
        except Exception:
            return self._defaults()

    @staticmethod
    def _defaults():
        return [
            {"name": "ping", "data": "AT", "hex": False, "newline": "\\r\\n"},
            {"name": "查询版本", "data": "VER", "hex": False, "newline": "\\r\\n"},
            {"name": "复位", "data": "RST", "hex": False, "newline": "\\r\\n"},
            {"name": "0x01", "data": "01 02 03 04", "hex": True, "newline": "无"},
        ]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
        except OSError:
            # 快捷发送栏持久化失败不影响运行：静默忽略，下次启动沿用内存内容
            pass

    # ------------------------------------------------------------- 界面重建
    def _rebuild(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                # addStretch 产生的 QSpacerItem 无 widget，需显式释放避免累积泄漏
                del item

        self._btn_add = QPushButton(tr("quick.new"))
        self._btn_add.clicked.connect(self._add)
        self._layout.addWidget(self._btn_add)

        self._buttons = []
        for idx, item in enumerate(self.items):
            btn = QPushButton(item["name"])
            btn.setToolTip(self._format_tip(item))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.clicked.connect(lambda _=False, i=idx: self._send(i))
            btn.customContextMenuRequested.connect(
                lambda pos, i=idx, b=btn: self._menu(b, i, pos))
            self._layout.addWidget(btn)
            self._buttons.append(btn)

        self._layout.addStretch(1)

    @staticmethod
    def _format_tip(item):
        kind = tr("quick.tip_hex") if item["hex"] else tr("quick.tip_text")
        data = item["data"]
        if len(data) > 40:
            data = data[:40] + "…"
        return f"{kind}{data}\n{tr('quick.tip_newline')}{_newline_display(item['newline'])}"

    # ------------------------------------------------------------- 动作
    def _send(self, index):
        if 0 <= index < len(self.items):
            self.send.emit(copy.deepcopy(self.items[index]))

    def _add(self):
        dialog = QuickSendEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.items.append(dialog.item)
            self._changed()

    def _edit(self, index):
        if not (0 <= index < len(self.items)):
            return
        item = self.items[index]
        dialog = QuickSendEditDialog(
            item["name"], item["data"], item["hex"], item["newline"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.items[index] = dialog.item
            self._changed()

    def _delete(self, index):
        if 0 <= index < len(self.items):
            del self.items[index]
            self._changed()

    def _move(self, index, delta):
        j = index + delta
        if 0 <= index < len(self.items) and 0 <= j < len(self.items):
            self.items[index], self.items[j] = self.items[j], self.items[index]
            self._changed()

    def _menu(self, button, index, pos):
        menu = QMenu(self)
        a_send = menu.addAction(tr("quick.send"))
        menu.addSeparator()
        a_edit = menu.addAction(tr("quick.edit"))
        a_del = menu.addAction(tr("quick.delete"))
        a_up = menu.addAction(tr("quick.move_up"))
        a_down = menu.addAction(tr("quick.move_down"))
        chosen = menu.exec(button.mapToGlobal(pos))
        menu.deleteLater()
        if chosen == a_send:
            self._send(index)
        elif chosen == a_edit:
            self._edit(index)
        elif chosen == a_del:
            self._delete(index)
        elif chosen == a_up:
            self._move(index, -1)
        elif chosen == a_down:
            self._move(index, 1)

    def _changed(self):
        self.save()
        self.dirty.emit()
        self._rebuild()

    def retranslate(self):
        """语言切换后刷新「新建」按钮与各条目提示（条目名称为用户数据，不翻译）。"""
        if hasattr(self, "_btn_add"):
            self._btn_add.setText(tr("quick.new"))
        for btn, item in zip(getattr(self, "_buttons", []), self.items):
            btn.setToolTip(self._format_tip(item))


# ---------------------------------------------------------------------------
# 即时发送 / 本地回显终端（Local Echo with Instant Send，复刻 WindTerm）
# ---------------------------------------------------------------------------
ECHO_COLOR = "#e09600"        # 已发送（本地回显）字符颜色：金色，深/浅色背景均清晰
PROMPT_COLOR = "#8a94a6"      # 输入提示符 "> " 的柔和灰
RX_COLOR = "#8fe3a6"          # 接收数据（RX）默认颜色：柔和绿，与 TX/时间戳区分
TIMESTAMP_COLOR = "#6b7280"   # 时间戳颜色：弱化灰，不抢占正文注意力
LINENO_COLOR = "#5a6472"      # 行号颜色：弱化灰蓝，与时间戳同级，不干扰正文
LINE_NO_MARKER = "__LINENO__"     # 行号片段内部标记：由 _flush 翻译为「前置色 + 区分背景」，整列效果接近行号栏

# ANSI SGR 前景色映射（16 色），复刻 WindTerm 等终端的一般配色习惯
ANSI_COLORS = {
    30: "#2f3542", 31: "#e5484d", 32: "#46a758", 33: "#e0a316",
    34: "#3b82f6", 35: "#c026d3", 36: "#0fa8a8", 37: "#d8dee9",
    90: "#7a8494", 91: "#ff6b6b", 92: "#69db7c", 93: "#ffd43b",
    94: "#74c0fc", 95: "#e599f7", 96: "#66d9e8", 97: "#ffffff",
}


def _iter_ansi(text):
    """把含 ANSI SGR 序列的文本拆成 [(chunk, color_or_None), ...]。

    仅处理 CSI ``...m`` 选择图形再现（SGR）序列中的前景色（30–37 / 90–97）
    与复位（``0`` / ``39``）；粗体等其余属性安全忽略。非 SGR 的转义字节按原样
    保留，避免吞掉设备侧其它控制序列的可见含义。
    """
    if "\x1b" not in text:
        return [(text, None)]
    segs = []
    buffer = []
    color = None
    i, n = 0, len(text)

    def flush():
        if buffer:
            segs.append(("".join(buffer), color))
            buffer.clear()

    while i < n:
        c = text[i]
        if c == "\x1b" and i + 1 < n and text[i + 1] == "[":
            # 先冲刷当前缓冲（带当前颜色），避免转义前后文本合并成一段
            flush()
            # 定位 CSI 结束字母
            j = i + 2
            while j < n and not (text[j].isalpha()):
                j += 1
            if j < n and text[j] == "m":
                params = text[i + 2:j]
                for p in params.split(";"):
                    if p in ("", "0", "39"):
                        color = None
                    elif p == "1":
                        pass                # 粗体：忽略（保持可读即可）
                    else:
                        try:
                            code = int(p)
                        except ValueError:
                            continue
                        if code in ANSI_COLORS:
                            color = ANSI_COLORS[code]
                i = j + 1
                continue
        buffer.append(c)
        i += 1
    flush()
    return segs if segs else [("", None)]


class InstantTerminal(QPlainTextEdit):
    """串口终端接收/显示/即时输入控件（清零重写，文本编辑器式编辑）。

    【回显模型】（按用户实测要求对齐「系统自带文本编辑器」）
      - 「本地回显」= 终端自己显示键入字符；「远程回显」= 下位机回传显示。
      - 关闭本地回显（默认，用于带回显设备）：
          按键【始终发送】、不本地渲染，显示完全由设备回显驱动（输入紧跟设备
          提示符 msh >help）。设备回显中的退格  按终端语义执行擦除（删除文档
          末尾一个字符），不再显示为空格。
      - 开启本地回显（用于不回显设备 / 需要编辑反馈）：
          按键【始终发送】+ 本地金色显示，且【设备回显与本地输入顺序配对消费】——
          设备回传的确认字符（与本地最近输入一致）不再重复显示；设备对退格/回车
          的确认回显（\b \b、\r\n）静默处理。
          结果：屏幕显示与逻辑输入完全一致（输入 help、退格退格、再输 lp →
          屏幕始终显示 help），与系统自带文本编辑器编辑体验一致。
      - 说明：此前版本曾按 WindTerm 官方说明实现「本地+远程叠加每字符两次」
        （hheellpp）。实测发现叠加状态下退格/编辑显示混乱（设备 \b 被显示为空格、
        删除不同步），用户明确要求「跟系统文本编辑器一样的编辑显示结果一致」，
        故本地回显改为文本编辑器式（逻辑与显示一致）。

    【渲染模型】
      - 接收到的所有字节立即实时显示（半行也显示）；只有换行符才结束当前行。
      - 行号/时间戳 = 行首现即装饰：一行第一次出现可见内容（设备半行、输入字符）
        时立即显示；输入从一开始就带行号/时间戳。
      - 自动换行 = 软换行（显示层折行），只有换行符才真实换行。
    """

    bytesOut = Signal(bytes)       # 需要立即发出到串口的原始字节
    modeChanged = Signal(str)      # 模式变化："remote" / "local"

    _MIN_LEFT_PAD_CHARS = 1        # 文本区最小内边距（字符宽度）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._encoding = "utf-8"
        self._newline = b"\r\n"                    # Enter 时发送的行尾字节
        self._echo = False                     # False=远程回显(默认) True=本地回显
        self._prefix = "> "                    # 新行输入提示符
        self._lineno_enabled = False           # 行号显示
        self._timestamp_enabled = False        # 时间戳显示
        self._ts_fmt = "s"                     # "s"=秒 / "ms"=毫秒
        self._hex_echo_enabled = False         # HEX 回显
        self._line_no = 0                      # 行号计数器
        self._row_decorated = False            # 当前行是否已装饰
        self._line = ""                        # 当前输入文本（逻辑）
        self._text_start = None                # 本地回显：输入文本起点文档位置
        # 文本编辑器式回显
        self._echo_pending = []                # 待设备确认的本地输入字符队列
        self._enter_pending = False            # 刚回车，待消费设备对回车的 \r\n 回显
        # 输入历史
        self._history = []
        self._hist_idx = -1
        self._draft = ""
        # 暂停显示（缓存而非丢弃，恢复时回放）
        self._paused = False
        self._pause_buf = []
        # 显示上限（回滚块数 / 字节数）
        self._max_blocks = 8000
        self._max_bytes = 0
        # 自动滚动增强：用户上翻时暂缓，回到底部或 5 秒后恢复
        self._scroll_hold = False
        self._scroll_resume = QTimer(self)
        self._scroll_resume.setSingleShot(True)
        self._scroll_resume.setInterval(5000)
        self._scroll_resume.timeout.connect(self._release_scroll_hold)
        self.verticalScrollBar().valueChanged.connect(self._on_vscroll_changed)
        self.setReadOnly(False)
        self.setAcceptDrops(False)
        self.setCursorWidth(2)                 # 加粗闪烁光标（竖线）
        self.setUndoRedoEnabled(False)         # 关闭撤销栈
        self.setTabChangesFocus(False)         # Tab 作为字符输入而非焦点跳转
        self.setStyleSheet("font-family:Consolas,Monaco,monospace;font-size:13px;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setViewportMargins(8, 0, 0, 0)    # 文本区最小内边距

    # ------------------------------------------------------------- 配置
    def set_echo(self, checked: bool):
        """本地回显开关（文本编辑器式）。
        关闭（默认，带回显设备）：按键始终发送、不本地渲染，显示由设备回显驱动。
        开启（不回显设备 / 需编辑反馈）：按键始终发送 + 本地金色显示 + 设备回显
        与本地输入顺序配对消费（不重复显示），编辑体验与系统文本编辑器一致。"""
        checked = bool(checked)
        if checked == self._echo:
            return
        self._echo = checked
        self._echo_pending.clear()
        self._enter_pending = False
        if checked:
            if self._line:
                self._set_line(self._line)
        else:
            self._remove_local_input()
        self.modeChanged.emit("local" if self._echo else "remote")

    def _remove_local_input(self):
        if self._text_start is None:
            return
        cur = self.textCursor()
        cur.setPosition(self._text_start)
        cur.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        self._text_start = None

    def set_encoding(self, encoding: str):
        self._encoding = encoding or "utf-8"

    def set_mode(self, mode: str):
        mode = mode.lower()
        self.set_echo(mode in ("local", "echo"))

    def mode(self) -> str:
        return "local" if self._echo else "remote"

    def set_newline_bytes(self, newline: bytes):
        self._newline = newline or b"\r\n"

    def set_prompt(self, prompt: str):
        self._prefix = (prompt + " ") if prompt else "> "

    def set_lineno(self, checked: bool):
        self._lineno_enabled = bool(checked)

    def set_timestamp(self, checked: bool):
        self._timestamp_enabled = bool(checked)

    def set_hex_echo(self, checked: bool):
        self._hex_echo_enabled = bool(checked)

    def set_timestamp_format(self, format_str: str):
        self._ts_fmt = "s" if format_str == "s" else "ms"

    # ------------------------------------------------------------- 接收渲染
    def append_rx(self, text: str, color=None, autoscroll=True):
        """追加接收/记录文本：立即实时渲染（半行也显示）。
        本地回显（文本模式）走 _render_with_echo——设备回显与本地输入
        顺序配对消费（不重复显示），退格/回车确认回显静默处理；其余模式走
        _render_text。退格 \b 统一按擦除语义处理，不再显示为空格。"""
        if not text:
            return
        text = self._normalize_unprintable(text)
        if not text:
            return
        if self._echo and not self._hex_echo_enabled:
            self._render_with_echo(text, color, autoscroll)
        else:
            self._render_text(text, color, autoscroll)
        # 每次写入后按显示上限回滚：行数/容量上限须在实时数据增长时持续生效，
        # 而非仅在 set_max_blocks/set_max_bytes 调整瞬间 trim 一次。
        self._trim()

    def _render_with_echo(self, text, color, autoscroll):
        """本地回显（文本模式）：设备回显与本地输入配对消费。
        - 可显示字符：与 _echo_pending 队首一致 → 消费（不重复显示）；
          否则作为设备新输出正常显示。
        - \b / \x08（退格擦除）：本地已处理退格，整体丢弃（含其后的空格）。
        - \r / \n：若是刚回车后设备的回车确认，消费首个换行；否则正常换行。
        """
        if self._paused:
            self._pause_buf.append((text, color))
            return
        out = []
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch == "\x08":
                i += 1
                if i < n and text[i] == " ":
                    i += 1
                continue
            if ch == "\r" or ch == "\n":
                if self._enter_pending:
                    # 消费设备对回车的确认换行
                    self._enter_pending = False
                    if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                        i += 2
                    else:
                        i += 1
                    continue
                # 换行标志输入/确认阶段结束，作废剩余待确认队列，
                # 避免残留 pending 误消费后续设备输出（如 Tab 候选列表）
                self._echo_pending.clear()
                out.append(ch)
                i += 1
                continue
            if ch.isprintable() or ch == "\t":
                if self._echo_pending and ch == self._echo_pending[0]:
                    self._echo_pending.pop(0)   # 消费设备确认回显
                    i += 1
                    continue
                # 设备回显与待确认队首不匹配 → 设备已开始输出新内容
                # （非输入确认），作废剩余待确认队列，防止后续字符被误消费丢失
                self._echo_pending.clear()
            out.append(ch)
            i += 1
        if out:
            self._render_text("".join(out), color, autoscroll)

    def _render_text(self, text, color, autoscroll):
        """实时渲染：按换行符切分逐段插入；行首现即装饰。
        退格 \x08（远程模式 / 设备历史输出）按终端语义删除文档末尾一个
        非换行字符（不再显示为空格）。"""
        if self._paused:
            self._pause_buf.append((text, color))
            return
        # 先处理退格擦除（终端语义：\b 删除末尾字符；其后的空格作为擦除填充吞掉）
        if "\x08" in text:
            out = []
            i, m = 0, len(text)
            while i < m:
                if text[i] == "\x08":
                    self._handle_erase()
                    i += 1
                    if i < m and text[i] == " ":
                        i += 1
                    continue
                out.append(text[i])
                i += 1
            text = "".join(out)
            if not text:
                return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        parts = text.split("\n")
        cur = self.textCursor()
        cur.beginEditBlock()
        try:
            for i, part in enumerate(parts):
                if part:
                    self._decorate_current_block()
                    cur.movePosition(QTextCursor.MoveOperation.End)
                    if color is None:
                        for chunk, ansi in _iter_ansi(part):
                            if chunk:
                                cur.insertText(chunk, self._format(ansi or RX_COLOR))
                    else:
                        cur.insertText(part, self._format(color))
                if i < len(parts) - 1:
                    self._finish_current_line(cur)
        finally:
            cur.endEditBlock()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cur)
        if autoscroll and not self._scroll_hold:
            self.ensureCursorVisible()

    def _handle_erase(self):
        """终端 \b 语义：删除文档末尾一个非换行字符（光标左移擦除）。
        末尾是换行符或装饰区域时静默（终端 \b 在行首无效果）。"""
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        pos = cur.position()
        if pos <= 0:
            return
        txt = self.toPlainText()
        if pos > len(txt):
            pos = len(txt)
            cur.setPosition(pos)
        # 跳过末尾换行符：\b 不删除换行
        if txt[pos - 1:pos] == "\n":
            return
        cur.movePosition(QTextCursor.MoveOperation.Left,
                         QTextCursor.MoveMode.KeepAnchor, 1)
        # 不删除行号/时间戳装饰区（装饰位于输入区起点之前时保护）
        if self._text_start is not None and cur.position() < self._text_start:
            return
        cur.removeSelectedText()

    def _finish_current_line(self, cur):
        self._decorate_current_block()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText("\n", self._base_fmt())
        self._row_decorated = False

    def _decorate_current_block(self):
        """【行首现即装饰】当前行行首显示时间戳+行号；每行仅一次。"""
        if not (self._lineno_enabled or self._timestamp_enabled):
            return False
        if self._row_decorated:
            return False
        c = QTextCursor(self.document())
        c.movePosition(QTextCursor.MoveOperation.End)
        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        segs = []
        if self._timestamp_enabled:
            segs.append((self._now_stamp(), TIMESTAMP_COLOR))
        if self._lineno_enabled:
            self._line_no += 1
            w = max(2, len(str(self._line_no)))
            segs.append((f"{self._line_no:>{w}d}  ", LINE_NO_MARKER))
        if not segs:
            return False
        total = 0
        for text, marker in segs:
            if marker == LINE_NO_MARKER:
                c.insertText(text, self._lineno_fmt())
            else:
                c.insertText(text, self._format(marker))
            total += len(text)
        if self._text_start is not None:
            self._text_start += total
        self._row_decorated = True
        return True

    @staticmethod
    def _normalize_unprintable(text: str) -> str:
        """规范化设备回显文本：控制字符的处理与键盘输入一致——不渲染任何可见标记。
        - 可显示字符原样保留
        - \t \n \r \x08 保留（终端标准控制功能：缩进/换行/退格按语义执行，
          与键盘 Enter/Backspace/Tab 的本地行为一致）
        - ANSI SGR 颜色序列（ESC[...m）整体保留（用于前景色解析）
        - 其余控制字符与控制序列（ESC[2K、ESC[A、ESC OP、单独 ESC、
          0x00-0x1F、0x7F、0x80-0x9F C1 区）一律静默丢弃——与键盘输入控制字符
          （只发送、本地不显示）保持一致，不再显示 ␛/␀ 等可见符号
        """
        if not text:
            return text
        out = []
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch == "\x1b":
                if i + 1 < n:
                    nxt = text[i + 1]
                    if nxt == "[":
                        # CSI：ESC [ 参数... 最终字节
                        j = i + 2
                        while j < n and not (0x40 <= ord(text[j]) <= 0x7E):
                            j += 1
                        if j < n:
                            j += 1
                        if text[i:j].endswith("m"):
                            out.append(text[i:j])   # SGR 颜色序列原样保留
                        i = j
                        continue
                    if nxt == "]":
                        # OSC：ESC ] ... 直到 BEL 或 ESC\
                        j = i + 2
                        while j < n:
                            if text[j] == "\x07":
                                j += 1
                                break
                            if text[j] == "\x1b" and j + 1 < n and text[j + 1] == "\\":
                                j += 2
                                break
                            j += 1
                        i = j
                        continue
                    if nxt == "O":
                        # SS3（ESC O 单字符，如 F1-F4 回显）
                        i = min(i + 3, n)
                        continue
                    # 其他两字符转义序列（ESC X）
                    i = min(i + 2, n)
                    continue
                # 单独 ESC
                i += 1
                continue
            if ch in ("\t", "\n", "\r", "\x08"):
                out.append(ch)
            else:
                code_point = ord(ch)
                is_visible_char = (code_point >= 0x20 and code_point != 0x7F
                                   and not (0x80 <= code_point <= 0x9F))
                if is_visible_char:
                    out.append(ch)
            i += 1
        return "".join(out)

    # ------------------------------------------------------------- 输入行（本地回显）
    def _ensure_input(self):
        if self._text_start is not None:
            return
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self._text_start = cur.position()

    def _type_char(self, ch: str):
        """键入字符：按键【始终发送】；本地回显模式本地金色显示，
        并把该字符记入待确认队列（设备回显时配对消费，不重复显示）。"""
        data = ch.encode(self._encoding, errors="replace")
        if not data:
            return
        self.bytesOut.emit(data)
        self._line += ch
        if self._echo:
            self._ensure_input()
            self._decorate_current_block()
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            if self._hex_echo_enabled:
                cur.insertText(data.hex(" "), self._echo_fmt())
            else:
                cur.insertText(ch, self._echo_fmt())
                self._echo_pending.append(ch)
            self.setTextCursor(cur)
            self.ensureCursorVisible()

    def _type_ctrl(self, data: bytes, name: str = ""):
        """发送不可显示的控制字符字节（方向键 ANSI 序列 ESC[A/ESC[B、
        Ctrl 控制字节 0x03/0x18/0x1a 等）。

        与可显示字符（_type_char，发送+本地回显）不同：控制字符在本地回显
        开关打开与关闭（下位机自带回显）两种模式下处理完全一致——【只发送、
        不本地渲染任何控制标记】（不显示 ^C、␀ 等文本，不换行、不清空当前
        输入行），显示效果与系统文本编辑器输入控制字符时一致，完全由设备
        回显驱动。"""
        self.bytesOut.emit(data)

    def _on_enter(self):
        """回车：发送行尾；本地回显模式本地换行并消费设备对回车的 \r\n 回显。"""
        if self._echo:
            self._ensure_input()
        self.bytesOut.emit(self._newline)
        if self._line:
            self._record(self._line)
        self._line = ""
        self._hist_idx = -1
        self._draft = ""
        if self._echo:
            self._echo_pending.clear()
            self._enter_pending = True
            cur = self.textCursor()
            self._finish_current_line(cur)
            self._text_start = None
            self.ensureCursorVisible()
        else:
            self._text_start = None

    def _on_backspace(self):
        """退格：发送 0x08；本地回显模式文本编辑器式删除本地输入末尾字符
        （设备回显的退格擦除序列在 _render_with_echo 中静默丢弃）。"""
        if not self._line:
            return
        self.bytesOut.emit(b"\x08")
        self._line = self._line[:-1]
        if self._echo:
            self._ensure_input()
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            n = 3 if self._hex_echo_enabled else 1
            cur.movePosition(QTextCursor.MoveOperation.Left,
                             QTextCursor.MoveMode.KeepAnchor, n)
            if cur.position() < self._text_start:
                cur.setPosition(self._text_start)
                cur.movePosition(QTextCursor.MoveOperation.End,
                                 QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
            self.setTextCursor(cur)
            if self._echo_pending:
                self._echo_pending.pop()
            self.ensureCursorVisible()

    def _on_clear_line(self):
        """Esc：仅清除当前输入行显示，不发送任何字节。"""
        if self._line or self._hist_idx != -1:
            self._hist_idx = -1
            self._draft = ""
            if self._line:
                self._line = ""
                if self._echo:
                    self._set_line("")

    def _set_line(self, text: str):
        self._line = text
        if not self._echo:
            return
        self._ensure_input()
        self._decorate_current_block()
        cur = self.textCursor()
        cur.setPosition(self._text_start)
        cur.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        if text:
            if self._hex_echo_enabled:
                display = text.encode(self._encoding, errors="replace").hex(" ")
            else:
                display = text
            cur.insertText(display, self._echo_fmt())
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cur)
        self.ensureCursorVisible()


    # ------------------------------------------------------------- 历史
    def _record(self, text: str):
        if text in self._history:
            self._history.remove(text)
        self._history.insert(0, text)
        self._history = self._history[:500]

    def _history_up(self):
        if not self._history:
            return
        if self._hist_idx == -1:
            self._draft = self._line
            self._hist_idx = 0
        else:
            self._hist_idx = min(self._hist_idx + 1, len(self._history) - 1)
        self._set_line(self._history[self._hist_idx])

    def _history_down(self):
        if self._hist_idx == -1:
            return
        self._hist_idx -= 1
        if self._hist_idx < 0:
            self._hist_idx = -1
            self._set_line(self._draft)
        else:
            self._set_line(self._history[self._hist_idx])

    # ------------------------------------------------------------- 控制字符
    # 普通控制键 → 标准终端控制序列（VT100/ANSI）。与可显示字符（_type_char）
    # 不同：控制字符无论本地回显控件打开与否（含下位机自带回显），处理完全一致
    # ——【只发送、不本地渲染任何控制标记】，显示效果与文本编辑器输入控制字符时
    # 一致（不产生 ^X/␀ 等文本、不换行、不清空输入行），完全由设备回显驱动。
    _CTRL_KEY_SEQS = {
        Qt.Key.Key_Up: b"\x1b[A",
        Qt.Key.Key_Down: b"\x1b[B",
        Qt.Key.Key_Right: b"\x1b[C",
        Qt.Key.Key_Left: b"\x1b[D",
        Qt.Key.Key_Home: b"\x1b[H",
        Qt.Key.Key_End: b"\x1b[F",
        Qt.Key.Key_PageUp: b"\x1b[5~",
        Qt.Key.Key_PageDown: b"\x1b[6~",
        Qt.Key.Key_Insert: b"\x1b[2~",
        Qt.Key.Key_Delete: b"\x7f",
        Qt.Key.Key_F1: b"\x1bOP",
        Qt.Key.Key_F2: b"\x1bOQ",
        Qt.Key.Key_F3: b"\x1bOR",
        Qt.Key.Key_F4: b"\x1bOS",
        Qt.Key.Key_F5: b"\x1b[15~",
        Qt.Key.Key_F6: b"\x1b[17~",
        Qt.Key.Key_F7: b"\x1b[18~",
        Qt.Key.Key_F8: b"\x1b[19~",
        Qt.Key.Key_F9: b"\x1b[20~",
        Qt.Key.Key_F10: b"\x1b[21~",
        Qt.Key.Key_F11: b"\x1b[23~",
        Qt.Key.Key_F12: b"\x1b[24~",
    }

    @staticmethod
    def _ctrl_byte(key):
        """Ctrl+键 → ASCII 控制字节（标准键盘全部 Ctrl 组合）。
        Ctrl+A-Z → 0x01-0x1A；Ctrl+@/Space/2 → NUL；Ctrl+[ 或 Ctrl+3 → ESC；
        Ctrl+\\ 或 Ctrl+4 → FS；Ctrl+] 或 Ctrl+5 → GS；Ctrl+^ 或 Ctrl+6 → RS；
        Ctrl+_ 或 Ctrl+- 或 Ctrl+7 → US；Ctrl+8 → BS；Ctrl+? 或 Ctrl+/ → DEL(0x7F)。"""
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return bytes([key & 0x1F])
        mapping = {
            Qt.Key.Key_BracketLeft: b"\x1b",   # Ctrl+[
            Qt.Key.Key_Backslash: b"\x1c",     # Ctrl+\
            Qt.Key.Key_BracketRight: b"\x1d",  # Ctrl+]
            Qt.Key.Key_2: b"\x00",             # Ctrl+2 = NUL
            Qt.Key.Key_Space: b"\x00",         # Ctrl+Space = NUL
            Qt.Key.Key_3: b"\x1b",             # Ctrl+3 = ESC
            Qt.Key.Key_4: b"\x1c",             # Ctrl+4 = FS
            Qt.Key.Key_5: b"\x1d",             # Ctrl+5 = GS
            Qt.Key.Key_6: b"\x1e",             # Ctrl+6 = RS
            Qt.Key.Key_AsciiCircum: b"\x1e",   # Ctrl+^ = RS
            Qt.Key.Key_7: b"\x1f",             # Ctrl+7 = US
            Qt.Key.Key_Minus: b"\x1f",         # Ctrl+- = US
            Qt.Key.Key_Underscore: b"\x1f",    # Ctrl+_ = US
            Qt.Key.Key_8: b"\x08",             # Ctrl+8 = BS
            Qt.Key.Key_Question: b"\x7f",      # Ctrl+? = DEL
            Qt.Key.Key_Slash: b"\x7f",         # Ctrl+/ = DEL
        }
        return mapping.get(key)


    # ------------------------------------------------------------- 键盘
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        self.moveCursor(QTextCursor.MoveOperation.End)
        ctrl_pressed = (mods & Qt.KeyboardModifier.ControlModifier)
        alt_pressed = (mods & Qt.KeyboardModifier.AltModifier)
        if ctrl_pressed and not alt_pressed:
            # Ctrl+↑/↓：浏览发送历史（普通 ↑/↓ 走下方分支发送 ANSI 方向键序列）。
            # 必须在此处理，否则会被本分支末尾的 event.ignore(); return 提前拦截。
            if key == Qt.Key.Key_Up:
                self._history_up()
                return
            if key == Qt.Key.Key_Down:
                self._history_down()
                return
            if key == Qt.Key.Key_C:
                if self.textCursor().hasSelection():
                    self.copy()
                else:
                    # 控制字符：只发送、不显示控制标记（与文本编辑器一致）
                    self._type_ctrl(b"\x03")
                return
            if key == Qt.Key.Key_V:
                from PySide6.QtWidgets import QApplication
                clip = QApplication.clipboard()
                paste_text = clip.text()
                if paste_text:
                    lines = paste_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                    if len(lines) > 1 and lines[-1] == "":
                        lines = lines[:-1]
                    for i, line in enumerate(lines):
                        for ch in line:
                            if ch.isprintable() or ch == "\t":
                                self._type_char(ch)
                        if i < len(lines) - 1:
                            self._on_enter()
                return
            if key == Qt.Key.Key_A:
                if self._text_start is not None:
                    cur = self.textCursor()
                    cur.setPosition(self._text_start)
                    cur.movePosition(QTextCursor.MoveOperation.End,
                                     QTextCursor.MoveMode.KeepAnchor)
                    self.setTextCursor(cur)
                else:
                    self.moveCursor(QTextCursor.MoveOperation.End)
                return
            if key == Qt.Key.Key_X:
                if (self.textCursor().hasSelection()
                        and self._text_start is not None
                        and self.textCursor().selectionStart() >= self._text_start):
                    self.cut()
                    cur = self.textCursor()
                    cur.setPosition(self._text_start)
                    cur.movePosition(QTextCursor.MoveOperation.End,
                                     QTextCursor.MoveMode.KeepAnchor)
                    self._line = cur.selectedText()
                else:
                    # 控制字符：只发送、不显示控制标记（与文本编辑器一致）
                    self._type_ctrl(b"\x18")
                return
            if key == Qt.Key.Key_Z:
                # 控制字符：只发送、不显示控制标记（与文本编辑器一致）
                self._type_ctrl(b"\x1a")
                return
            byte = self._ctrl_byte(key)
            if byte is not None:
                # 控制字符：只发送、不显示控制标记（与文本编辑器一致）
                self._type_ctrl(byte)
                return
            event.ignore()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_enter()
            return
        if key == Qt.Key.Key_Backspace:
            self._on_backspace()
            return
        if key == Qt.Key.Key_Escape:
            self._on_clear_line()
            return
        if key == Qt.Key.Key_Tab:
            # Tab 在文本编辑器中产生可见缩进 → 按可显示字符处理（发送+回显）
            self._type_char("\t")
            return
        # 不可显示的控制字符（方向键/Home/End/PgUp/PgDn/Insert/Delete/F1-F12）：
        # 发送标准终端控制序列，本地不渲染任何控制标记——本地回显控件打开与否
        # （含下位机自带回显）处理完全一致，显示效果与文本编辑器输入一致。
        # （Ctrl+↑/↓ 的历史浏览已在 Ctrl 分支处理，不在此发送）
        seq = self._CTRL_KEY_SEQS.get(key)
        if seq is not None:
            self._type_ctrl(seq)
            return
        text = event.text()
        if text and not (mods & (Qt.KeyboardModifier.ControlModifier |
                                 Qt.KeyboardModifier.AltModifier |
                                 Qt.KeyboardModifier.MetaModifier)):
            for ch in text:
                if ch.isprintable() or ch == "\t":
                    self._type_char(ch)

    # ------------------------------------------------------------- 滚动/暂停/上限
    def _on_vscroll_changed(self, value):
        if value >= self.verticalScrollBar().maximum():
            self._release_scroll_hold()
        else:
            self._scroll_hold = True
            if not self._scroll_resume.isActive():
                self._scroll_resume.start()

    def _release_scroll_hold(self):
        self._scroll_hold = False
        self._scroll_resume.stop()

    def shutdown(self):
        """窗口关闭前停止本控件所有计时器（BUG-O 清理）。"""
        self._scroll_resume.stop()
        self._scroll_hold = False

    def set_paused(self, on: bool):
        """暂停/继续实时渲染：暂停时接收内容暂存缓冲，恢复后按序补显。"""
        self._paused = bool(on)
        if not self._paused and self._pause_buf:
            buffer = self._pause_buf
            self._pause_buf = []
            for text, color in buffer:
                self._render_text(text, color, True)

    def set_max_blocks(self, n: int):
        self._max_blocks = max(100, int(n))
        self._trim()

    def set_max_bytes(self, n: int):
        self._max_bytes = max(0, int(n))
        self._trim()

    def max_blocks(self) -> int:
        return self._max_blocks

    def reset(self):
        """清空终端全部显示与输入/历史状态（回到初始空态）。"""
        self._pause_buf.clear()
        self._paused = False
        self.clear()
        self._line = ""
        self._text_start = None
        self._hist_idx = -1
        self._draft = ""
        self._line_no = 0
        self._row_decorated = False
        self._echo_pending.clear()
        self._enter_pending = False

    def flush_pending(self):
        pass

    # ------------------------------------------------------------- 格式
    def _base_fmt(self):
        f = QTextCharFormat()
        f.setForeground(self.palette().color(QPalette.ColorRole.Text))
        return f

    @staticmethod
    def _format(color):
        f = QTextCharFormat()
        f.setForeground(QColor(color))
        return f

    def _echo_fmt(self):
        return self._format(ECHO_COLOR)

    def _prompt_fmt(self):
        return self._format(PROMPT_COLOR)

    def _lineno_fmt(self):
        f = self._format(LINENO_COLOR)
        f.setBackground(self.palette().color(QPalette.ColorRole.AlternateBase))
        return f

    def _now_stamp(self):
        import time as _time
        t = _time.time()
        base = _time.strftime("[%H:%M:%S", _time.localtime(t))
        if self._ts_fmt == "s":
            return base + "] "
        return base + f".{int(t * 1000) % 1000:03d}] "

    # ------------------------------------------------------------- 内部工具
    def _trim(self):
        doc = self.document()
        while self._max_blocks > 0 and doc.blockCount() > self._max_blocks:
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.Start)
            cur.movePosition(QTextCursor.MoveOperation.NextBlock,
                             QTextCursor.MoveMode.KeepAnchor)
            removed = len(cur.block().text()) + 1
            cur.removeSelectedText()
            self._shift_text_start(-removed)
        while self._max_bytes > 0 and doc.characterCount() > self._max_bytes:
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.Start)
            cur.movePosition(QTextCursor.MoveOperation.NextBlock,
                             QTextCursor.MoveMode.KeepAnchor)
            removed = len(cur.block().text()) + 1
            cur.removeSelectedText()
            self._shift_text_start(-removed)

    def _shift_text_start(self, delta):
        if self._text_start is not None:
            self._text_start = max(0, self._text_start + delta)

