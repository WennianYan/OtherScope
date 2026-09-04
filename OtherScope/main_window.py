# -*- coding: utf-8 -*-
"""主窗口：菜单栏 + 收发合一终端 + 波形格式配置 + 波形面板与 FFT 面板。

关键设计：
- 收发合并到单一终端面板（cmd 风格）：底部输入行回车即发，接收/本地回显写入同一日志区。
- 波形时间轴按通讯接口速率精确计算：串口按「波特率 × 每字节比特数 × 接收字节偏移」。
- 全界面国际化：简体中文 / English，默认跟随系统，菜单栏可切换。
"""

from __future__ import annotations

import codecs
import os
import traceback as _tb
from collections import deque

crash_log_dir = os.path.dirname(os.path.abspath(__file__))
_CRASH_LOG_PATH = os.path.join(crash_log_dir, "..", "OtherScope_crash.log")


def _log_main_error(where: str):
    """记录主窗口路径上的未捕获异常到崩溃日志（不向上抛，避免 Qt 崩溃闪退）。"""
    try:
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as file_handle:
            file_handle.write(f"\n==== 主窗口异常 @ {where} ====\n")
            _tb.print_exc(file=file_handle)
    except Exception:
        pass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QLineEdit, QTabWidget, QSplitter,
    QGroupBox, QMessageBox, QFileDialog, QMainWindow, QDialog, QTextBrowser,
    QMenu, QApplication, QSpinBox)

from .translations import tr, trf, set_language, current_lang, LANG_ZH, LANG_EN
from .state_save import AppConfig, ScopeState
from .app_theme import ThemeManager, THEME_DARK, THEME_LIGHT
from .user_manual import manual_html
from .printf_parser import FrameParser
from .serial_source import (BAUDRATES, STOP_BITS,
                             list_serial_ports, SerialSource, VirtualSource,
                             NetSource, DEMO_FORMAT)
from .oscilloscope import WaveformPanel, DistPanel
from .fft_spectrum import FftSpectrumPanel
from .data_hub import DataHub
from .numeric_controls import PlusMinusBox
from .hover_help import install_hover_help, state_text, shutdown_hover
from .communication_terminal import (QuickSendBar, SendEdit, InstantTerminal, ECHO_COLOR,
                       RX_COLOR,
                       newline_bytes, hex_to_bytes, interpret_escapes,
                       compute_checksum, checksum_labels, CHECKSUM_NONE)


# 语言敏感的选项：value 为稳定码，display 为 i18n key（None 表示文字原样）
_PARITY_OPTIONS = [("N", "serial.parity.none"), ("E", "serial.parity.even"),
                   ("O", "serial.parity.odd"), ("M", "serial.parity.mark"),
                   ("S", "serial.parity.space")]
_FLOW_OPTIONS = [("none", "serial.flow.none"), ("rts", "serial.flow.rts"),
                 ("xon", "serial.flow.xon")]
_NEWLINE_OPTIONS = [("无", "terminal.newline.none"), ("\\r\\n", None),
                    ("\\n", None), ("\\r", None)]


def _default_newline() -> str:
    """系统默认回车/行尾字节：Windows → \r\n，Linux/macOS → \n。
    用于「回车行尾」「行尾」控件首次运行时的默认值（用户手动选择后以用户为准）。"""
    import platform
    sysname = platform.system()
    if sysname == "Windows":
        return "\\r\\n"
    return "\\n"
# 校验算法用 terminal.py 的全量列表 checksum_labels()（覆盖全球已公开算法），
# 此处不再维护精简常量，避免遗漏。


def _combo_text(code, key):
    return tr(key) if key else code


