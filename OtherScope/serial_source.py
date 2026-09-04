# -*- coding: utf-8 -*-
"""串口枚举、串口收发线程、以及免硬件的虚拟数据源。"""

from __future__ import annotations

import math
import os
import random
import socket
import threading

import serial
from serial.tools import list_ports
from PySide6.QtCore import QThread, Signal

BAUDRATES = [300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400,
             57600, 115200, 230400, 460800, 921600]

PARITIES = {"无校验 (None)": "N", "偶校验 (Even)": "E", "奇校验 (Odd)": "O",
            "标记 (Mark)": "M", "空格 (Space)": "S"}
STOP_BITS = {"1": 1.0, "1.5": 1.5, "2": 2.0}
FLOWS = {"无": "none", "RTS/CTS": "rts", "XON/XOFF": "xon"}


def list_serial_ports():
    """返回 [(device, description, hwid), ...]，供 UI 下拉框使用。

    先走系统枚举（含描述信息），单条失败不影响其余端口；若系统枚举漏报
    （部分虚拟串口/非标准驱动不写入注册表），在 Windows 上再直连探测
    COM1~COM256 兜底，与 SSCOM 的识别方式一致，保证端口不被遗漏。
    """
    result = []
    seen = set()

    def _add(device, desc="", hwid=""):
        if not device:
            return
        key = device.upper() if os.name == "nt" else device
        if key in seen:
            return
        seen.add(key)
        result.append((device, desc, hwid))

    # 1) 系统枚举：per-port 容错，单个损坏条目不会拖垮整次枚举
    try:
        for p in list_ports.comports():
            try:
                _add(p.device, p.description or "", p.hwid or "")
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass    # comports() 全局异常时靠下方直连探测兜底

    # 2) Windows 直连探测兜底：SSCOM 同款做法，逐个试用打开 COMx
    if os.name == "nt":
        for idx in range(1, 257):
            name = f"COM{idx}"
            if name.upper() in seen:
                continue
            try:
                sock = serial.Serial(port=name, timeout=0, write_timeout=0)
                sock.close()
                _add(name)
            except Exception:  # noqa: BLE001
                continue
    return result


class _DataSource(QThread):
    """数据源基类：子线程持续产生字节流。"""

    data = Signal(bytes)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()
        self.requestInterruption()

    def write(self, payload: bytes) -> bool:
        """默认接受写入（虚拟源等）；真实串口覆盖实现。"""
        return True

    def set_signal(self, dtr=None, rts=None) -> bool:
        """配置虚拟信号发生器的波形参数（基准/幅值/频率/相位/占空比）。"""
        return False


class SerialSource(_DataSource):
    """真实串口数据源。"""

    def __init__(self, port, baudrate=115200, bytesize=8, parity="N",
                 stopbits=1.0, flow="none", dtr=None, rts=None, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = int(baudrate)
        self.bytesize = int(bytesize)
        self.parity = parity
        self.stopbits = float(stopbits)
        self.flow_control = flow
        self.dtr = dtr      # 打开后要施加的 DTR / RTS 电平（None=不修改）
        self.rts = rts
        self._serial = None
        self._lock = threading.Lock()

    def run(self):
        """串口接收线程主循环：打开端口→持续读取→发射 data 信号，退出时释放句柄。"""
        try:
            kwargs = dict(port=self.port, baudrate=self.baudrate,
                          bytesize=self.bytesize, timeout=0.02, write_timeout=0.1)
            kwargs["parity"] = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                                "O": serial.PARITY_ODD, "M": serial.PARITY_MARK,
                                "S": serial.PARITY_SPACE}[self.parity]
            kwargs["stopbits"] = {1.0: serial.STOPBITS_ONE,
                                  1.5: serial.STOPBITS_ONE_POINT_FIVE,
                                  2.0: serial.STOPBITS_TWO}[self.stopbits]
            self._serial = serial.Serial(**kwargs)
            if self.flow_control in ("rts", "rtscts"):
                self._serial.rtscts = True
            elif self.flow_control == "xon":
                self._serial.xonxoff = True
            if self.dtr is not None:
                self._serial.dtr = bool(self.dtr)
            if self.rts is not None:
                self._serial.rts = bool(self.rts)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            # 打开成功但流控/控制线设置失败时，关闭已打开的句柄，避免端口泄漏
            try:
                if self._serial is not None and self._serial.is_open:
                    self._serial.close()
            except Exception:  # noqa: BLE001
                pass
            self._serial = None
            return

        try:
            while not (self._stop_evt.is_set() or self.isInterruptionRequested()):
                try:
                    with self._lock:
                        if self._serial is None or not self._serial.is_open:
                            break
                        n = self._serial.in_waiting
                        chunk = self._serial.read(n) if n else b""
                    if chunk:
                        self.data.emit(chunk)
                    else:
                        self._stop_evt.wait(0.005)
                except Exception as exc:  # noqa: BLE001
                    self.error.emit(str(exc))
                    break
        finally:
            # 与 write()/set_signal() 共用同一把锁，保证关闭与读写互斥
            with self._lock:
                try:
                    if self._serial is not None and self._serial.is_open:
                        self._serial.close()
                except Exception:  # noqa: BLE001
                    pass
                self._serial = None

    def write(self, payload: bytes) -> bool:
        """向串口写入数据（锁外执行 write，避免硬件流控阻塞读线程）。"""
        if self._stop_evt.is_set():
            return False
        # BUG-04 修复：pyserial 的 Serial 对象 read/write 内部已线程安全，
        # 原实现把 write 放在 _lock 内，硬件流控下 write 阻塞会卡死读线程。
        # 现仅在锁内获取 ser 引用，锁外执行 write，读写互不阻塞。
        with self._lock:
            ser = self._serial
            if ser is None or not ser.is_open:
                return False
        try:
            ser.write(payload)
            return True
        except Exception as exc:  # noqa: BLE001
            # 必须在锁外 emit：error 槽会走 GUI 关闭流程（wait/close），
            # 若持锁同步重入会与读线程死锁，最终触发 terminate() 导致句柄泄漏
            self.error.emit(str(exc))
            return False

    def set_signal(self, dtr=None, rts=None) -> bool:
        """设置 DTR/RTS 控制线（None 表示保持不变）。"""
        err = None
        ok = False
        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    if dtr is not None:
                        self._serial.dtr = bool(dtr)
                    if rts is not None:
                        self._serial.rts = bool(rts)
                    ok = True
                except Exception as exc:  # noqa: BLE001
                    err = str(exc)
        if err is not None:
            self.error.emit(err)
        return ok