class MainWindow(QMainWindow):
    """主窗口：串口/网口通讯终端 + 波形示波器 + FFT + 分布统计四页签。

    数据流唯一入口：串口/网口收到的原始字节流经 _handle_line 解析，
    通过 DataHub.append_frame 写入环形 FIFO；波形/FFT/分布各窗口均从
    DataHub 读取耦合后的数据渲染，保证多页面数据同源一致。
    """

    def __init__(self):
        super().__init__()
        self.resize(1320, 900)
        self.setMinimumSize(1024, 700)  # 限制最小尺寸，避免布局计算过大

        self.parser = FrameParser(DEMO_FORMAT)
        self.source = None
        self.opened = False
        self._decimals = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._rx_bytes = 0              # 显示用接收字节计数
        self._tx_bytes = 0              # 显示用发送字节计数
        self._hex_tx_source = ""        # HEX 发送勾选前的源字符串（取消 HEX 时恢复显示用）
        # SOP-06 Hex 转储：累积字节按列宽分页输出（偏移+Hex+ASCII），偏移自打开串口/清屏累计
        self._hex_buf = bytearray()      # 待分页的 hex 字节
        self._hex_offset = 0             # 已输出行的字节偏移
        self._hex_cols = 16              # 每行字节数（SOP 支持 8/16/24/32）
        # SOP V3.0：时间戳默认秒级 [HH:mm:ss]（WindTerm 默认），毫秒为可选项
        self._ts_fmt = "s"
        # 精确时序：按接口速率计算的串行时钟
        self._t_per_byte = 1e-3         # 每字节耗时（秒），打开串口时按参数计算
        self._t_baud = 115200           # 当前会话真实波特率（虚拟源固定 115200）
        self._session_bytes = 0         # 本会话累计接收字节数（连续，不随清屏重置）
        self._tim_buf = bytearray()     # 待切行的原始字节缓冲（用于字节级精确时间戳）
        # 原始行环形缓冲：格式串变化时据此重新解析已收数据重绘波形
        self._raw_lines = deque(maxlen=50_000)
        # 文件分块发送状态
        self._file_send_fh = None
        self._file_send_sent = 0
        self._file_send_total = 0
        self._periodic_active = False  # 周期发送进行中标志（延时发送期间）

        self._build_menu()
        self._build_ui()
        self.theme = ThemeManager(QApplication.instance())
        self.theme.register(self.waveform)
        self.theme.register(self.fft_panel)
        self.theme.register(self.dist_panel)
        self.theme.apply(THEME_DARK)
        self._refresh_ports()
        self._apply_format()
        self._retranslate()
        self._load_config()

    # ---------------------------------------------------------------- 菜单
    def _build_menu(self):
        menu_bar = self.menuBar()

        self.menu_file = menu_bar.addMenu("")
        self.act_save_rx = QAction(self)
        self.act_save_rx.triggered.connect(self._save_rx)
        self.menu_file.addAction(self.act_save_rx)
        self.act_send_file = QAction(self)
        self.act_send_file.triggered.connect(self._send_file)
        self.menu_file.addAction(self.act_send_file)
        self.act_export_csv = QAction(self)
        self.act_export_csv.triggered.connect(
            self.waveform.export_csv if hasattr(self, "waveform") else lambda: None)
        # 占位：导出动作在 _build_ui 后重新绑定，避免波形尚未构建
        self.menu_file.addAction(self.act_export_csv)
        self.menu_file.addSeparator()
        self.act_exit = QAction(self)
        self.act_exit.triggered.connect(self.close)
        self.menu_file.addAction(self.act_exit)

        self.menu_view = menu_bar.addMenu("")
        self.act_view_terminal = QAction(self)
        self.act_view_waveform = QAction(self)
        self.act_view_fft = QAction(self)
        self.act_view_dist = QAction(self)
        self.menu_view.addAction(self.act_view_terminal)
        self.menu_view.addAction(self.act_view_waveform)
        self.menu_view.addAction(self.act_view_fft)
        self.menu_view.addAction(self.act_view_dist)
        self.menu_view.addSeparator()
        self.menu_theme = self.menu_view.addMenu("")
        self.act_theme_dark = QAction(self)
        self.act_theme_light = QAction(self)
        self.act_theme_dark.setCheckable(True)
        self.act_theme_light.setCheckable(True)
        self.theme_group = QActionGroup(self)
        self.theme_group.addAction(self.act_theme_dark)
        self.theme_group.addAction(self.act_theme_light)
        self.act_theme_dark.triggered.connect(lambda: self._set_theme(THEME_DARK))
        self.act_theme_light.triggered.connect(lambda: self._set_theme(THEME_LIGHT))
        self.menu_theme.addAction(self.act_theme_dark)
        self.menu_theme.addAction(self.act_theme_light)

        self.menu_lang = menu_bar.addMenu("")
        self.act_lang_zh = QAction(self)
        self.act_lang_en = QAction(self)
        self.act_lang_zh.setCheckable(True)
        self.act_lang_en.setCheckable(True)
        self.lang_group = QActionGroup(self)
        self.lang_group.addAction(self.act_lang_zh)
        self.lang_group.addAction(self.act_lang_en)
        self.act_lang_zh.triggered.connect(lambda: self._set_language(LANG_ZH))
        self.act_lang_en.triggered.connect(lambda: self._set_language(LANG_EN))
        self.menu_lang.addAction(self.act_lang_zh)
        self.menu_lang.addAction(self.act_lang_en)

        # 设置 -> 通讯接口（串口/网口），替代原「通讯方式」控件
        self.menu_settings = menu_bar.addMenu("")
        self.menu_comm = self.menu_settings.addMenu("")
        self.act_comm_serial = QAction(self)
        self.act_comm_net = QAction(self)
        self.act_comm_serial.setCheckable(True)
        self.act_comm_net.setCheckable(True)
        self.comm_group = QActionGroup(self)
        self.comm_group.addAction(self.act_comm_serial)
        self.comm_group.addAction(self.act_comm_net)
        self.act_comm_serial.triggered.connect(lambda: self._set_comm_mode(False))
        self.act_comm_net.triggered.connect(lambda: self._set_comm_mode(True))
        self.menu_comm.addAction(self.act_comm_serial)
        self.menu_comm.addAction(self.act_comm_net)

        self.menu_help = menu_bar.addMenu("")
        self.act_manual = QAction(self)
        self.act_manual.triggered.connect(self._show_manual)
        self.menu_help.addAction(self.act_manual)
        self.act_about = QAction(self)
        self.act_about.triggered.connect(self._show_about)
        self.menu_help.addAction(self.act_about)

    def _set_language(self, lang):
        if lang == current_lang():
            return
        set_language(lang)
        self.parser = FrameParser(self.parser.format)   # 无副作用重建，保持格式
        self._retranslate()
        self._refresh_ports()

    def _set_theme(self, theme):
        if not hasattr(self, "theme") or theme == self.theme.theme:
            return
        self.theme.apply(theme)
        self.act_theme_dark.setChecked(theme == THEME_DARK)
        self.act_theme_light.setChecked(theme == THEME_LIGHT)

    def _show_manual(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("manual.title"))
        dialog.resize(920, 680)
        lay = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(manual_html(current_lang() == LANG_ZH))
        browser.setOpenExternalLinks(False)
        lay.addWidget(browser)

        def _toggle_fullscreen():
            if dialog.isFullScreen():
                dialog.showNormal()
                dialog.resize(920, 680)
                btn_full.setText(tr("common.fullscreen"))
            else:
                dialog.showFullScreen()
                btn_full.setText(tr("common.exit_fullscreen"))

        btns = QHBoxLayout()
        btn_full = QPushButton(tr("common.fullscreen"))
        btn_full.clicked.connect(_toggle_fullscreen)
        btns.addWidget(btn_full)
        btns.addStretch(1)
        btn = QPushButton(tr("common.close"))
        btn.clicked.connect(dialog.accept)
        btns.addWidget(btn)
        lay.addLayout(btns)
        dialog.exec()

    def _show_about(self):
        """关于对话框：完整软件信息（名称 / 版本 / 版权 / 许可证 / 源码链接）。

        版本号统一取自 __version__（单一来源，避免与界面文案漂移）。
        """
        from . import __version__
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPushButton,
                                       QHBoxLayout, QTextBrowser)
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("about.title"))
        dialog.setMinimumWidth(480)
        dialog.setMinimumHeight(420)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(20, 16, 20, 12)
        lay.setSpacing(8)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        about_html = tr("about.content").replace("{VERSION}", __version__)
        browser.setHtml(about_html)
        browser.setStyleSheet("QTextBrowser{background:transparent;border:none;}")
        lay.addWidget(browser, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn = QPushButton(tr("common.ok"))
        btn.clicked.connect(dialog.accept)
        btns.addWidget(btn)
        lay.addLayout(btns)
        dialog.exec()

    # ---------------------------------------------------------------- 界面
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        # DataHub 数据总线：通讯终端（串口/网口）是唯一写入方，波形/FFT/分布图三个窗口只读。
        self.dh = DataHub(self)
        self.tab_widget = QTabWidget()
        root.addWidget(self.tab_widget)
        self.tab_widget.addTab(self._build_terminal_tab(), "")
        self.tab_widget.addTab(self._build_wave_tab(), "")
        self.tab_widget.addTab(self._build_fft_tab(), "")
        self.tab_widget.addTab(self._build_dist_tab(), "")

        # 视图菜单切换页签（终端0 波形1 FFT2 分布图3）
        self.act_view_terminal.triggered.connect(lambda: self.tab_widget.setCurrentIndex(0))
        self.act_view_waveform.triggered.connect(lambda: self.tab_widget.setCurrentIndex(1))
        self.act_view_fft.triggered.connect(lambda: self.tab_widget.setCurrentIndex(2))
        self.act_view_dist.triggered.connect(lambda: self.tab_widget.setCurrentIndex(3))
        # 导出波形 CSV 绑定到已构建的波形面板
        self.act_export_csv.triggered.disconnect()
        self.act_export_csv.triggered.connect(self.waveform.export_csv)

    def _build_terminal_tab(self):
        tab = QWidget()
        vbox = QVBoxLayout(tab)

        # 通讯方式改由菜单「设置 -> 通讯接口」选择（串口/网口互斥）。
        # cb_proto 作为内部模式状态保留（currentData()=="net" 即网口），但不加入
        # 任何布局、不在界面显示，原「通讯方式」GroupBox 及其控件已移除。
        self.cb_proto = QComboBox()
        self.cb_proto.addItem(tr("net.proto_serial"), "serial")
        self.cb_proto.addItem(tr("net.proto_net"), "net")
        self.cb_proto.currentIndexChanged.connect(self._on_proto_changed)

        # 串口配置（紧凑 2 行布局）
        self.grp_serial = QGroupBox()
        grid_serial = QGridLayout(self.grp_serial)
        # 第1行：串口 / 刷新 / 波特率 / 数据位 / 停止位 / 校验
        self.lb_port = QLabel()
        grid_serial.addWidget(self.lb_port, 0, 0)
        self.cb_port = QComboBox()
        grid_serial.addWidget(self.cb_port, 0, 1)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self._refresh_ports)
        grid_serial.addWidget(self.btn_refresh, 0, 2)
        self.lb_baud = QLabel()
        grid_serial.addWidget(self.lb_baud, 0, 3)
        self.cb_baud = QComboBox()
        self.cb_baud.addItems([str(b) for b in BAUDRATES])
        self.cb_baud.setCurrentText("115200")
        grid_serial.addWidget(self.cb_baud, 0, 4)
        self.lb_data = QLabel()
        grid_serial.addWidget(self.lb_data, 0, 5)
        self.cb_data = QComboBox()
        self.cb_data.addItems(["8", "7", "6", "5"])
        grid_serial.addWidget(self.cb_data, 0, 6)
        self.lb_stop = QLabel()
        grid_serial.addWidget(self.lb_stop, 0, 7)
        self.cb_stop = QComboBox()
        for label, val in STOP_BITS.items():
            self.cb_stop.addItem(label, val)
        self.cb_stop.setCurrentText("1")
        grid_serial.addWidget(self.cb_stop, 0, 8)
        self.lb_parity = QLabel()
        grid_serial.addWidget(self.lb_parity, 0, 9)
        self.cb_parity = QComboBox()
        # 校验下拉选项左移贴近下拉框 —— 宽度随内容自适应（AdjustToContents），
        # 不在宽列中被拉伸，选项文本紧贴下拉框左边缘
        self.cb_parity.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        grid_serial.addWidget(self.cb_parity, 0, 10)
        # 第2行：流控 / 编码 / 控制线(DTR RTS)
        self.lb_flow = QLabel()
        grid_serial.addWidget(self.lb_flow, 1, 0)
        self.cb_flow = QComboBox()
        grid_serial.addWidget(self.cb_flow, 1, 1)
        self.lb_enc = QLabel()
        grid_serial.addWidget(self.lb_enc, 1, 2)
        self.cb_enc = QComboBox()
        self.cb_enc.addItems(["utf-8", "gbk", "ascii", "latin-1"])
        self.cb_enc.currentTextChanged.connect(self._on_enc_changed)
        grid_serial.addWidget(self.cb_enc, 1, 3)
        self.lb_ctrl = QLabel()
        grid_serial.addWidget(self.lb_ctrl, 1, 4)
        self.chk_dtr = QCheckBox("DTR")
        self.chk_dtr.setChecked(True)
        self.chk_dtr.toggled.connect(self._on_dtr_rts)
        grid_serial.addWidget(self.chk_dtr, 1, 5)
        self.chk_rts = QCheckBox("RTS")
        self.chk_rts.toggled.connect(self._on_dtr_rts)
        grid_serial.addWidget(self.chk_rts, 1, 6)
        # 串口打开/关闭控件移到控制线 RTS 后面
        self.btn_open_serial = QPushButton()
        self.btn_open_serial.clicked.connect(self._toggle_open)
        self.lb_open_state_serial = QLabel()
        grid_serial.addWidget(self.btn_open_serial, 1, 7)
        grid_serial.addWidget(self.lb_open_state_serial, 1, 8)
        # stretch 列从 9 移到 11 —— 列 9 是「校验」标签列(0,9)，
        # 原 setColumnStretch(9,1) 会拉伸该校验标签列，把校验下拉(0,10)推到面板
        # 最右端、与「校验」标签严重分离。改为拉伸列 11（校验下拉与打开按钮之后），
        # 校验标签与校验下拉立即紧邻，下拉框靠左贴近「校验」。
        grid_serial.setColumnStretch(11, 1)
        vbox.addWidget(self.grp_serial)

        # 网口参数（所有设置控件 1 行，新增「本地 IP」用于 TCP 服务器监听绑定）
        self.grp_net = QGroupBox()
        grid_net = QGridLayout(self.grp_net)
        self.lb_net_proto = QLabel()
        grid_net.addWidget(self.lb_net_proto, 0, 0)
        self.cb_net_proto = QComboBox()
        self.cb_net_proto.addItem(tr("net.tcp_client"), "tcp_client")
        self.cb_net_proto.addItem(tr("net.tcp_server"), "tcp_server")
        self.cb_net_proto.addItem(tr("net.udp"), "udp")
        self.cb_net_proto.currentIndexChanged.connect(self._on_net_proto_changed)
        grid_net.addWidget(self.cb_net_proto, 0, 1)
        self.lb_net_host = QLabel()
        grid_net.addWidget(self.lb_net_host, 0, 2)
        self.ed_net_host = QLineEdit("127.0.0.1")
        grid_net.addWidget(self.ed_net_host, 0, 3)
        self.lb_net_port = QLabel()
        grid_net.addWidget(self.lb_net_port, 0, 4)
        self.sp_net_port = QSpinBox()
        self.sp_net_port.setRange(1, 65535)
        self.sp_net_port.setValue(23)
        grid_net.addWidget(self.sp_net_port, 0, 5)
        self.lb_net_localip = QLabel()
        grid_net.addWidget(self.lb_net_localip, 0, 6)
        self.ed_net_localip = QLineEdit("0.0.0.0")
        grid_net.addWidget(self.ed_net_localip, 0, 7)
        self.lb_net_local = QLabel()
        grid_net.addWidget(self.lb_net_local, 0, 8)
        self.sp_net_local = QSpinBox()
        self.sp_net_local.setRange(1, 65535)
        self.sp_net_local.setValue(23)
        grid_net.addWidget(self.sp_net_local, 0, 9)
        # 网口连接/断开控件放到网口设置控件的最后面
        self.btn_open_net = QPushButton()
        self.btn_open_net.clicked.connect(self._toggle_open)
        self.lb_open_state_net = QLabel()
        grid_net.addWidget(self.btn_open_net, 0, 10)
        grid_net.addWidget(self.lb_open_state_net, 0, 11)
        grid_net.setColumnStretch(12, 1)
        vbox.addWidget(self.grp_net)
        self.grp_net.hide()
        self._on_net_proto_changed(0)


        # 收发合一终端面板
        self.grp_term = QGroupBox()
        term_layout = QVBoxLayout(self.grp_term)

        rx_options_bar = QHBoxLayout()
        self.chk_hex_rx = QCheckBox()
        self.chk_hex_rx.toggled.connect(self._on_display_mode_changed)
        rx_options_bar.addWidget(self.chk_hex_rx)
        # SOP-06：Hex 列数（8/16/24/32），默认 16
        self.cb_hex_cols = QComboBox()
        self.cb_hex_cols.addItems(["8", "16", "24", "32"])
        self.cb_hex_cols.setCurrentText("16")
        self.cb_hex_cols.currentTextChanged.connect(self._on_hex_cols_changed)
        rx_options_bar.addWidget(self.cb_hex_cols)
        self.chk_ts = QCheckBox()
        self.chk_ts.toggled.connect(self._on_display_mode_changed)
        rx_options_bar.addWidget(self.chk_ts)
        # SOP-04：时间戳格式（秒 / 毫秒），默认毫秒
        self.cb_ts_fmt = QComboBox()
        self.cb_ts_fmt.addItem(tr("terminal.ts_fmt_s"), "s")
        self.cb_ts_fmt.addItem(tr("terminal.ts_fmt_ms"), "ms")
        self.cb_ts_fmt.setCurrentIndex(0)  # SOP V3.0：默认秒级
        self.cb_ts_fmt.currentIndexChanged.connect(self._on_ts_fmt_changed)
        rx_options_bar.addWidget(self.cb_ts_fmt)
        self.chk_lineno = QCheckBox()
        self.chk_lineno.toggled.connect(self._on_display_mode_changed)
        rx_options_bar.addWidget(self.chk_lineno)
        self.chk_autoscroll = QCheckBox()
        self.chk_autoscroll.setChecked(True)
        rx_options_bar.addWidget(self.chk_autoscroll)
        self.chk_pause_rx = QCheckBox()
        self.chk_pause_rx.toggled.connect(self._on_pause_rx)
        rx_options_bar.addWidget(self.chk_pause_rx)
        self.chk_wrap = QCheckBox()
        self.chk_wrap.setChecked(True)
        self.chk_wrap.toggled.connect(self._on_wrap)
        rx_options_bar.addWidget(self.chk_wrap)
        # 回车行尾下拉（回车/即时输入发送时附加 \n / \r / \r\n / 无）
        self.lb_enter_nl = QLabel()
        rx_options_bar.addWidget(self.lb_enter_nl)
        self.cb_enter_nl = QComboBox()
        for _code, _key in _NEWLINE_OPTIONS:
            self.cb_enter_nl.addItem(_combo_text(_code, _key), _code)
        self.cb_enter_nl.currentIndexChanged.connect(self._on_enter_nl_changed)
        rx_options_bar.addWidget(self.cb_enter_nl)
        # 本地回显移至接收缓存行数左侧；串口/网口共用（同一终端回显逻辑）
        self.chk_echo = QCheckBox()
        self.chk_echo.setChecked(False)  # SOP V3.0：默认 Remote Mode（不本地回显）
        self.chk_echo.toggled.connect(lambda _: self._sync_instant_terminal_config())
        rx_options_bar.addWidget(self.chk_echo)
        self.lb_rx_cap = QLabel()
        rx_options_bar.addWidget(self.lb_rx_cap)
        self.cb_rx_cap = QComboBox()
        # CACHE-01 修复：接收缓存支持行数和容量两种模式，全局上限 10GB
        self.cb_rx_cap.addItems([
            "1000 行", "5000 行", "10000 行", "50000 行", "100000 行",
            "1 MB", "10 MB", "100 MB", "1 GB", "5 GB", "10 GB"
        ])
        self.cb_rx_cap.setCurrentText("10000 行")
        self.cb_rx_cap.currentTextChanged.connect(self._on_rx_cap_changed)
        rx_options_bar.addWidget(self.cb_rx_cap)
        self.btn_clear_rx = QPushButton()
        self.btn_clear_rx.clicked.connect(self._clear_rx)
        rx_options_bar.addWidget(self.btn_clear_rx)
        self.btn_save_rx = QPushButton()
        self.btn_save_rx.clicked.connect(self._save_rx)
        rx_options_bar.addWidget(self.btn_save_rx)
        self.lb_rx_count = QLabel("0")
        rx_options_bar.addWidget(self.lb_rx_count)
        self.btn_clear_count = QPushButton()
        self.btn_clear_count.clicked.connect(self._clear_counts)
        rx_options_bar.addWidget(self.btn_clear_count)
        rx_options_bar.addStretch(1)
        term_layout.addLayout(rx_options_bar)

        # 终端日志（接收 + 即时输入本地回显共用）
        self.rx_edit = InstantTerminal()
        self.rx_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.rx_edit.customContextMenuRequested.connect(self._on_term_context_menu)
        self.rx_edit.bytesOut.connect(self._on_instant_bytes)
        # 自动换行控件初始化后立即与复选框状态同步（软换行 WidgetWidth / NoWrap）
        self._on_wrap(self.chk_wrap.isChecked())
        # CACHE-01 修复：初始化时按下拉框当前值设置缓存（行数或 MB）
        self._on_rx_cap_changed(self.cb_rx_cap.currentText())
        # 接收区与发送面板之间加可拖拽分隔条（QSplitter）：拖拽分隔条即可调整接收区高度，
        # 接收区减多少→发送面板增多少（等量联动）；发送面板锚定底部、顶边随分隔条移动。
        self.rx_splitter = QSplitter(Qt.Orientation.Vertical)
        self.rx_splitter.setChildrenCollapsible(False)
        self.rx_splitter.setHandleWidth(6)
        self.rx_splitter.addWidget(self.rx_edit)
        # 发送面板：选项条(固定) + 输入行(伸缩吸收) + 快捷栏(固定)，
        # 无多余空白，发送面板高度变化全部由输入行吸收。
        self._rx_bottom = QWidget()
        self._rx_bottom_layout = QVBoxLayout(self._rx_bottom)
        self._rx_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self._rx_bottom_layout.setSpacing(2)
        self.rx_splitter.addWidget(self._rx_bottom)
        term_layout.addWidget(self.rx_splitter, 1)

        # 发送选项条（截图区域2：高度固定不变，不随发送面板伸缩）
        self._bar2_widget = QWidget()
        tx_options_bar = QHBoxLayout(self._bar2_widget)
        tx_options_bar.setContentsMargins(0, 0, 0, 0)
        self.chk_hex_tx = QCheckBox()
        self.chk_hex_tx.toggled.connect(self._on_hex_tx_toggled)
        tx_options_bar.addWidget(self.chk_hex_tx)
        self.chk_esc = QCheckBox()
        tx_options_bar.addWidget(self.chk_esc)
        self.lb_newline = QLabel()
        tx_options_bar.addWidget(self.lb_newline)
        self.cb_newline = QComboBox()
        self.cb_newline.currentIndexChanged.connect(
            lambda _: self._sync_newline_both())
        tx_options_bar.addWidget(self.cb_newline)
        self.lb_checksum = QLabel()
        tx_options_bar.addWidget(self.lb_checksum)
        self.cb_checksum = QComboBox()
        # 校验下拉选项左移贴近下拉框（宽度随内容自适应）
        self.cb_checksum.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        tx_options_bar.addWidget(self.cb_checksum)
        self.chk_periodic = QCheckBox()
        self.chk_periodic.toggled.connect(self._on_periodic)
        tx_options_bar.addWidget(self.chk_periodic)
        self.sp_period = PlusMinusBox(1.0, 60000.0, 1000.0, decimals=0,
                                      step=100.0, suffix=" ms")
        self.sp_period.valueChanged.connect(self._on_period_changed)
        tx_options_bar.addWidget(self.sp_period)
        # 发送按钮与发送文件按钮相邻（发送在左），发送区（底部输入行）因此扩到最宽
        self.btn_send = QPushButton()
        self.btn_send.clicked.connect(self._on_send_line_clicked)
        tx_options_bar.addWidget(self.btn_send)
        self.btn_send_file = QPushButton()
        self.btn_send_file.clicked.connect(self._send_file)
        tx_options_bar.addWidget(self.btn_send_file)
        self.lb_tx_count = QLabel("0")
        tx_options_bar.addWidget(self.lb_tx_count)
        tx_options_bar.addStretch(1)
        # 状态提示（发送结果/串口未打开等）位于发送选项条最右侧，高亮显示
        self.lb_send_note = QLabel("")
        self.lb_send_note.setStyleSheet("color: #ffcc00; font-weight: bold;")
        tx_options_bar.addWidget(self.lb_send_note)
        # 选项条高度硬性锁定为其内容高度（sizeHint）：任何情况下都不随发送面板伸缩，
        # 发送面板高度变化全部由下方输入行+快捷发送栏吸收。
        self._bar2_widget.setFixedHeight(self._bar2_widget.sizeHint().height())
        self._rx_bottom_layout.addWidget(self._bar2_widget)

        # 底部输入行（cmd 风格），占满整行宽度
        input_line_bar = QHBoxLayout()
        self.input_line = SendEdit()
        self.input_line.submitted.connect(self._send_line)
        input_line_bar.addWidget(self.input_line, 1)
        # stretch=1：输入行吸收发送面板全部高度变化（无空白）；
        # 选项条、快捷栏均为固定高度，不参与伸缩。
        self._rx_bottom_layout.addLayout(input_line_bar, 1)
        # 初始高度比例：接收区大、发送面板约 210px（选项条31+输入行~130+快捷栏46）
        self.rx_splitter.setSizes([700, 210])
        self.rx_splitter.setStretchFactor(0, 1)
        self.rx_splitter.setStretchFactor(1, 0)

        vbox.addWidget(self.grp_term, 3)

        # 快捷发送栏（固定高度，位于输入行下方；发送面板伸缩时输入行吸收高度差）
        self.quick_bar = QuickSendBar()
        self.quick_bar.send.connect(self._send_item)
        self._rx_bottom_layout.addWidget(self.quick_bar)

        self._send_timer = QTimer(self)
        self._send_timer.timeout.connect(self._send)
        self._file_send_timer = QTimer(self)
        self._file_send_timer.setInterval(5)
        self._file_send_timer.timeout.connect(self._file_send_step)
        # 通讯终端页所有控件悬停 3 秒显示详细说明（唯一提示体系，含选中/不选中状态感知）
        self._install_terminal_helps()
        return tab

    # ------------------------------------------------------------------ hover 说明
    def _install_terminal_helps(self):
        """为通讯终端页全部控件安装「悬停 3 秒详细说明 + 最终视觉效果」。
        带选中/不选中状态的控件（复选框）按当前状态动态生成说明。"""

        def hl(color):
            return f"<span style='color:{color};'><b>"

        # ---- 串口配置区
        install_hover_help(self.cb_port,
            lambda: f"<b>串口端口</b><br>选择要连接的下位机串口设备（COM 口）。"
                    f"<br>点击右侧「刷新」可重新扫描系统串口。<br>{hl('#e09600')}效果："
                    f"</b></span>选择后点「打开串口」即开始与设备通信。")
        install_hover_help(self.btn_refresh,
            lambda: "<b>刷新端口</b><br>重新扫描系统所有串口设备，检测新插入的 "
                    "USB 转串口。<br><span style='color:#e09600;'><b>效果：</b></span>"
                    "下拉列表立即更新为最新串口列表。")
        install_hover_help(self.cb_baud,
            lambda: "<b>波特率</b><br>串口通信速率（bit/s），必须与下位机一致。"
                    "<br>常见：9600 / 115200 / 460800 / 921600。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>与设备不一致时"
                    "会出现乱码或完全无响应。")
        install_hover_help(self.cb_data,
            lambda: "<b>数据位</b><br>每帧数据位数，常用 8。<br>"
                    "必须与下位机串口配置一致，否则解析错位。")
        install_hover_help(self.cb_stop,
            lambda: "<b>停止位</b><br>每帧停止位数，常用 1。<br>必须与下位机一致。")
        install_hover_help(self.cb_parity,
            lambda: "<b>校验位</b><br>无 / 奇 / 偶 / 标志 / 空格校验，须与下位机一致。"
                    "<br>多数嵌入式设备为「无」。")
        install_hover_help(self.cb_flow,
            lambda: "<b>流控</b><br>无 / 硬件(RTS/CTS) / 软件(XON/XOFF) 流控。<br>"
                    "大多数场景选「无」。")
        install_hover_help(self.cb_enc,
            lambda: "<b>字符编码</b><br>接收与发送文本的编码。<br>设备输出中文时选 "
                    "GBK，默认 UTF-8。<br><span style='color:#e09600;'><b>效果："
                    "</b></span>编码不对时中文显示为乱码。")
        # 串口/网口各自的打开按钮分别安装悬停说明
        install_hover_help(self.btn_open_serial,
            lambda: "<b>打开 / 关闭串口</b><br>未打开：点击打开串口并开始收发（按钮变为"
                    "「关闭串口」）。<br>已打开：点击关闭串口（按钮变回「打开串口」）。"
                    "<br><span style='color:#e09600;'><b>提示：</b></span>串口与网口互斥，"
                    "同一时刻只能打开一种。")
        install_hover_help(self.btn_open_net,
            lambda: "<b>连接 / 断开网口</b><br>未连接：点击建立网口连接（TCP 客户端 / "
                    "TCP 服务器监听 / UDP 绑定），按钮变为「断开」。<br>已连接：点击断开网口连接。"
                    "<br><span style='color:#e09600;'><b>提示：</b></span>串口与网口互斥，"
                    "同一时刻只能打开一种。")
        install_hover_help(self.chk_dtr,
            state_text(lambda: self.chk_dtr.isChecked(),
                "<b>DTR：已勾选</b><br>DTR（数据终端就绪）信号线拉高。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>可唤醒部分设备、"
                "触发某些设备的复位/就绪逻辑。",
                "<b>DTR：未勾选</b><br>DTR 信号线为低电平。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>大多数下位机"
                "不依赖 DTR，保持默认即可。"))

        # ---- 原「通讯方式」控件已移除，改由菜单「设置 -> 通讯接口」选择

        # ---- 网口配置区
        install_hover_help(self.cb_net_proto,
            state_text(lambda: self.cb_net_proto.currentData() == "tcp_client",
                "<b>网口协议：TCP 客户端</b><br>主动连接远程 TCP 服务器（IP + 远程端口）。"
                "<br><span style='color:#e09600;'><b>效果：</b></span>输入远程 IP 与端口，"
                "点「连接」即建立 TCP 连接并开始收发。",
                "<b>网口协议：TCP 服务器 / UDP</b><br>TCP 服务器：本地监听端口，等待设备"
                "主动连入。<br>UDP：本地端口绑定接收，远程 IP/端口为发送目标。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>相关参数自动切换显示。"))
        install_hover_help(self.ed_net_host,
            lambda: "<b>远程 IP</b><br>目标设备的 IP 地址。<br>"
                    "TCP 客户端：要连接的服务器 IP。<br>"
                    "UDP：数据发送的目标 IP。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>"
                    "填写正确后点「连接」即可通信。")
        install_hover_help(self.sp_net_port,
            lambda: "<b>远程端口</b><br>目标设备的端口号（1–65535）。<br>"
                    "TCP 客户端：服务器监听端口。<br>UDP：发送目标端口。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>"
                    "与设备端口一致才能通信。")
        install_hover_help(self.ed_net_localip,
            lambda: "<b>本地 IP</b><br>本机监听/绑定网卡地址。<br>"
                    "TCP 服务器：在此 IP 上监听，等待设备连入。<br>"
                    "UDP：在此 IP 上绑定接收。<br>"
                    "默认 <code>0.0.0.0</code> 表示监听本机全部网卡。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>"
                    "填入指定网卡 IP 可只监听该网卡，隔离网络。")
        install_hover_help(self.sp_net_local,
            lambda: "<b>本地端口</b><br>本机监听/绑定端口（1–65535）。<br>"
                    "TCP 服务器：监听端口，等待设备连入。<br>UDP：绑定端口，接收数据。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>"
                    "设备向该端口发数据即可收到。")
        install_hover_help(self.chk_rts,
            state_text(lambda: self.chk_rts.isChecked(),
                "<b>RTS：已勾选</b><br>RTS（请求发送）信号线拉高。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>用于硬件流控"
                "或唤醒部分设备。",
                "<b>RTS：未勾选</b><br>RTS 信号线为低电平。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>多数场景关闭流控"
                "时保持默认即可。"))
        install_hover_help(self.chk_echo,
            state_text(lambda: self.chk_echo.isChecked(),
                "<b>本地回显：已开启（串口/网口共用）</b><br>按键始终发送 + 本地金色渲染，"
                "设备回传字符与本地输入顺序配对消费（不重复显示）——编辑体验与系统文本编辑器一致。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>用于不回显设备时看清输入；"
                "设备也回显时同样单次（确认字符被消费）。",
                "<b>本地回显：关闭（推荐，串口/网口共用）</b><br>按键始终发送、不本地渲染，"
                "屏幕仅显示设备回传内容。<br><span style='color:#e09600;'><b>效果：</b></span>"
                "用于带回显设备（如 RT-Thread/msh、Linux shell）时输入紧跟设备提示符，绝无双重。"))
        # ---- 接收显示条
        install_hover_help(self.chk_hex_rx,
            state_text(lambda: self.chk_hex_rx.isChecked(),
                "<b>HEX 显示：已勾选</b><br>接收数据以十六进制显示"
                "（每字节两个 hex 字符 + 空格）。<br>适合查看二进制原始字节、"
                "帧头帧尾。<br><span style='color:#e09600;'><b>效果：</b></span>"
                "接收区显示如 01 02 A5 FF。",
                "<b>HEX 显示：未勾选（默认）</b><br>接收数据按文本显示。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>设备输出 "
                "ASCII/中文时直观可读。"))
        install_hover_help(self.cb_hex_cols,
            lambda: "<b>HEX 列数</b><br>HEX 显示时每行显示的字节数（8/16/24/32）。"
                    "<br>默认 16。<br><span style='color:#e09600;'><b>效果："
                    "</b></span>每满 N 字节自动换新行。")
        install_hover_help(self.chk_ts,
            state_text(lambda: self.chk_ts.isChecked(),
                "<b>时间戳：已勾选</b><br>每行行首显示接收时间戳 [HH:mm:ss]"
                "（或毫秒）。<br>便于观察数据到达时刻与间隔。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>行首出现灰色时间戳。",
                "<b>时间戳：未勾选（默认）</b><br>不显示时间戳。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>接收区更简洁。" ))
        install_hover_help(self.cb_ts_fmt,
            lambda: "<b>时间戳格式</b><br>秒 [HH:mm:ss] 或 毫秒 [HH:mm:ss.zzz]。<br>"
                    "默认秒级（与 WindTerm 一致），毫秒用于高精度分析。")
        install_hover_help(self.chk_lineno,
            state_text(lambda: self.chk_lineno.isChecked(),
                "<b>行号：已勾选</b><br>每行行首显示递增行号（灰色列）。<br>"
                "输入行在完成（回车/设备换行）后才显示行号，行号严格递增无跳号。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>如 「 1  msh "
                "&gt;help」。",
                "<b>行号：未勾选（默认）</b><br>不显示行号。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>接收区无行号列。"))
        install_hover_help(self.chk_autoscroll,
            state_text(lambda: self.chk_autoscroll.isChecked(),
                "<b>自动滚动：已勾选（默认）</b><br>新数据到达自动滚动到底部，"
                "始终看到最新数据。<br><span style='color:#e09600;'><b>效果："
                "</b></span>接收时视图跟随滚动。",
                "<b>自动滚动：未勾选</b><br>不自动滚动，可停留在任意位置查看历史。"
                "<br><span style='color:#e09600;'><b>效果：</b></span>接收时视图"
                "保持不动，上翻查看历史更稳。"))
        install_hover_help(self.chk_pause_rx,
            state_text(lambda: self.chk_pause_rx.isChecked(),
                "<b>暂停显示：已勾选</b><br>暂停显示，接收数据继续接收并缓存，"
                "恢复后按序回放。<br>适合高波特率下停下来细看时使用。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>接收区静止，"
                "恢复后补显示暂停期间的数据。",
                "<b>暂停显示：未勾选（默认）</b><br>接收数据实时显示。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>数据实时刷新。" ))
        install_hover_help(self.chk_wrap,
            state_text(lambda: self.chk_wrap.isChecked(),
                "<b>自动换行：已勾选（默认）</b><br>超长行在控件宽度处自动"
                "<b>软换行</b>折行显示完整。<br><b>注意：</b>软换行只是显示效果，"
                "<b>不改变数据内容、不计入行号</b>；只有换行符（\\n / \\r\\n）"
                "才产生真实换行。<br><span style='color:#e09600;'><b>效果："
                "</b></span>设备输出长数组/长数据时完整可见。",
                "<b>自动换行：未勾选</b><br>关闭自动换行，超长行<b>横向滚动</b>"
                "查看。<br>适合对齐查看固定宽度文本。<br><span style='color:#e09600;'>"
                "<b>效果：</b></span>长行不折行、横向滚动条出现。"))
        install_hover_help(self.cb_rx_cap,
            lambda: "<b>接收缓存上限</b><br>接收区最大缓存（行数或容量），超过后"
                    "自动丢弃最旧行（FIFO）。<br>越大占用内存越多，一般 10000 行"
                    "足够。<br><span style='color:#e09600;'><b>效果：</b></span>"
                    "超出上限时最旧内容被滚动丢弃。")
        install_hover_help(self.btn_clear_rx,
            lambda: "<b>清空接收</b><br>清空接收区全部内容。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>行号从 1 "
                    "重新开始。")
        install_hover_help(self.btn_save_rx,
            lambda: "<b>保存接收</b><br>把接收区当前全部内容保存为文本文件。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>弹出保存"
                    "对话框，可选择路径。")
        install_hover_help(self.btn_clear_count,
            lambda: "<b>清零计数</b><br>把接收字节计数和发送字节计数清零。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>计数显示"
                    "归零后重新累计。")

        # ---- 发送选项条
        install_hover_help(self.chk_hex_tx,
            state_text(lambda: self.chk_hex_tx.isChecked(),
                "<b>HEX 发送：已勾选</b><br>发送内容按十六进制解析（空格分隔），"
                "如「AA 01 02」发送字节 AA 01 02。<br>非法 hex 会提示错误。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>逐字节发送。",
                "<b>HEX 发送：未勾选（默认）</b><br>发送内容按文本发送。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>按当前编码发送"
                "文本字符。"))
        install_hover_help(self.chk_esc,
            state_text(lambda: self.chk_esc.isChecked(),
                "<b>转义处理：已勾选</b><br>发送时解析转义序列，如 \\r \\n \\t "
                "\\\\ 等。<br><span style='color:#e09600;'><b>效果：</b></span>"
                "文本中的 \\r\\n 会发送为回车换行字节。",
                "<b>转义处理：未勾选（默认）</b><br>不解析转义，原样发送。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>反斜杠按普通"
                "字符发送。"))
        install_hover_help(self.cb_enter_nl,
            lambda: "<b>回车行尾</b><br>按<code>回车键</code>（即时输入）发送时附加的"
                    "行尾字节，下拉选择：<b>\\r\\n / \\n / \\r / 无</b>。<br>"
                    "与底部「行尾」下拉联动，任一处修改两处同步。<br>"
                    "常用：RT-Thread/msh、Linux shell 用 <b>\\r\\n</b>；"
                    "部分设备只认 <b>\\n</b> 或 <b>\\r</b>；"
                    "无 = 回车只发已输入的字符不加行尾。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>按回车后，"
                    "设备收到命令 + 所选行尾字节，终端换行。")
        install_hover_help(self.cb_newline,
            lambda: "<b>行尾</b><br>回车/发送时附加的行尾字节：\\r\\n / \\r / \\n "
                    "/ 无。<br>需与下位机命令解析要求一致。<br>"
                    "<b>默认</b>：首次运行自动按<b>系统默认回车</b>"
                    "（Windows = \\r\\n，Linux/macOS = \\n）；手动选择后以你的选择为准。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>发送内容后"
                    "自动追加所选行尾。")
        install_hover_help(self.cb_checksum,
            lambda: "<b>校验</b><br>发送时自动附加校验字节（无/和校验/CRC 等）。<br>"
                    "需与下位机校验协议一致。<br><span style='color:#e09600;'>"
                    "<b>效果：</b></span>发送时在数据末尾追加校验字节。")
        install_hover_help(self.chk_periodic,
            state_text(lambda: self.chk_periodic.isChecked(),
                "<b>周期发送：已勾选</b><br>按右侧周期（毫秒）自动重复发送发送框"
                "内容。<br>适合持续查询设备状态。<br><span style='color:#e09600;'>"
                "<b>效果：</b></span>按设定周期持续自动发送。",
                "<b>周期发送：未勾选（默认）</b><br>手动点击发送或回车发送。<br>"
                "<span style='color:#e09600;'><b>效果：</b></span>仅手动触发发送。" ))
        install_hover_help(self.sp_period,
            lambda: "<b>发送周期</b><br>周期发送的时间间隔（毫秒）。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>勾选周期发送"
                    "后按此间隔重复发送。")
        install_hover_help(self.btn_send,
            lambda: "<b>发送</b><br>立即发送发送框中的内容（按当前 HEX/转义/行尾/"
                    "校验设置）。<br><span style='color:#e09600;'><b>效果："
                    "</b></span>数据发往串口，发送计数 +1。")
        install_hover_help(self.btn_send_file,
            lambda: "<b>发送文件</b><br>选择文件，把文件内容（文本或二进制）发送到"
                    "串口。<br>用于固件/脚本下发。<br><span style='color:#e09600;'>"
                    "<b>效果：</b></span>按所选文件内容发送。")
        install_hover_help(self.lb_rx_count,
            lambda: "<b>接收计数</b><br>累计接收字节数。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>实时更新，"
                    "可用「清零计数」归零。")
        install_hover_help(self.lb_tx_count,
            lambda: "<b>发送计数</b><br>累计发送字节数。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>实时更新，"
                    "可用「清零计数」归零。")

        # ---- 底部输入行
        install_hover_help(self.input_line,
            lambda: "<b>底部输入行</b><br>输入命令后回车即发送（终端风格）。<br>"
                    "↑/↓ 回溯发送历史，Esc 清空当前行。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>内容立即发往"
                    "串口，设备回显显示在接收区。")
        install_hover_help(self.quick_bar,
            lambda: "<b>快捷发送栏</b><br>预置常用命令，单击即发送。<br>"
                    "右键可增删改移，每项可独立配置 HEX 与行尾，退出自动保存。<br>"
                    "<span style='color:#e09600;'><b>效果：</b></span>一键发送"
                    "常用指令，提升调试效率。")

    def _build_wave_tab(self):
        tab = QWidget()
        vbox = QVBoxLayout(tab)
        row_layout = QHBoxLayout()
        self.lb_fmt_label = QLabel()
        row_layout.addWidget(self.lb_fmt_label)
        self.fmt_edit = QLineEdit(DEMO_FORMAT)
        row_layout.addWidget(self.fmt_edit, 1)
        self.btn_apply_fmt = QPushButton()
        self.btn_apply_fmt.clicked.connect(self._apply_format)
        row_layout.addWidget(self.btn_apply_fmt)
        self.lb_fmt_info = QLabel()
        row_layout.addWidget(self.lb_fmt_info)
        vbox.addLayout(row_layout)
        self.waveform = WaveformPanel(dh=self.dh)
        self.waveform.cleared.connect(self._on_waveform_cleared)
        # BUG-I 修复：通道启停变化 → 同步 FFT 通道下拉并刷新分布图
        self.waveform.channels_changed.connect(self._on_channels_changed)
        vbox.addWidget(self.waveform, 1)
        return tab

    def _build_fft_tab(self):
        self.fft_panel = FftSpectrumPanel(self.dh)
        return self.fft_panel

    def _build_dist_tab(self):
        self.dist_panel = DistPanel(self.dh)
        return self.dist_panel

    # ---------------------------------------------------------------- 串口
    def _refresh_ports(self):
        prev = self.cb_port.currentData()
        self.cb_port.blockSignals(True)
        self.cb_port.clear()
        ports = list_serial_ports()
        for dev, desc, _hw in ports:
            self.cb_port.addItem(f"{dev}  ({desc})" if desc else dev, dev)
        self.cb_port.addItem(tr("serial.virtual"), "__VIRTUAL__")
        # 语言切换/刷新动作不应改变用户已选端口（reset currentData）
        idx = self.cb_port.findData(prev)
        if idx >= 0:
            self.cb_port.setCurrentIndex(idx)
        self.cb_port.blockSignals(False)

    def _on_proto_changed(self, idx):
        """通讯方式切换（串口/网口互斥）：先关闭当前数据源，再切换参数区。"""
        if self.opened:
            self._close_source()
        is_net = self._net_mode()
        self.grp_net.setVisible(is_net)
        self.grp_serial.setVisible(not is_net)
        if is_net:
            self._open_btn().setText(tr("net.open"))
            self._open_state_lb().setText(tr("net.state_closed"))
        else:
            self._open_btn().setText(tr("serial.open"))
            self._open_state_lb().setText(tr("serial.state_closed"))
        self._sync_comm_menu_actions()

    def _on_net_proto_changed(self, idx):
        """网口协议联动：TCP Client 需远程 IP/端口；TCP Server/UDP 需本地端口；
        UDP 两者都要（本地收 + 远程发）。"""
        proto = self.cb_net_proto.currentData() or "tcp_client"
        # TCP 客户端：远程 IP + 远程端口；TCP 服务器：本地 IP + 本地端口；
        # UDP：远程 IP/端口（发送目标）+ 本地 IP/端口（绑定接收）都要。
        need_remote = proto in ("tcp_client", "udp")
        need_local = proto in ("tcp_server", "udp")
        for widget, on in ((self.lb_net_host, need_remote), (self.ed_net_host, need_remote),
                      (self.lb_net_port, need_remote), (self.sp_net_port, need_remote),
                      (self.lb_net_localip, need_local), (self.ed_net_localip, need_local),
                      (self.lb_net_local, need_local), (self.sp_net_local, need_local)):
            widget.setEnabled(on)
            widget.setVisible(on)

    def _open_net(self):
        """打开网口数据源（TCP Client / TCP Server / UDP）。
        串口/网口互斥：调用前已由 _open_source 确保另一种已关闭。"""
        proto = self.cb_net_proto.currentData() or "tcp_client"
        host = (self.ed_net_host.text() or "").strip() or "127.0.0.1"
        port = self.sp_net_port.value()
        local_ip = (self.ed_net_localip.text() or "").strip() or "0.0.0.0"
        local = self.sp_net_local.value()
        self.waveform.clear()
        self.source = NetSource(proto=proto, host=host, port=port,
                                local_ip=local_ip, local_port=local)
        # 网口无波特率：沿用当前波特率下拉作为帧时间基准（与串口同一存储框架）
        try:
            time_per_baud = int(self.cb_baud.currentText() or 115200)
        except (TypeError, ValueError):
            time_per_baud = 115200
        self._t_per_byte = 10 / time_per_baud
        self._t_baud = time_per_baud
        self._session_bytes = 0
        self._tim_buf.clear()
        self._decimals = self._new_decoder()
        # 锁定通讯相关控件（网口参数 + 通讯方式；串口参数区已隐藏）
        for widget in (self.cb_proto, self.cb_net_proto, self.ed_net_host,
                  self.sp_net_port, self.ed_net_localip, self.sp_net_local):
            widget.setEnabled(False)
        self._activate_source()
        self._open_btn().setText(tr("net.close"))
        self._open_state_lb().setText(tr("net.state_open"))
        self.lb_send_note.setText("")
        if self.chk_periodic.isChecked():
            self._send_timer.start(self._period_ms())

    def _close_net(self):
        self._send_timer.stop()
        self.opened = False
        self._finish_file_send(completed=None)
        if self.source is not None:
            for sig, slot in ((self.source.data, self._on_data),
                              (self.source.error, self._on_source_error),
                              (self.source.finished, self._on_source_finished)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self.source.stop()
            if not self.source.wait(5000):
                self.source.terminate()
                self.source.wait()
            self.source = None
        # 冲刷增量解码器末尾不完整多字节字符（SOP-08：与串口关闭共用实现）
        self._flush_decoder_tail()
        for widget in (self.cb_proto, self.cb_net_proto, self.ed_net_host,
                  self.sp_net_port, self.ed_net_localip, self.sp_net_local):
            widget.setEnabled(True)
        self._on_net_proto_changed(self.cb_net_proto.currentIndex())
        self._open_btn().setText(tr("net.open"))
        self._open_state_lb().setText(tr("net.state_closed"))
        self.lb_send_note.setText("")

    def _net_mode(self) -> bool:
        """当前通讯方式是否为网口（串口/网口互斥）。"""
        return bool(getattr(self, "cb_proto", None) and self.cb_proto.currentData() == "net")

    def _set_comm_mode(self, is_net):
        """菜单「设置 -> 通讯接口」切换串口/网口（替代原通讯方式控件）。
        先关闭当前数据源，再切换参数区；cb_proto 作为内部模式状态保留但不显示。"""
        idx = 1 if is_net else 0
        if not hasattr(self, "cb_proto"):
            return
        if self.cb_proto.currentIndex() != idx:
            self.cb_proto.blockSignals(True)
            self.cb_proto.setCurrentIndex(idx)
            self.cb_proto.blockSignals(False)
            self._on_proto_changed(idx)
        self._sync_comm_menu_actions()

    def _sync_comm_menu_actions(self):
        """同步菜单勾选状态到当前通讯方式（串口/网口互斥）。"""
        if hasattr(self, "act_comm_serial"):
            self.act_comm_serial.setChecked(not self._net_mode())
            self.act_comm_net.setChecked(self._net_mode())

    def _open_btn(self):
        """当前通讯方式对应的打开/关闭按钮（串口面板或网口面板）。"""
        return self.btn_open_net if self._net_mode() else self.btn_open_serial

    def _open_state_lb(self):
        """当前通讯方式对应的打开状态标签。"""
        return self.lb_open_state_net if self._net_mode() else self.lb_open_state_serial

    def _toggle_open(self):
        if self.opened:
            self._close_source()
        else:
            self._open_source()

    def _open_source(self):
        """按当前通讯方式打开数据源；打开一种前先互斥关闭另一种。"""
        if self._net_mode():
            if self.opened:               # 已是网口开着 → 关闭重开
                self._close_source()
            self._open_net()
        else:
            if self.opened:               # 已是串口开着 → 关闭重开
                self._close_source()
            self._open_serial()

    def _close_source(self):
        if self._net_mode():
            self._close_net()
        else:
            self._close_serial()

    def _current_baud(self) -> int:
        """串口页当前「真实波特率」：已打开取锁定会话值（虚拟源固定 115200），未打开取下拉框当前选择。"""
        if self.opened:
            return int(getattr(self, "_t_baud", 115200))
        try:
            return int(self.cb_baud.currentText() or 0)
        except (TypeError, ValueError):
            return 0

    def _activate_source(self):
        """激活数据源：连接数据/错误/完成信号并启动线程（串口与网口共用）。"""
        self.source.data.connect(self._on_data)
        self.source.error.connect(self._on_source_error)
        self.source.finished.connect(self._on_source_finished)
        self.source.start()
        self.opened = True

    def _open_serial(self):
        port = self.cb_port.currentData() or ""
        if port != "__VIRTUAL__" and not port:
            QMessageBox.warning(self, "OtherScope", tr("serial.warn_no_port"))
            return
        # 新会话复位
        self.waveform.clear()

        if port == "__VIRTUAL__":
            self.source = VirtualSource(rate=400.0, baud=115200, bits_per_byte=10)
            time_per_baud = 115200
            time_per_bit = 10
        else:
            data_bits = int(self.cb_data.currentText())
            parity_code = self.cb_parity.currentData() or "N"
            stop_text = self.cb_stop.currentText()
            stop_bits = STOP_BITS.get(stop_text, 1.0)
            parity_bits = 0 if parity_code == "N" else 1
            time_per_baud = int(self.cb_baud.currentText())
            time_per_bit = 1 + data_bits + parity_bits + stop_bits
            self.source = SerialSource(
                port=port,
                baudrate=time_per_baud,
                bytesize=data_bits,
                parity=parity_code,
                stopbits=stop_bits,
                flow=self.cb_flow.currentData() or "none",
                dtr=self.chk_dtr.isChecked(),
                rts=self.chk_rts.isChecked(),
            )
        # 精确时序：每字节耗时 = 每字节比特数 / 波特率
        self._t_per_byte = time_per_bit / time_per_baud
        self._t_baud = time_per_baud
        self._session_bytes = 0
        self._tim_buf.clear()

        self._decimals = self._new_decoder()
        for widget in (self.cb_port, self.cb_baud, self.cb_data, self.cb_stop,
                  self.cb_parity, self.cb_flow, self.cb_enc,
                  self.chk_dtr, self.chk_rts, self.btn_refresh, self.cb_proto):
            widget.setEnabled(False)
        self._activate_source()
        self._open_btn().setText(tr("serial.close"))
        self._open_state_lb().setText(tr("serial.state_open"))
        self.lb_send_note.setText("")
        if self.chk_periodic.isChecked():
            self._send_timer.start(self._period_ms())

    def _close_serial(self):
        self._send_timer.stop()
        self.opened = False
        # 先置关闭标志再收尾，避免 _finish_file_send 内部恢复周期发送（此时串口已不可用）
        self._finish_file_send(completed=None)
        if self.source is not None:
            for sig, slot in ((self.source.data, self._on_data),
                              (self.source.error, self._on_source_error),
                              (self.source.finished, self._on_source_finished)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self.source.stop()
            # 延长等待时间至 5s；超时 terminate 前手动关闭串口句柄，
            # 避免被强制终止的线程跳过 finally 块导致端口泄漏。
            if not self.source.wait(5000):
                try:
                    ser = getattr(self.source, "_ser", None)
                    if ser is not None and ser.is_open:
                        ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self.source.terminate()
                self.source.wait()
            self.source = None
        # BUG-19/SOP-08：冲刷增量解码器末尾不完整的多字节字符，避免丢尾
        self._flush_decoder_tail()
        for widget in (self.cb_port, self.cb_baud, self.cb_data, self.cb_stop,
                  self.cb_parity, self.cb_flow, self.cb_enc,
                  self.chk_dtr, self.chk_rts, self.btn_refresh, self.cb_proto):
            widget.setEnabled(True)
        self._open_btn().setText(tr("serial.open"))
        self._open_state_lb().setText(tr("serial.state_closed"))
        self.lb_send_note.setText("")

    def _on_source_error(self, msg):
        if not self.opened:
            return
        # 按当前通讯方式（串口/网口）关闭，避免网口错误误走串口关闭逻辑
        was_net = self._net_mode()
        self._close_source()
        QMessageBox.critical(self, tr("net.err_title") if was_net
                              else tr("serial.err_title"), msg)

    def _on_source_finished(self):
        # 按当前通讯方式关闭（网口断连/串口异常统一处理）
        if self.opened:
            self._close_source()

    def _flush_decoder_tail(self):
        """冲刷增量解码器末尾不完整的多字节字符到接收区，避免丢尾。

        在关闭串口/网口、切换编码前调用（原 _close_serial/_close_net 内两处
        重复实现收敛于此，SOP-08 去冗余）。
        """
        try:
            tail = self._decimals.decode(b"", final=True)
            if not tail:
                return
            if self.chk_hex_rx.isChecked():
                self._insert_single_line(tail.encode(self.cb_enc.currentText(),
                                                     errors="replace").hex(" ") + "\n",
                                         RX_COLOR)
            else:
                self._append_text(tail)
        except Exception:  # noqa: BLE001
            pass

    def _on_enc_changed(self, enc: str):
        """编码切换即时生效：先冲刷旧解码器末尾，再按新编码重建解码器。

        BUG-S 修复：此前编码下拉仅同步终端配置，打开状态下切换编码不会重建
        `_decimals`，导致解码仍按旧编码进行（GBK 数据显示乱码）。
        """
        self._flush_decoder_tail()
        self._decimals = self._new_decoder()
        self._sync_instant_terminal_config()

    # ---------------------------------------------------------------- 接收
    def _on_data(self, data: bytes):
        if not self.opened or self.source is None:
            return
        try:
            self._on_data_impl(data)
        except Exception:
            # 数据接收/解析/写入任何一环异常都不能让 Qt 事件循环崩溃：
            # 记录到崩溃日志后继续接收，保证通讯终端不中断。
            _log_main_error("MainWindow._on_data")

    def _on_data_impl(self, data: bytes):
        self._rx_bytes += len(data)
        self.lb_rx_count.setText(trf("terminal.rx_bytes", n=self._rx_bytes))
        # 显示：编码与展示分离，波形解析始终按文本进行
        text = self._decimals.decode(data)
        if self.chk_hex_rx.isChecked():
            # SOP-06：接收区 Binary 模式 → 标准 hexdump（偏移+Hex+ASCII，按列宽分页）
            self._insert_hex_bytes(data, RX_COLOR)
        elif text:
            self._append_text(text)

        # 波形：字节级切行，按累计接收字节偏移计算精确到达时刻
        self._session_bytes += len(data)
        self._tim_buf.extend(data)
        self._extract_timed_lines()

    def _extract_timed_lines(self):
        buffer = self._tim_buf
        n = len(buffer)
        if n == 0:
            return
        start_abs = self._session_bytes - n   # buffer[0] 的绝对字节偏移
        idx = 0
        enc = self.cb_enc.currentText()
        while idx < n:
            idx_nl = buffer.find(b"\n", idx)
            idx_cr = buffer.find(b"\r", idx)
            candidates = [k for k in (idx_nl, idx_cr) if k >= 0]
            if not candidates:
                break
            split_pos = min(candidates)
            j = split_pos
            while j < n and buffer[j] in (0x0A, 0x0D):
                j += 1
            line_bytes = bytes(buffer[idx:split_pos])
            abs_start = start_abs + idx
            # 时间戳取「行首字节」的到达时刻：与虚拟源的串行时钟一致（行首即该帧采样时刻）
            timestamp_sec = abs_start * self._t_per_byte
            if line_bytes:
                self._handle_line(line_bytes.decode(enc, errors="replace"), timestamp_sec)
            idx = j
        if idx > 0:
            del buffer[:idx]
        # 无行尾的超长缓冲保护：整体作为一行冲刷，避免内存无界增长
        if len(buffer) > 8192:
            abs_start = self._session_bytes - len(buffer)
            timestamp_sec = abs_start * self._t_per_byte
            text = bytes(buffer).decode(enc, errors="replace")
            if text:
                self._handle_line(text, timestamp_sec)
            buffer.clear()

    def _insert_term(self, text, color=None):
        self.rx_edit.append_rx(text, color,
                               autoscroll=self.chk_autoscroll.isChecked())

    def _insert_single_line(self, text, color):
        """插入单条显示行（HEX 接收 / 发送回显）。
        SOP V3.0：行号/时间戳改由终端渲染层分配，主窗口只传纯文本。"""
        self.rx_edit.append_rx(text, color,
                               autoscroll=self.chk_autoscroll.isChecked())

    def _insert_hex_bytes(self, data: bytes, color):
        """SOP-06：标准 hexdump 显示。累积字节按列宽（8/16/24/32）分页输出，
        每行 = 8 位十六进制偏移 + Hex 字节列（大写、空格分隔）+ ASCII 可读列
        （不可打印以 '.' 占位），逐字节无损呈现。偏移自打开串口/清屏后累计。"""
        if not data:
            return
        self._hex_buf.extend(data)
        buffer = self._hex_buf
        col = self._hex_cols
        n = len(buffer)
        rows = []
        row_count = n // col
        for r in range(row_count):
            rows.append((self._hex_offset + r * col, bytes(buffer[r * col:(r + 1) * col])))
        if row_count:
            del buffer[:row_count * col]
            self._hex_offset += row_count * col
        # Bug X 修复：不足一列的残字节立即作为末行输出，保证逐字节无损显示，
        # 不依赖后续数据凑满一列或切模式才 flush（否则单字节信号永不显示）。
        if buffer:
            rows.append((self._hex_offset, bytes(buffer)))
            self._hex_offset += len(buffer)
            buffer.clear()
        for offset, row_bytes in rows:
            hex_str = " ".join(f"{b:02X}" for b in row_bytes)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row_bytes)
            text = f"{offset:08X}  {hex_str:<{col * 3 - 1}}  {asc}\n"
            self._insert_single_line(text, color)
        # HEX 视图同样受显示上限约束：写入后即时回滚，保证行数/容量上限持续生效。
        self.rx_edit._trim()

    def _on_hex_cols_changed(self, text: str):
        """SOP-06：Hex 列数 8/16/24/32 即时生效。"""
        try:
            self._hex_cols = int(text)
        except (TypeError, ValueError):
            self._hex_cols = 16

    def _on_ts_fmt_changed(self, idx: int):
        """SOP-04：时间戳格式 秒/毫秒 即时生效（对后续新行生效，历史固化不变）。"""
        format_str = self.cb_ts_fmt.itemData(idx) if self.cb_ts_fmt.count() > 0 else "ms"
        self._ts_fmt = format_str or "ms"
        self._sync_instant_terminal_config()

    def _on_term_context_menu(self, pos):
        """终端本地化右键菜单：复制 / 全选 / 清空显示。"""
        menu = QMenu(self)
        a_copy = menu.addAction(tr("terminal.menu.copy"))
        a_sel = menu.addAction(tr("terminal.menu.select_all"))
        menu.addSeparator()
        a_clear = menu.addAction(tr("terminal.menu.clear"))
        chosen = menu.exec(self.rx_edit.mapToGlobal(pos))
        menu.deleteLater()
        if chosen == a_copy:
            self.rx_edit.copy()
        elif chosen == a_sel:
            self.rx_edit.selectAll()
        elif chosen == a_clear:
            self._clear_rx()

    def _on_display_mode_changed(self, *_):
        # HEX/文本、时间戳开/关均会打乱续行语义：清空续行缓冲避免跨模式错位/乱码
        # SOP-06：HEX 关 → flush 不足一列的残留字节；HEX 开 → 从新偏移重新开始
        if not self.chk_hex_rx.isChecked():
            self._flush_hex_remaining()
        else:
            self._hex_buf = bytearray()
            self._hex_offset = 0
        # T-01/T-02 修复：同步装饰开关给即时输入终端
        self._sync_instant_terminal_config()

    def _flush_hex_remaining(self):
        """SOP-06：把不足一列的残留 hex 字节作为末行输出并清零缓冲。"""
        buffer = self._hex_buf
        if not buffer:
            return
        col = self._hex_cols
        n = len(buffer)
        hex_str = " ".join(f"{b:02X}" for b in buffer)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in buffer)
        text = f"{self._hex_offset:08X}  {hex_str:<{col * 3 - 1}}  {asc}\n"
        self._insert_single_line(text, RX_COLOR)
        self._hex_buf = bytearray()
        self._hex_offset += n

    def _append_text(self, text, with_ts=None):
        """RX 文本显示：V1.29 半行缓冲改由终端内部处理。
        主窗口只负责把解码文本传给终端，终端内部统一做半行缓冲、
        行号/时间戳渲染层分配与设备回显去重，杜绝行号跳号与乱序。"""
        if not text:
            return
        self._insert_term(text)

    def _on_wrap(self, checked):
        from PySide6.QtWidgets import QPlainTextEdit as _QPTE
        self.rx_edit.setLineWrapMode(_QPTE.LineWrapMode.WidgetWidth if checked
                                     else _QPTE.LineWrapMode.NoWrap)

    def _on_pause_rx(self, checked):
        """暂停显示：冻结画面但后台继续接收缓存，取消后回放并滚到底部。"""
        if hasattr(self, "rx_edit"):
            self.rx_edit.set_paused(checked)

    def _on_rx_cap_changed(self, text):
        """CACHE-01 修复：接收缓存支持行数和容量（MB/GB）两种模式。
        行数模式：set_max_blocks(n)；容量模式：set_max_bytes(n * 单位)。"""
        text = text.strip()
        if text.endswith("行"):
            try:
                n = int(text.replace("行", "").strip())
            except (TypeError, ValueError):
                return
            if hasattr(self, "rx_edit"):
                self.rx_edit.set_max_blocks(n)
                self.rx_edit.set_max_bytes(0)  # 0 表示不限制字节
        elif text.upper().endswith("GB"):
            try:
                giga_bytes = int(text.upper().replace("GB", "").strip())
            except (TypeError, ValueError):
                return
            if hasattr(self, "rx_edit"):
                self.rx_edit.set_max_bytes(giga_bytes * 1024 * 1024 * 1024)
                self.rx_edit.set_max_blocks(0)
        elif text.upper().endswith("MB"):
            try:
                mega_bytes = int(text.upper().replace("MB", "").strip())
            except (TypeError, ValueError):
                return
            if hasattr(self, "rx_edit"):
                self.rx_edit.set_max_bytes(mega_bytes * 1024 * 1024)
                self.rx_edit.set_max_blocks(0)

    def _handle_line(self, line, ts):
        self._raw_lines.append((ts, line))
        res = self.parser.parse(line)
        if res:
            # 唯一数据写入路径：通讯终端解析出的数据帧写入 DataHub 数据总线，
            # 波形/FFT/分布图三个窗口只读消费，互不直接引用。
            self.dh.append_frame(ts, res)

    # ---------------------------------------------------------------- 发送
    def _on_hex_tx_toggled(self, on):
        """HEX 发送勾选：把输入框字符串实时转成 HEX 显示；取消则恢复字符串显示。

        显示转换与真实发送口径一致（按当前编码编码后取十六进制、空格分隔），
        因此 HEX 模式发出的字节恰等于原字符串的编码字节，仅视觉呈现发生变化。
        """
        self.chk_esc.setEnabled(not on)
        if not hasattr(self, "input_line"):
            return
        enc = self.cb_enc.currentText() if hasattr(self, "cb_enc") else "utf-8"
        if on:
            self._hex_tx_source = self.input_line.text()
            if self._hex_tx_source:
                try:
                    body = self._hex_tx_source.encode(enc, errors="replace")
                    self.input_line.setText(body.hex(" ").upper())
                except Exception:  # noqa: BLE001
                    # BUG-08 修复：编码失败时回退复选框状态，避免 HEX 模式已开启
                    # 但输入框仍显示原字符串、发送时按 HEX 解析必然报错。
                    self.chk_hex_tx.blockSignals(True)
                    self.chk_hex_tx.setChecked(False)
                    self.chk_hex_tx.blockSignals(False)
                    self.chk_esc.setEnabled(True)
                    return
        else:
            cur = self.input_line.text().strip()
            decoded = None
            try:
                if cur:
                    decoded = hex_to_bytes(cur).decode(enc, errors="replace")
            except ValueError:
                decoded = None
            if decoded is None:
                decoded = self._hex_tx_source
            self.input_line.setText(decoded or "")

    def _new_decoder(self):
        """按当前编码名创建增量解码器（errors=replace，替换非法字节）。"""
        return codecs.getincrementaldecoder(self.cb_enc.currentText())(errors="replace")

    def _build_payload(self, data: str, is_hex: bool, newline_label: str, escapes: bool = False,
                       checksum_label: str = "无") -> bytes:
        if is_hex:
            body = hex_to_bytes(data)
        elif escapes:
            body = interpret_escapes(data, self.cb_enc.currentText())
        else:
            body = data.encode(self.cb_enc.currentText(), errors="replace")
        body = body + compute_checksum(body, checksum_label)
        return body + newline_bytes(newline_label)

    def _do_write(self, payload: bytes, echo: bool = True):
        if not self.opened or self.source is None:
            self.lb_send_note.setText(tr("terminal.send_not_open"))
            return False
        try:
            ok = self.source.write(payload)
        except Exception:  # noqa: BLE001
            ok = False
        if bool(ok):
            self._tx_bytes += len(payload)
            self.lb_tx_count.setText(trf("terminal.tx_bytes", n=self._tx_bytes))
            if echo and self.chk_echo.isChecked():
                self._echo_tx(payload)
        self.lb_send_note.setText("" if ok else tr("terminal.send_failed"))
        return bool(ok)

    def _echo_tx(self, payload: bytes):
        """发送回显：与接收区视觉逻辑一致。

        T-03 修复：文本模式下按 \\n 分割逐行回显（每行独立行号/时间戳），
        而非把整个 payload 作为一行。
        T-04 修复：HEX 发送或 HEX 接收模式下始终显示十六进制，避免二进制 decode 乱码。
        本地回显 = 文本编辑器式——本地金色显示，设备确认回显与本地输入
        顺序配对消费（不重复显示），退格/回车编辑与系统文本编辑器一致。
        """
        enc = self.cb_enc.currentText()
        hex_rx = self.chk_hex_rx.isChecked()
        hex_tx = self.chk_hex_tx.isChecked()
        if hex_rx:
            # 接收区 Binary(hexdump) 模式：发送回显纳入同一 hex 字节流（偏移连续）
            self._insert_hex_bytes(payload, ECHO_COLOR)
            return
        if hex_tx:
            # 仅发送 HEX（接收区文本）：显示空格分隔 hex 串
            self._insert_single_line(payload.hex(" ") + "\n", ECHO_COLOR)
            return
        # 文本模式：按行分割，逐行回显（与接收区 _append_text 逻辑一致）
        text = payload.decode(enc, errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        if text.endswith("\n"):
            if lines and lines[-1] == "":
                lines.pop()
        for line in lines:
            self._insert_single_line(line + "\n", ECHO_COLOR)

    def _on_instant_bytes(self, payload: bytes):
        """即时输入（Instant Send）产生的原始字节：直接写入串口，本地回显由终端自行处理。"""
        if not self.opened or self.source is None:
            self.lb_send_note.setText(tr("terminal.send_not_open"))
            return
        try:
            ok = self.source.write(payload)
        except Exception:  # noqa: BLE001
            ok = False
        if bool(ok):
            self._tx_bytes += len(payload)
            self.lb_tx_count.setText(trf("terminal.tx_bytes", n=self._tx_bytes))
            self.lb_send_note.setText("")
        else:
            self.lb_send_note.setText(tr("terminal.send_failed"))

    def _on_enter_nl_changed(self, idx):
        """终端工具栏「回车行尾」变化：同步底部「行尾」下拉并应用到即时输入终端。"""
        data = self.cb_enter_nl.currentData()
        if self.cb_newline.currentData() != data:
            self.cb_newline.blockSignals(True)
            self.cb_newline.setCurrentIndex(self.cb_newline.findData(data))
            self.cb_newline.blockSignals(False)
        self._sync_instant_terminal_config()

    def _sync_newline_both(self):
        """底部「行尾」变化：同步终端工具栏「回车行尾」下拉并应用。"""
        data = self.cb_newline.currentData()
        if hasattr(self, "cb_enter_nl") and self.cb_enter_nl.currentData() != data:
            self.cb_enter_nl.blockSignals(True)
            self.cb_enter_nl.setCurrentIndex(self.cb_enter_nl.findData(data))
            self.cb_enter_nl.blockSignals(False)
        self._sync_instant_terminal_config()

    def _sync_instant_terminal_config(self):
        """把本地回显 / 编码 / 行尾 / 装饰开关同步给即时输入终端。

        T-01/T-02 修复：同步行号/时间戳/HEX 回显开关，使即时输入回显与接收区一致。
        """
        if not hasattr(self, "rx_edit"):
            return
        self.rx_edit.set_echo(self.chk_echo.isChecked())
        self.rx_edit.set_encoding(self.cb_enc.currentText())
        self.rx_edit.set_newline_bytes(
            newline_bytes(self.cb_newline.currentData() or "无"))
        self.rx_edit.set_lineno(self.chk_lineno.isChecked())
        self.rx_edit.set_timestamp(self.chk_ts.isChecked())
        self.rx_edit.set_timestamp_format(self._ts_fmt)
        self.rx_edit.set_hex_echo(self.chk_hex_rx.isChecked())

    def _set_terminal_prompt(self):
        if hasattr(self, "rx_edit"):
            self.rx_edit.set_prompt(tr("terminal.prompt"))

    def _on_dtr_rts(self, _checked):
        if self.source is not None:
            self.source.set_signal(dtr=self.chk_dtr.isChecked(), rts=self.chk_rts.isChecked())

    def _clear_counts(self):
        self._rx_bytes = 0
        self._tx_bytes = 0
        self.lb_rx_count.setText(trf("terminal.rx_bytes", n=0))
        self.lb_tx_count.setText(trf("terminal.tx_bytes", n=0))

    def _clear_rx(self):
        # BUG-03 修复：终端清空时同步清空波形，避免波形数据残留但原始行缓冲已丢、
        # 导致后续「应用并重绘」无效。waveform.clear() 触发 _on_waveform_cleared
        # 再次清空原始行缓冲（幂等，无害）。
        self.rx_edit.reset()
        self._raw_lines.clear()
        self._tim_buf.clear()
        # BUG-H 修复：清空接收内容时同步重置接收字节计数，
        # 避免计数显示与接收区内容不一致（显示信息实时同步）。
        self._rx_bytes = 0
        self.lb_rx_count.setText(trf("terminal.rx_bytes", n=0))
        # SOP V3.0：行号计数器改由终端内部管理（reset 时自动重置）
        self._hex_buf = bytearray()
        self._hex_offset = 0
        self._decimals = self._new_decoder()
        if hasattr(self, "waveform"):
            self.waveform.clear()
        # 终端清空时同步清空分布图，各窗口数据一致
        if hasattr(self, "dist"):
            self.dist_panel._mark_dirty()
            self.dist_panel.refresh()

    def _on_channels_changed(self):
        """通道启停变化：同步 FFT 通道下拉与分布图刷新。"""
        if hasattr(self, "fft_panel"):
            self.fft_panel.sync_channels()
        if hasattr(self, "dist_panel"):
            self.dist_panel._mark_dirty()
            self.dist_panel.refresh()

    def _on_waveform_cleared(self):
        self._raw_lines.clear()
        self._tim_buf.clear()
        # SOP V3.0：行号计数器改由终端内部管理
        self._decimals = self._new_decoder()

    def _send(self):
        """周期发送：重复发送当前输入行内容（支持[delay NNN]延时标记）。
        周期间隔只作用于两次完整循环之间，即发送完最后一条指令后才开始计时。"""
        if self._file_send_fh is not None:
            self.lb_send_note.setText(tr("terminal.sending_file"))
            return
        text = self.input_line.text().rstrip("\n\r")
        if not text:
            return
        # 停止定时器，避免延时发送期间重复触发
        self._send_timer.stop()
        self._periodic_active = True
        self._send_line(text)

    def _do_send_text(self, text):
        if self._file_send_fh is not None:
            self.lb_send_note.setText(tr("terminal.sending_file"))
            return
        try:
            payload = self._build_payload(text, self.chk_hex_tx.isChecked(),
                                          self.cb_newline.currentData() or "无",
                                          self.chk_esc.isChecked(),
                                          self.cb_checksum.currentData() or "无")
        except ValueError:
            QMessageBox.warning(self, tr("terminal.hex_error_title"), tr("terminal.hex_error_msg"))
            return
        self._do_write(payload)

    def _send_line(self, text: str):
        text = text.rstrip("\n\r")
        if not text:
            return
        # 延时发送：解析 [delay NNN] 标记，分段发送，每段之间延时指定毫秒
        import re
        parts = re.split(r'\[delay\s+(\d+)\]', text, flags=re.IGNORECASE)
        # parts 格式：[seg0, delay1, seg1, delay2, seg2, ...]
        if len(parts) <= 1:
            self._do_send_text(text)
            self._periodic_check_next()
            return
        # 构建发送队列：[(segment, delay_ms), ...]
        queue = []
        for i in range(0, len(parts), 2):
            seg = parts[i]
            delay = int(parts[i + 1]) if i + 1 < len(parts) else 0
            if seg:
                queue.append((seg, delay))
        if not queue:
            self._periodic_check_next()
            return
        self._send_delayed_queue(queue, 0)

    def _send_delayed_queue(self, queue, idx):
        """依次发送队列中的指令，每段发送后延时指定毫秒。"""
        if idx >= len(queue):
            self._periodic_check_next()
            return
        seg, delay = queue[idx]
        self._do_send_text(seg)
        if idx + 1 < len(queue) and delay > 0:
            QTimer.singleShot(delay, lambda: self._send_delayed_queue(queue, idx + 1))
        elif idx + 1 >= len(queue):
            # 最后一段发送完成，检查是否启动下一次周期
            self._periodic_check_next()

    def _periodic_check_next(self):
        """周期发送完成后检查：如果周期发送开启，启动下一次周期定时器。
        周期间隔只作用于两次完整循环之间。"""
        if getattr(self, "_periodic_active", False):
            self._periodic_active = False
            if self.opened and self.chk_periodic.isChecked() and self._file_send_fh is None:
                self._send_timer.start(self._period_ms())

    def _on_send_line_clicked(self):
        text = self.input_line.text().rstrip("\n\r")
        if not text:
            return
        self.input_line.record(text)
        self._send_line(text)
        self.input_line.clear()

    def _send_item(self, item):
        if self._file_send_fh is not None:
            self.lb_send_note.setText(tr("terminal.sending_file"))
            return
        try:
            payload = self._build_payload(item["data"], item["hex"], item["newline"],
                                          self.chk_esc.isChecked(),
                                          self.cb_checksum.currentData() or "无")
        except ValueError:
            QMessageBox.warning(self, tr("terminal.hex_error_title"),
                                trf("terminal.hex_error_item", name=item["name"]))
            return
        self._do_write(payload)

    def _send_file(self):
        # BUG-07 修复：切换文件时直接中止当前发送但不恢复周期发送，
        # 避免用户在文件选择对话框点「取消」后周期发送意外启动。
        if self._file_send_fh is not None:
            file_handle = self._file_send_fh
            self._file_send_fh = None
            self._file_send_timer.stop()
            try:
                file_handle.close()
            except OSError:
                pass
            self.lb_send_note.setText("")
            self._file_send_sent = 0
            self._file_send_total = 0
        path, _ = QFileDialog.getOpenFileName(self, tr("terminal.file_select"))
        if not path:
            # 用户取消：若之前周期发送是开启的，恢复它
            self._resume_periodic_if_needed()
            return
        try:
            file_handle = open(path, "rb")
            size = os.path.getsize(path)
        except OSError as exc:
            QMessageBox.critical(self, tr("terminal.file_error"), str(exc))
            return
        if size == 0:
            file_handle.close()
            QMessageBox.information(self, tr("terminal.file_empty"), tr("terminal.file_empty_msg"))
            return
        if not self.opened or self.source is None:
            file_handle.close()
            self.lb_send_note.setText(tr("terminal.send_not_open"))
            return
        self._file_send_fh = file_handle
        self._file_send_sent = 0
        self._file_send_total = size
        self.lb_send_note.setText(trf("terminal.file_progress", sent=0, total=size))
        self._send_timer.stop()
        self._file_send_timer.start()

    def _finish_file_send(self, completed):
        file_handle = self._file_send_fh
        self._file_send_fh = None
        if file_handle is not None:
            try:
                file_handle.close()
            except OSError:
                pass
        self._file_send_timer.stop()
        self._resume_periodic_if_needed()
        if completed is True:
            note = trf("terminal.file_done", n=self._file_send_sent)
        elif completed is False:
            note = tr("terminal.file_failed")
        else:
            note = "" if not self._file_send_sent else trf("terminal.file_aborted", n=self._file_send_sent)
        self.lb_send_note.setText(note)
        self._file_send_sent = 0
        self._file_send_total = 0

    def _file_send_step(self):
        file_handle = self._file_send_fh
        if file_handle is None:
            self._file_send_timer.stop()
            return
        if not self.opened or self.source is None:
            self._finish_file_send(completed=None)
            return
        try:
            chunk = file_handle.read(4096)
        except OSError:
            self._finish_file_send(completed=False)
            self.lb_send_note.setText(tr("terminal.file_read_failed"))
            return
        if not chunk:
            self._finish_file_send(completed=True)
            self._resume_periodic_if_needed()
            return
        if not self._do_write(chunk, echo=False):
            self._finish_file_send(completed=False)
            return
        self._file_send_sent += len(chunk)
        self.lb_send_note.setText(trf("terminal.file_progress",
                                      sent=self._file_send_sent, total=self._file_send_total))

    def _resume_periodic_if_needed(self):
        # 仅当定时器当前未运行时才启动，避免用户取消文件选择时
        # 重置已在运行的周期发送定时器（导致下一次发送被延迟）。
        if self.opened and self.chk_periodic.isChecked() and not self._send_timer.isActive():
            self._send_timer.start(self._period_ms())

    def _on_periodic(self, checked):
        if checked and self.opened:
            self._send_timer.start(self._period_ms())
        else:
            self._send_timer.stop()
            self._periodic_active = False

    def _on_period_changed(self, value):
        if self.chk_periodic.isChecked() and self._send_timer.isActive():
            self._send_timer.setInterval(int(round(value)))

    def _period_ms(self):
        """周期发送间隔（毫秒，整数），供定时器使用。"""
        return max(1, int(round(self.sp_period.value())))

    # ---------------------------------------------------------------- 格式/波形
    def _apply_format(self):
        format_str = self.fmt_edit.text().strip()
        # Bug W 修复：数据按真实换行切行（_extract_timed_lines 已去掉行尾
        # CR/LF），格式串末尾若含字面 \r\n / \n / \r 转义，正则将期望匹配
        # 不存在的行尾字符而永失败；此处将其作为行结束符剥离。
        for line_tail in ("\\r\\n", "\\n", "\\r"):
            if format_str.endswith(line_tail):
                format_str = format_str[: -len(line_tail)]
                break
        self.parser.set_format(format_str)
        n = self.parser.num_channels
        self.waveform.setup_channels(n)
        # 从格式串解析单位，更新各通道单位（解析到则更新，未解析到保持默认V）
        for i, unit in enumerate(self.parser.channel_units):
            if i in self.waveform.channels and unit:
                # 规范化单位（mv→mV、uv/μv→µV 等），保证各窗口单位显示一致
                self.waveform.channels[i]["unit"] = self.waveform._normalize_unit(unit)
        # 重建通道表以反映新单位
        self.waveform._rebuild_channel_table()
        # 立即刷新自动测量面板的单位标签与读数（防止通道列已更新而测量面板仍显示旧单位）
        self.waveform._on_meas_ch_changed()
        self.fft_panel.sync_channels()
        self.dist_panel._mark_dirty()
        frames = [(ts, res) for ts, line in self._raw_lines
                  if (res := self.parser.parse(line))]
        self.waveform.bulk_add(frames)
        self._refresh_fmt_info()

    def _refresh_fmt_info(self):
        """仅刷新格式提示文案（语言切换时使用，不做破坏性重建）。"""
        n = self.parser.num_channels
        if n == 0:
            self.lb_fmt_info.setText(tr("wave.no_channel"))
        else:
            self.lb_fmt_info.setText(trf("wave.chan_count", n=n,
                                         names="、".join(self.waveform.channels[c]["name"]
                                                         for c in self.waveform.channels)))

    def _save_rx(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("save.rx_title"), "rx.txt",
                                              tr("save.file_ok"))
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.rx_edit.toPlainText())
        from .export_dialogs import show_saved_dialog
        show_saved_dialog(self, tr("save.title"), trf("save.done", path=path), path)

    # ---------------------------------------------------------------- 语言切换
    def _retranslate(self):
        self.setWindowTitle(tr("app.title"))

        # 菜单
        self.menu_file.setTitle(tr("menu.file"))
        self.menu_view.setTitle(tr("menu.view"))
        self.menu_lang.setTitle(tr("menu.language"))
        self.menu_settings.setTitle(tr("menu.settings"))
        self.menu_comm.setTitle(tr("menu.settings.comm"))
        self.act_comm_serial.setText(tr("menu.settings.comm.serial"))
        self.act_comm_net.setText(tr("menu.settings.comm.net"))
        self.menu_help.setTitle(tr("menu.help"))
        self.act_save_rx.setText(tr("menu.file.save_rx"))
        self.act_send_file.setText(tr("menu.file.send_file"))
        self.act_export_csv.setText(tr("menu.file.export_csv"))
        self.act_exit.setText(tr("menu.file.exit"))
        self.act_view_terminal.setText(tr("menu.view.terminal"))
        self.act_view_waveform.setText(tr("menu.view.waveform"))
        self.act_view_fft.setText(tr("menu.view.fft"))
        self.act_view_dist.setText(tr("menu.view.dist"))
        self.menu_theme.setTitle(tr("menu.view.theme"))
        self.act_theme_dark.setText(tr("menu.theme.dark"))
        self.act_theme_light.setText(tr("menu.theme.light"))
        self.act_theme_dark.setChecked(self.theme.theme == THEME_DARK)
        self.act_theme_light.setChecked(self.theme.theme == THEME_LIGHT)
        self.act_lang_zh.setText(tr("menu.language.zh"))
        self.act_lang_en.setText(tr("menu.language.en"))
        self.act_manual.setText(tr("menu.help.manual"))
        self.act_about.setText(tr("menu.help.about"))
        self.act_lang_zh.setChecked(current_lang() == LANG_ZH)
        self.act_lang_en.setChecked(current_lang() == LANG_EN)

        # 页签
        self.tab_widget.setTabText(0, tr("tab.terminal"))
        self.tab_widget.setTabText(1, tr("tab.waveform"))
        self.tab_widget.setTabText(2, tr("tab.fft"))
        self.tab_widget.setTabText(3, tr("tab.dist"))

        # 通讯方式（串口/网口互斥，由菜单「设置->通讯接口」控制，
        # cb_proto 仅作为内部模式状态保留，不显示）
        self.cb_proto.blockSignals(True)
        self.cb_proto.clear()
        self.cb_proto.addItem(tr("net.proto_serial"), "serial")
        self.cb_proto.addItem(tr("net.proto_net"), "net")
        self.cb_proto.setCurrentIndex(1 if self._net_mode() else 0)
        self.cb_proto.blockSignals(False)
        # 网口设置
        self.grp_net.setTitle(tr("net.settings"))
        self.lb_net_proto.setText(tr("net.proto"))
        _net_proto_cur = self.cb_net_proto.currentData()   # 语言切换前保存协议
        self.cb_net_proto.blockSignals(True)
        self.cb_net_proto.clear()
        self.cb_net_proto.addItem(tr("net.tcp_client"), "tcp_client")
        self.cb_net_proto.addItem(tr("net.tcp_server"), "tcp_server")
        self.cb_net_proto.addItem(tr("net.udp"), "udp")
        _np_idx = self.cb_net_proto.findData(_net_proto_cur)
        self.cb_net_proto.setCurrentIndex(_np_idx if _np_idx >= 0 else 0)
        self.cb_net_proto.blockSignals(False)
        self.lb_net_host.setText(tr("net.host"))
        self.lb_net_port.setText(tr("net.remote_port"))
        self.lb_net_localip.setText(tr("net.local_ip"))
        self.lb_net_local.setText(tr("net.local_port"))

        # 串口设置
        self.grp_serial.setTitle(tr("serial.group"))
        self.lb_port.setText(tr("serial.port"))
        self.lb_baud.setText(tr("serial.baud"))
        self.lb_data.setText(tr("serial.data_bits"))
        self.lb_stop.setText(tr("serial.stop_bits"))
        self.lb_parity.setText(tr("serial.parity"))
        self.lb_flow.setText(tr("serial.flow"))
        self.lb_enc.setText(tr("serial.encoding"))
        self.lb_ctrl.setText(tr("serial.ctrl_lines"))
        self.btn_refresh.setText(tr("serial.refresh"))
        self.chk_echo.setText(tr("serial.local_echo"))
        if self._net_mode():
            self._open_btn().setText(tr("net.close" if self.opened else "net.open"))
            self._open_state_lb().setText(tr("net.state_open" if self.opened else "net.state_closed"))
        else:
            self._open_btn().setText(tr("serial.close" if self.opened else "serial.open"))
            self._open_state_lb().setText(tr("serial.state_open" if self.opened
                                        else "serial.state_closed"))
        self._sync_comm_menu_actions()

        # 终端
        self.grp_term.setTitle(tr("terminal.group"))
        self.chk_hex_rx.setText(tr("terminal.hex_disp"))
        self.chk_ts.setText(tr("terminal.timestamp"))
        self.chk_lineno.setText(tr("terminal.lineno"))
        self.chk_autoscroll.setText(tr("terminal.autoscroll"))
        self.chk_pause_rx.setText(tr("terminal.pause"))
        self.chk_wrap.setText(tr("terminal.wrap"))
        self.lb_enter_nl.setText(tr("terminal.enter_newline"))
        self.lb_rx_cap.setText(tr("terminal.rx_cap"))
        self.btn_clear_rx.setText(tr("terminal.clear"))
        self.btn_save_rx.setText(tr("terminal.save"))
        self.btn_clear_count.setText(tr("terminal.reset_count"))
        self.chk_hex_tx.setText(tr("terminal.hex_tx"))
        self.chk_esc.setText(tr("terminal.escape"))
        self.lb_newline.setText(tr("terminal.newline"))
        self.lb_checksum.setText(tr("terminal.checksum"))
        self.chk_periodic.setText(tr("terminal.periodic"))
        self.sp_period.retranslate()
        self.btn_send_file.setText(tr("terminal.send_file"))

        self.btn_send.setText(tr("terminal.send"))
        self.input_line.setPlaceholderText(tr("terminal.input_placeholder"))
        self.lb_rx_count.setText(trf("terminal.rx_bytes", n=self._rx_bytes))
        self.lb_tx_count.setText(trf("terminal.tx_bytes", n=self._tx_bytes))

        # 波形/格式
        self.lb_fmt_label.setText(tr("wave.fmt_label"))
        self.btn_apply_fmt.setText(tr("wave.apply"))
        self._refresh_fmt_info()

        # 语言相关下拉框
        self._reload_language_combos()
        self.waveform.retranslate()
        self.fft_panel.retranslate()
        self.dist_panel.retranslate()
        self.quick_bar.retranslate()
        # 即时输入终端的提示符/回显/编码/行尾
        self._set_terminal_prompt()
        self._sync_instant_terminal_config()

    def _reload_language_combos(self):
        # 校验位
        cur = self.cb_parity.currentData()
        self.cb_parity.blockSignals(True)
        self.cb_parity.clear()
        for code, key in _PARITY_OPTIONS:
            self.cb_parity.addItem(_combo_text(code, key), code)
        self.cb_parity.setCurrentIndex(max(0, self.cb_parity.findData(cur)))
        self.cb_parity.blockSignals(False)
        # 流控
        cur = self.cb_flow.currentData()
        self.cb_flow.blockSignals(True)
        self.cb_flow.clear()
        for code, key in _FLOW_OPTIONS:
            self.cb_flow.addItem(_combo_text(code, key), code)
        self.cb_flow.setCurrentIndex(max(0, self.cb_flow.findData(cur)))
        self.cb_flow.blockSignals(False)
        # 行尾（无保存值时默认系统回车：Windows \r\n / Linux/macOS \n）
        cur = self.cb_newline.currentData()
        if not cur:
            cur = _default_newline()
        self.cb_newline.blockSignals(True)
        self.cb_newline.clear()
        for code, key in _NEWLINE_OPTIONS:
            self.cb_newline.addItem(_combo_text(code, key), code)
        self.cb_newline.setCurrentIndex(max(0, self.cb_newline.findData(cur)))
        self.cb_newline.blockSignals(False)
        # 同步终端工具栏「回车行尾」下拉
        if hasattr(self, "cb_enter_nl"):
            self.cb_enter_nl.blockSignals(True)
            self.cb_enter_nl.clear()
            for _code, _key in _NEWLINE_OPTIONS:
                self.cb_enter_nl.addItem(_combo_text(_code, _key), _code)
            self.cb_enter_nl.setCurrentIndex(max(0, self.cb_enter_nl.findData(cur)))
            self.cb_enter_nl.blockSignals(False)
        # 校验（全量：XOR/SUM/CRC8/CRC16/CRC32/Adler/Fletcher）
        cur = self.cb_checksum.currentData()
        self.cb_checksum.blockSignals(True)
        self.cb_checksum.clear()
        for label in checksum_labels():
            if label == CHECKSUM_NONE:
                self.cb_checksum.addItem(tr("terminal.checksum.none"), CHECKSUM_NONE)
            else:
                self.cb_checksum.addItem(label, label)
        self.cb_checksum.setCurrentIndex(max(0, self.cb_checksum.findData(cur)))
        self.cb_checksum.blockSignals(False)
        # 虚拟串口项编码在刷新时已按语言重建
        self._refresh_ports()

    def closeEvent(self, event):
        self._save_config()
        self._close_serial()
        # BUG-P 修复：属性名为 fft_panel（原检查 fft 导致 shutdown 从未执行）
        if hasattr(self, "fft_panel"):
            self.fft_panel.shutdown()
        # BUG-O 修复：显式停止子控件显示计时器（波形/分布图/FFT/悬停帮助/
        # 终端自动滚动），避免窗口关闭瞬间遗留活动 QTimer
        self.waveform.shutdown()
        self.dist_panel.shutdown()
        self.rx_edit.shutdown()
        shutdown_hover()
        super().closeEvent(event)

    # -------------------------------------------------------- 配置持久化
    def _config_state(self) -> ScopeState:
        """从当前界面提取运行时状态快照（单一数据源）。"""
        return ScopeState(
            language=current_lang(),
            theme=self.theme.theme,
            port=self.cb_port.currentData() or "",
            baudrate=self._combo_int(self.cb_baud, 115200),
            data_bits=self._combo_int(self.cb_data, 8),
            stop_bits=self.cb_stop.currentText() or "1",
            parity=self.cb_parity.currentData() or "N",
            flow=self.cb_flow.currentData() or "none",
            dtr=self.chk_dtr.isChecked(),
            rts=self.chk_rts.isChecked(),
            local_echo=self.chk_echo.isChecked(),
            # BUG-18 修复：保存时基真实秒数值，同时保留 index 向后兼容
            timebase_value=float(self.waveform.timebase),
            timebase_index=self.waveform.cb_timebase.currentIndex(),
            max_points=self.waveform.max_points,
            v_unit=self.waveform.v_unit,
        )

    def _save_config(self):
        config = AppConfig()
        config.save_state(self._config_state())
        config.sync()

    def _load_config(self):
        config = AppConfig()
        if not config.has_state():
            return          # 首次运行：保持内置默认值
        state = config.load_state()
        # 主题
        if state.theme in (THEME_DARK, THEME_LIGHT) and state.theme != self.theme.theme:
            self._set_theme(state.theme)
        # 语言（先切换并重译，确保后续回填的组合框数据在正确语言下解析）
        if state.language in (LANG_ZH, LANG_EN) and state.language != current_lang():
            set_language(state.language)
            self._retranslate()
            self._refresh_ports()
        # 串口（启动时尚未打开，直接回填）
        self._restore_combo_data(self.cb_port, state.port)
        self._restore_combo_text(self.cb_baud, str(state.baudrate))
        self._restore_combo_text(self.cb_data, str(state.data_bits))
        self._restore_combo_text(self.cb_stop, state.stop_bits)
        self._restore_combo_data(self.cb_parity, state.parity)
        self._restore_combo_data(self.cb_flow, state.flow)
        self.chk_dtr.setChecked(bool(state.dtr))
        self.chk_rts.setChecked(bool(state.rts))
        self.chk_echo.setChecked(bool(state.local_echo))
        # 示波器
        timebase_combo = self.waveform.cb_timebase
        # BUG-18 修复：优先用时基真实值找最接近档位，fallback 到旧版索引
        if state.timebase_value and state.timebase_value > 0:
            self.waveform._set_timebase_value(float(state.timebase_value))
        elif 0 <= state.timebase_index < timebase_combo.count():
            self.waveform.cb_timebase.setCurrentIndex(state.timebase_index)
        if state.max_points > 0:
            self.waveform.set_max_points(int(state.max_points))
        if state.v_unit:
            self.waveform.ed_unit.setText(state.v_unit)

    @staticmethod
    def _combo_int(combo_box, default):
        try:
            return int(combo_box.currentText())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _restore_combo_text(combo_box, text):
        i = combo_box.findText(text)
        if i >= 0:
            combo_box.setCurrentIndex(i)

    @staticmethod
    def _restore_combo_data(combo_box, data):
        i = combo_box.findData(data)
        if i >= 0:
            combo_box.setCurrentIndex(i)