class VirtualSource(_DataSource):
    """虚拟数据源：无硬件即可测试波形与 FFT。

    以固定速率输出一行 8 通道数据，与默认格式串 ``DEMO_FORMAT`` 匹配。
    各通道直流偏移 / 幅度 / 主频 / 次频均不同，开箱即可看到 8 条独立波形，
    任选任一通道做 FFT 都能看到对应频率峰值。
    """

    # 每通道：[直流偏移, 幅度(主频), 主频Hz, 幅度(次频，0 表示不叠加), 次频Hz]
    _CHANS = [
        (120.0, 30.0, 5.0, 8.0, 37.0),     # ch1
        (60.0, 25.0, 12.0, 0.0, 0.0),      # ch2
        (-20.0, 40.0, 3.0, 0.0, 0.0),      # ch3
        (90.0, 20.0, 25.0, 0.0, 0.0),      # ch4
        (150.0, 15.0, 50.0, 5.0, 2.0),     # ch5
        (30.0, 35.0, 8.0, 0.0, 0.0),       # ch6
        (100.0, 10.0, 17.0, 0.0, 0.0),     # ch7
        (200.0, 22.0, 33.0, 0.0, 0.0),     # ch8
    ]

    def __init__(self, rate=400.0, parent=None, baud=115200, bits_per_byte=10):
        super().__init__(parent)
        # rate 是「行速率上界」（限速用，Hz），不是实际输出速率。
        # 实际输出速率由串行时钟 baud/bits_per_byte 决定；rate 仅用于避免 UI 被
        # 过高峰值刷爆，设为 0 则不限速。命名保留兼容，勿误解为采样率。
        self.rate = max(1.0, float(rate))
        self.baud = int(baud)                       # 虚拟串行链路波特率
        self.bits_per_byte = int(bits_per_byte)     # 每字节比特数（含起始/停止/校验）
        self._serial_clock = 0.0                    # 串行时钟（秒，按字节累计）

    def _sample_line(self, t):
        """按当前时间 t 生成一行 8 通道文本（含行尾），供 run() 与自检复用。"""
        parts = []
        for i, (off, a1, f1, a2, f2) in enumerate(self._CHANS, start=1):
            v = off + a1 * math.sin(2 * math.pi * f1 * t)
            if a2:
                v += a2 * math.sin(2 * math.pi * f2 * t)
            v += random.uniform(-0.5, 0.5)   # 每通道轻噪声，贴近真实信号
            parts.append(f"ch{i}:{v:.1f}mv")
        return ",".join(parts) + "\n"

    def run(self):
        """虚拟源线程主循环：按串行节拍持续生成 8 通道波形行并发射 data 信号。

        每行按「字节数 × 每字节耗时」推进串行时钟，与主窗口按字节偏移计算
        时间戳严格一致，输出波形频率即串行时钟频率。
        """
        # 虚拟源模拟一条真实的串行链路：每行按「字节数 × 每字节耗时」推进串行时钟，
        # 与主窗口的接收端按字节偏移计算时间戳严格一致，输出波形频率即串行时钟频率。
        while not self._stop_evt.is_set():
            line = self._sample_line(self._serial_clock)
            data = line.encode("utf-8")
            self.data.emit(data)
            byte_time = len(data) * self.bits_per_byte / self.baud
            self._serial_clock += byte_time
            # 以真实串行节拍限速（近似），避免 UI 被过高峰值刷爆；取消限速也不影响时钟正确性
            delay = min(byte_time, 1.0 / self.rate) if self.rate > 0 else byte_time
            self._stop_evt.wait(delay)


# 虚拟源输出的默认格式串（8 通道）。主窗口据此初始化解析器与格式输入框。
DEMO_FORMAT = ("ch1:%fmv,ch2:%fmv,ch3:%fmv,ch4:%fmv,"
               "ch5:%fmv,ch6:%fmv,ch7:%fmv,ch8:%fmv")

class NetSource(_DataSource):
    """网口数据源：TCP Client / TCP Server / UDP。

    与 SerialSource 接口完全一致（data/error 信号 + write()/stop()/QThread.finished），
    因此主窗口把 `self.source` 统一指向 SerialSource 或 NetSource 后，
    接收/解码/终端显示/波形解析/发送/回显等既有数据管线【完全复用、零改动】。
    网口与串口互斥：同一时刻只允许打开其中一种（由主窗口 UI 层强制）。
    """

    def __init__(self, proto="tcp_client", host="127.0.0.1", port=23,
                 local_ip="0.0.0.0", local_port=23, parent=None):
        super().__init__(parent)
        self.proto = proto                 # "tcp_client" / "tcp_server" / "udp"
        self.host = host or "127.0.0.1"
        self.port = int(port)
        self.local_ip = local_ip or "0.0.0.0"   # 本地监听/绑定 IP（TCP Server / UDP）
        self.local_port = int(local_port)
        self._sock = None                  # 当前套接字（client 连接 / server 监听 / udp 绑定）
        self._client = None                # tcp_server 模式下已接受的客户端套接字
        self._peer = (self.host, self.port)  # udp 发送目标
        self._lock = threading.Lock()

    # ---------------- 发送 ----------------
    def write(self, payload: bytes) -> bool:
        with self._lock:
            try:
                if self.proto == "udp":
                    sock = self._sock
                    if sock is None:
                        return False
                    sock.sendto(payload, self._peer)
                    return True
                # tcp_client / tcp_server
                sock = (self._client
                        if (self.proto == "tcp_server" and self._client)
                        else self._sock)
                if sock is None:
                    return False
                sock.sendall(payload)
                return True
            except Exception:  # noqa: BLE001
                return False

    # ---------------- 线程主循环 ----------------
    def run(self):
        """网口线程主循环：按协议（TCP 客户端/服务端/UDP）建立连接并持续接收。"""
        import socket
        try:
            if self.proto == "tcp_client":
                self._run_tcp_client(socket)
            elif self.proto == "tcp_server":
                self._run_tcp_server(socket)
            else:
                self._run_udp(socket)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        finally:
            self._close_sock()

    def _recv_loop(self, sock, timeout):
        """通用接收循环：把收到的字节发到 data 信号。"""
        sock.settimeout(timeout)
        while not self._stop_evt.is_set():
            try:
                data = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self.data.emit(data)

    def _run_tcp_client(self, socket):
        sock = socket.create_connection((self.host, self.port), timeout=3.0)
        self._sock = sock
        self._recv_loop(sock, 0.1)

    def _run_tcp_server(self, socket):
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_sock.bind((self.local_ip, self.local_port))
        listen_sock.listen(1)
        listen_sock.settimeout(0.2)
        self._sock = listen_sock
        client = None
        # 等待客户端接入；可被 stop() 打断
        while not self._stop_evt.is_set():
            try:
                client, _addr = listen_sock.accept()
                break
            except socket.timeout:
                continue
        if client is None:
            return
        self._client = client
        try:
            self._recv_loop(client, 0.1)
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _run_udp(self, socket):
        """UDP 接收循环：绑定本地端口，非阻塞接收数据报并回填数据队列。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.local_ip, self.local_port))
        sock.settimeout(0.1)
        self._sock = sock
        while not self._stop_evt.is_set():
            try:
                data, _addr = sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            self.data.emit(data)

    def _close_sock(self):
        with self._lock:
            for sock in (self._client, self._sock):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            self._client = None
            self._sock = None
