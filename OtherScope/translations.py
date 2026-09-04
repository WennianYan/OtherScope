# -*- coding: utf-8 -*-
"""国际化（i18n）：简体中文 + English。

默认跟随系统语言，第一备用语言为英文。菜单栏可手动切换。

设计要点：
- 纯 Python 字典，零第三方依赖，便于无头环境自动化测试。
- ``tr(key)`` 按「当前语言 -> 英文 -> key 本身」逐级回退，绝不抛出 KeyError。
- ``trf(key, **kw)`` 支持 ``{name}`` 占位符格式化（对缺失占位符安全）。
"""

from __future__ import annotations

import os

LANG_ZH = "zh"
LANG_EN = "en"


def _detect_system_lang() -> str:
    """跟随系统语言；仅当系统为中文时返回中文，否则回退英文。"""
    name = ""
    try:
        # QLocale 依赖 Qt；在某些极早阶段（QApplication 尚未创建）也可安全读取。
        from PySide6.QtCore import QLocale
        name = QLocale.system().name() or ""
    except Exception:  # noqa: BLE001
        name = ""
    if not name:
        name = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "") or ""
    name = name.lower()
    if name.startswith("zh") or name.startswith("cn"):
        return LANG_ZH
    return LANG_EN


_current_lang = _detect_system_lang()


def current_lang() -> str:
    return _current_lang


def set_language(lang):
    """设置界面语言（"zh"/"en"；兼容 int 0=英文、1=中文，防静默失败）。"""
    global _current_lang
    if lang == 0:
        lang = LANG_EN
    elif lang == 1:
        lang = LANG_ZH
    if lang in (LANG_ZH, LANG_EN):
        _current_lang = lang


# ---------------------------------------------------------------------------
# 翻译表：key -> {"en": ..., "zh": ...}
# 所有对外可见的固定文案集中在此，便于审计与增补。
# ---------------------------------------------------------------------------
STRINGS = {
    # 应用 / 窗口
    "app.title": {"en": "OtherScope · Serial | Waveform | FFT | Distribution",
                  "zh": "其他示波器 · 通讯 | 波形 | 傅立叶 | 数据分布"},
    "menu.file": {"en": "&File", "zh": "文件(&F)"},
    "menu.file.save_rx": {"en": "Save Received Content…", "zh": "保存接收内容(&S)…"},
    "menu.file.send_file": {"en": "Send File…", "zh": "发送文件(&F)…"},
    "menu.file.export_csv": {"en": "Export Waveform CSV…", "zh": "导出波形 CSV(&E)…"},
    "menu.file.exit": {"en": "Exit", "zh": "退出(&X)"},
    "menu.view": {"en": "&View", "zh": "视图(&V)"},
    "menu.view.terminal": {"en": "Terminal", "zh": "通讯终端"},
    "menu.view.waveform": {"en": "Waveform", "zh": "波形示波器"},
    "menu.view.fft": {"en": "FFT Spectrum", "zh": "FFT 频谱"},
    "menu.view.dist": {"en": "Distribution", "zh": "分布图"},
    "menu.view.theme": {"en": "Theme", "zh": "主题"},
    "menu.theme.dark": {"en": "Dark", "zh": "深色"},
    "menu.theme.light": {"en": "Light", "zh": "浅色"},
    "menu.language": {"en": "&Language", "zh": "语言(&L)"},
    "menu.language.zh": {"en": "简体中文", "zh": "简体中文"},
    "menu.language.en": {"en": "English", "zh": "English"},
    "menu.settings": {"en": "&Settings", "zh": "设置(&S)"},
    "menu.settings.comm": {"en": "Communication Interface", "zh": "通讯接口(&C)"},
    "menu.settings.comm.serial": {"en": "Serial Port", "zh": "串口(&S)"},
    "menu.settings.comm.net": {"en": "Network", "zh": "网口(&N)"},
    "menu.help": {"en": "&Help", "zh": "帮助(&H)"},
    "menu.help.manual": {"en": "User Manual", "zh": "使用手册(&U)"},
    "menu.help.about": {"en": "About", "zh": "关于(&A)"},

    # 页签
    "tab.terminal": {"en": "Comm Terminal", "zh": "通讯终端"},
    "tab.waveform": {"en": "Waveform", "zh": "波形示波器"},
    "tab.fft": {"en": "FFT Spectrum", "zh": "FFT 频谱"},
    "tab.dist": {"en": "Distribution", "zh": "分布图"},

    # 通讯方式（串口/网口互斥）
    "net.proto_serial": {"en": "Serial Port", "zh": "串口"},
    "net.proto_net": {"en": "Network Port", "zh": "网口"},
    "net.settings": {"en": "Network Port Settings", "zh": "网口设置"},
    "net.tcp_client": {"en": "TCP Client", "zh": "TCP 客户端"},
    "net.tcp_server": {"en": "TCP Server", "zh": "TCP 服务器"},
    "net.udp": {"en": "UDP", "zh": "UDP"},
    "net.proto": {"en": "Protocol", "zh": "协议"},
    "net.host": {"en": "Remote IP", "zh": "远程 IP"},
    "net.remote_port": {"en": "Remote Port", "zh": "远程端口"},
    "net.local_ip": {"en": "Local IP", "zh": "本地 IP"},
    "net.local_port": {"en": "Local Port", "zh": "本地端口"},
    "net.open": {"en": "Connect", "zh": "连接"},
    "net.close": {"en": "Disconnect", "zh": "断开"},
    "net.state_open": {"en": "Opened", "zh": "已连接"},
    "net.state_closed": {"en": "Closed", "zh": "未连接"},
    "net.err_title": {"en": "Network Port Error", "zh": "网口错误"},

    # 串口设置
    "serial.group": {"en": "Serial Port Settings", "zh": "串口设置"},
    "serial.port": {"en": "Port", "zh": "串口"},
    "serial.baud": {"en": "Baud", "zh": "波特率"},
    "serial.data_bits": {"en": "Data Bits", "zh": "数据位"},
    "serial.stop_bits": {"en": "Stop Bits", "zh": "停止位"},
    "serial.parity": {"en": "Parity", "zh": "校验"},
    "serial.flow": {"en": "Flow", "zh": "流控"},
    "serial.encoding": {"en": "Encoding", "zh": "编码"},
    "serial.open": {"en": "Open Port", "zh": "打开串口"},
    "serial.close": {"en": "Close Port", "zh": "关闭串口"},
    "serial.refresh": {"en": "Refresh", "zh": "刷新"},
    "serial.state_open": {"en": "Opened", "zh": "已打开"},
    "serial.state_closed": {"en": "Closed", "zh": "未打开"},
    "serial.virtual": {"en": "Virtual Port (Demo, no hardware)", "zh": "虚拟串口 (Demo，无需硬件)"},
    "serial.parity.none": {"en": "None", "zh": "无校验 (None)"},
    "serial.parity.even": {"en": "Even", "zh": "偶校验 (Even)"},
    "serial.parity.odd": {"en": "Odd", "zh": "奇校验 (Odd)"},
    "serial.parity.mark": {"en": "Mark", "zh": "标记 (Mark)"},
    "serial.parity.space": {"en": "Space", "zh": "空格 (Space)"},
    "serial.flow.none": {"en": "None", "zh": "无"},
    "serial.flow.rts": {"en": "RTS/CTS", "zh": "RTS/CTS"},
    "serial.flow.xon": {"en": "XON/XOFF", "zh": "XON/XOFF"},
    "serial.ctrl_lines": {"en": "Control Lines", "zh": "控制线"},
    "serial.local_echo": {"en": "Local Echo", "zh": "本地回显"},
    "serial.warn_no_port": {"en": "No serial port selected. Click Refresh and choose one.",
                            "zh": "未选择串口，请先点击“刷新”并选择。"},
    "serial.err_title": {"en": "Serial Port Error", "zh": "串口错误"},

    # 单一面板终端
    "terminal.group": {"en": "Terminal (receive + send in one panel)", "zh": "终端（接收 + 发送同一面板）"},
    "terminal.hex_disp": {"en": "HEX View", "zh": "HEX 显示"},
    "terminal.ts_fmt_s": {"en": "Sec", "zh": "秒"},
    "terminal.ts_fmt_ms": {"en": "ms", "zh": "毫秒"},
    "terminal.timestamp": {"en": "Timestamp", "zh": "加时间戳"},
    "terminal.lineno": {"en": "Line No.", "zh": "行号"},
    "terminal.autoscroll": {"en": "Auto Scroll", "zh": "自动滚动"},
    "terminal.pause": {"en": "Pause View", "zh": "暂停显示"},
    "terminal.wrap": {"en": "Word Wrap", "zh": "自动换行"},
    "terminal.enter_newline": {"en": "Enter NL", "zh": "回车行尾"},
    "terminal.rx_cap": {"en": "RX buffer lines", "zh": "接收缓存行数"},
    "terminal.clear": {"en": "Clear", "zh": "清空"},
    "terminal.save": {"en": "Save RX", "zh": "保存接收"},
    "terminal.reset_count": {"en": "Reset Count", "zh": "清零计数"},
    "terminal.rx_bytes": {"en": "RX {n} bytes", "zh": "接收 {n} 字节"},
    "terminal.tx_bytes": {"en": "TX {n} bytes", "zh": "发送 {n} 字节"},
    "terminal.prompt": {"en": ">", "zh": ">"},
    "terminal.input_placeholder": {
        "en": "Type here, press Enter to send; ↑ older ↓ newer, Esc clear",
        "zh": "在此输入内容，回车发送；↑ 更旧 ↓ 更新，Esc 清空"},
    "terminal.hex_tx": {"en": "HEX Send", "zh": "HEX 发送"},
    "terminal.escape": {"en": "Escapes", "zh": "转义"},
    "terminal.newline": {"en": "Line End", "zh": "行尾"},
    "terminal.newline.none": {"en": "None", "zh": "无"},
    "terminal.checksum": {"en": "Checksum", "zh": "校验"},
    "terminal.checksum.none": {"en": "None", "zh": "无"},
    "terminal.periodic": {"en": "Periodic", "zh": "周期发送"},
    "terminal.send": {"en": "Send", "zh": "发送"},
    "terminal.send_file": {"en": "Send File", "zh": "发送文件"},
    "terminal.send_not_open": {"en": "Port closed, send ignored", "zh": "串口未打开，发送已忽略"},
    "terminal.send_failed": {"en": "Send failed", "zh": "发送失败"},
    "terminal.sending_file": {"en": "Sending file…", "zh": "文件发送中，请稍候"},
    "terminal.file_done": {"en": "File sent: {n} bytes", "zh": "文件发送完成 {n} 字节"},
    "terminal.file_failed": {"en": "File send failed, stopped", "zh": "文件发送失败，已停止"},
    "terminal.file_aborted": {"en": "File send stopped: {n} bytes", "zh": "文件发送已停止 {n} 字节"},
    "terminal.file_read_failed": {"en": "File read failed, stopped", "zh": "文件读取失败，已停止"},
    "terminal.file_progress": {"en": "Sending {sent}/{total} bytes", "zh": "发送文件中 {sent}/{total} 字节"},
    "terminal.file_select": {"en": "Select file to send", "zh": "选择要发送的文件"},
    "terminal.file_empty": {"en": "Send File", "zh": "发送文件"},
    "terminal.file_error": {"en": "File Error", "zh": "文件错误"},
    "terminal.file_empty_msg": {"en": "The file is empty.", "zh": "文件为空。"},
    "terminal.hex_error_title": {"en": "HEX Error", "zh": "HEX 错误"},
    "terminal.hex_error_msg": {"en": "Invalid hexadecimal string.", "zh": "十六进制字符串无效，请检查。"},
    "terminal.hex_error_item": {"en": "HEX content of item '{name}' is invalid.",
                                "zh": "条目「{name}」的 HEX 内容无效。"},
    "terminal.menu.copy": {"en": "Copy", "zh": "复制"},
    "terminal.menu.select_all": {"en": "Select All", "zh": "全选"},
    "terminal.menu.clear": {"en": "Clear Display", "zh": "清空显示"},

    # 快捷发送
    "quick.new": {"en": "+ New", "zh": "＋ 新建"},
    "quick.dlg_title": {"en": "Quick Send Item", "zh": "快捷发送项"},
    "quick.name": {"en": "Name", "zh": "名称"},
    "quick.name_ph": {"en": "Button label", "zh": "按钮显示名称"},
    "quick.content": {"en": "Content", "zh": "内容"},
    "quick.content_ph": {"en": "Payload; enter HEX if HEX send is checked",
                         "zh": "要发送的内容；勾选 HEX 后请输入十六进制"},
    "quick.as_hex": {"en": "Send as HEX", "zh": "以 HEX 发送"},
    "quick.warn_name": {"en": "Please enter a name.", "zh": "请填写名称。"},
    "quick.warn_hex": {"en": "Invalid HEX content.", "zh": "HEX 内容无效，请检查。"},
    "quick.send": {"en": "Send", "zh": "发送"},
    "quick.edit": {"en": "Edit", "zh": "编辑"},
    "quick.delete": {"en": "Delete", "zh": "删除"},
    "quick.move_up": {"en": "Move Up", "zh": "上移"},
    "quick.move_down": {"en": "Move Down", "zh": "下移"},
    "quick.tip_hex": {"en": "[HEX] ", "zh": "[HEX] "},
    "quick.tip_text": {"en": "[Text] ", "zh": "[文本] "},
    "quick.tip_newline": {"en": "Line end: ", "zh": "行尾: "},

    # 通用
    "common.ok": {"en": "OK", "zh": "确定"},
    "common.cancel": {"en": "Cancel", "zh": "取消"},
    "common.close": {"en": "Close", "zh": "关闭"},
    "common.fullscreen": {"en": "Full Screen", "zh": "全屏显示"},
    "common.exit_fullscreen": {"en": "Exit Full Screen", "zh": "退出全屏"},
    "common.warning": {"en": "Warning", "zh": "提示"},
    "common.open": {"en": "Open", "zh": "打开"},
    "common.open_folder": {"en": "Open Folder", "zh": "打开文件夹"},

    # ＋ / − 数值控件（PlusMinusBox 全局规范）
    "pmb.edit_tip": {"en": "Type a value, or hover and scroll the wheel to adjust",
                     "zh": "直接键入数值，或将鼠标悬停在控件上滚动滚轮微调"},

    # 波形 / 格式
    "wave.fmt_label": {"en": "Data format (printf style)", "zh": "数据格式（printf 风格）"},
    "wave.apply": {"en": "Apply & Replot", "zh": "应用并重绘"},
    "wave.no_channel": {"en": "No numeric channel found (%f/%d/%x …)", "zh": "格式串中未找到数值通道（%f/%d/%x 等）"},
    "wave.chan_count": {"en": "{n} numeric channels detected: {names}", "zh": "已识别 {n} 个数值通道：{names}"},

    # 示波器控件
    "scope.timebase": {"en": "Timebase", "zh": "时基"},
    "scope.timebase_tip": {"en": "Seconds per grid division (timebase)", "zh": "每格时间（时基），横向扫描速度"},
    "scope.coup_tip": {"en": "Coupling: AC removes DC offset, DC passes raw signal", "zh": "耦合方式：AC 隔直（去除直流偏置），DC 直通原始信号"},
    "scope.scale_tip": {"en": "Vertical sensitivity (V/div)", "zh": "垂直灵敏度（伏/格）"},
    "scope.color_tip": {"en": "Channel waveform color", "zh": "通道波形颜色"},
    "scope.run_tip": {"en": "Toggle run / pause acquisition", "zh": "切换运行 / 暂停采集"},
    "scope.single_tip": {"en": "Single-shot: capture one sweep then stop", "zh": "单次采集：采集一屏后自动停止"},
    "scope.clear_tip": {"en": "Clear all channel waveforms", "zh": "清除所有通道波形"},
    "scope.csv_tip": {"en": "Export visible waveforms to CSV", "zh": "导出可见波形为 CSV"},
    "scope.trig_mode_tip": {"en": "Trigger mode: Auto / Normal / Single", "zh": "触发模式：自动 / 常规 / 单次"},
    "scope.trig_type_tip": {"en": "Trigger type: edge / pulse width / timeout", "zh": "触发类型：边沿 / 脉宽 / 超时"},
    "scope.trig_src_tip": {"en": "Trigger source channel", "zh": "触发源通道"},
    "scope.trig_edge_tip": {"en": "Trigger edge: rising / falling / both", "zh": "触发沿：上升 / 下降 / 双沿"},
    "scope.pw_cond_tip": {"en": "Pulse width trigger condition", "zh": "脉宽触发条件"},
    "scope.to_state_tip": {"en": "Timeout trigger state", "zh": "超时触发状态"},
    "scope.page_first_tip": {"en": "First channel page", "zh": "第一页通道"},
    "scope.page_prev_tip": {"en": "Previous channel page", "zh": "上一页通道"},
    "scope.page_next_tip": {"en": "Next channel page", "zh": "下一页通道"},
    "scope.page_last_tip": {"en": "Last channel page", "zh": "最后一页通道"},
    "scope.page_spin_tip": {"en": "Jump to channel page", "zh": "跳转到通道页"},
    "scope.meas_ch_tip": {"en": "Channel shown in measurement panel", "zh": "测量面板显示的通道"},
    "scope.display_tip": {"en": "Display mode: lines / dots / fill", "zh": "显示模式：连线 / 点 / 填充"},
    "scope.cursor_mode_tip": {"en": "Cursor mode: off / manual / auto / track", "zh": "光标模式：关闭 / 手动 / 自动 / 跟踪"},
    "scope.cursor_src_tip": {"en": "Cursor measurement source channel", "zh": "光标测量源通道"},
    "scope.trigger": {"en": "Trigger", "zh": "触发"},
    "scope.trig_mode_auto": {"en": "Auto", "zh": "自动"},
    "scope.trig_mode_normal": {"en": "Normal", "zh": "常规"},
    "scope.trig_mode_single": {"en": "Single", "zh": "单次"},
    "scope.trig_edge_rise": {"en": "Rising", "zh": "上升沿"},
    "scope.trig_edge_fall": {"en": "Falling", "zh": "下降沿"},
    "scope.trig_edge_both": {"en": "Both", "zh": "双沿"},
    "scope.level": {"en": "Level", "zh": "电平"},
    "scope.level_tip": {"en": "Trigger level; arrows step by 0.05", "zh": "触发电平；向上/向下箭头以 0.05 步进"},
    "scope.auto": {"en": "AutoSet", "zh": "自动设置"},
    "scope.auto_tip": {"en": "Autoscale timebase, vertical and trigger (Keysight/Tektronix style)",
                       "zh": "自动设置时基/垂直/触发（Keysight/Tektronix 风格）"},
    "scope.limit": {"en": "Data limit", "zh": "数据上限"},
    "scope.limit_tip": {"en": "Max samples per channel (FIFO, oldest data dropped first)",
                        "zh": "每通道最多保存的采样点数（先进先出，最早的数据优先丢弃）"},
    "scope.limit_hint": {"en": "{n} pts/ch", "zh": "{n} 点/通道"},
    "scope.limit_warn_title": {"en": "Memory warning", "zh": "内存警告"},
    "scope.limit_warn": {"en": "Setting {n} pts/channel may use ~{mb} MB RAM with all channels. Continue?", "zh": "设置 {n} 点/通道，全开时约需 {mb} MB 内存。是否继续？"},
    "scope.refresh": {"en": "Refresh", "zh": "刷新率"},
    "scope.refresh_tip": {"en": "Waveform refresh rate (Hz). Higher = smoother but more CPU. Default 20Hz.", "zh": "波形刷新频率（Hz）。越高越流畅但CPU占用越高。默认20Hz。"},
    "scope.run": {"en": "Run", "zh": "运行"},
    "scope.pause": {"en": "Pause", "zh": "暂停"},
    "scope.single": {"en": "Single", "zh": "单次采集"},
    "scope.clear_plot": {"en": "Clear", "zh": "清屏"},
    "scope.export": {"en": "Export CSV", "zh": "导出 CSV"},
    "scope.knob_timebase": {"en": "Timebase", "zh": "时基"},
    "scope.knob_trig": {"en": "Trig Level", "zh": "触发电平"},
    "scope.knob_hpos": {"en": "H Pos", "zh": "水平位置"},
    "scope.knob_help": {"en": "Knob: drag around center (CW increase) / scroll; Shift = fine",
                        "zh": "旋钮：按住绕中心旋转拖动（顺时针增大）/ 滚轮调节；Shift 细调，实时无卡顿"},
    "scope.status_running": {"en": "Running · {n} samples", "zh": "运行中 · 已采样 {n} 点"},
    "scope.status_normal_wait": {"en": "Waiting for trigger…", "zh": "等待触发…"},
    "scope.trig_src_no_data": {"en": "Trigger source has no data", "zh": "触发源无数据"},
    "scope.status_paused": {"en": "Paused", "zh": "已暂停"},
    "scope.status_cleared": {"en": "Cleared, waiting for data…", "zh": "已清屏，等待数据…"},
    "scope.offset_tip": {"en": "Vertical Position (div): moves the waveform up/down on screen. Range ±5 div, resolution 0.01 div, continuous. Auto keeps 0 (waveform shown at real voltage position).", "zh": "垂直位置（div）：上下移动该通道波形在屏幕上的显示位置。范围 ±5 div，分辨率 0.01 div，连续无档位；Auto 保持 0（波形显示在真实电压位置）。"},
    "scope.offset_ac_disabled": {"en": "AC coupling: Vertical Position forced to 0 (signal centered at 0V)", "zh": "AC 耦合：垂直位置强制为 0（信号以 0V 为中心）"},
    "scope.auto_no_channel": {"en": "Auto: no enabled channel", "zh": "Auto：无启用通道"},
    "scope.auto_no_data": {"en": "Auto: no valid data", "zh": "Auto：无有效数据"},
    "scope.status_single_wait": {"en": "Single: waiting for trigger…", "zh": "单次：等待触发…"},
    "scope.status_single_done": {"en": "Single captured (trigger {name})", "zh": "单次已捕获（触发 {name}）"},

    # 通道 / 测量
    "scope.group_ch": {"en": "Channels", "zh": "通道"},
    "scope.col_show": {"en": "Show", "zh": "显示"},
    "scope.col_ch": {"en": "Channel", "zh": "通道"},
    "scope.col_coupling": {"en": "Coupling", "zh": "耦合"},
    "scope.col_gain": {"en": "V/div", "zh": "垂直灵敏度"},
    "scope.col_offset": {"en": "Position", "zh": "垂直位置"},
    "scope.col_unit": {"en": "Unit", "zh": "单位"},
    "scope.col_color": {"en": "Color", "zh": "颜色"},
    "scope.color_title": {"en": "Select Channel Color", "zh": "选择通道颜色"},
    "scope.group_meas": {"en": "Auto Measurements", "zh": "自动测量"},
    "scope.meas_ch": {"en": "Channel", "zh": "通道"},
    "scope.meas_vpp": {"en": "Vpp", "zh": "Vpp"},
    "scope.meas_vmax": {"en": "Vmax", "zh": "Vmax"},
    "scope.meas_vmin": {"en": "Vmin", "zh": "Vmin"},
    "scope.meas_high": {"en": "High", "zh": "高电平"},
    "scope.meas_low": {"en": "Low", "zh": "低电平"},
    "scope.meas_amp": {"en": "Amplitude", "zh": "幅值"},
    "scope.meas_mean": {"en": "Mean", "zh": "均值"},
    "scope.meas_rms": {"en": "RMS", "zh": "RMS"},
    "scope.meas_std": {"en": "Std Dev", "zh": "标准差"},
    "scope.meas_over": {"en": "Overshoot", "zh": "过冲"},
    "scope.meas_pre": {"en": "Preshoot", "zh": "预冲"},
    "scope.meas_freq": {"en": "Frequency", "zh": "频率"},
    "scope.meas_period": {"en": "Period", "zh": "周期"},
    "scope.meas_rise": {"en": "Rise Time", "zh": "上升时间"},
    "scope.meas_fall": {"en": "Fall Time", "zh": "下降时间"},
    "scope.meas_duty": {"en": "Duty Cycle", "zh": "占空比"},
    "scope.meas_width": {"en": "+Width", "zh": "正脉宽"},
    "scope.meas_neg_width": {"en": "-Width", "zh": "负脉宽"},
    "scope.meas_trig": {"en": "Trigger", "zh": "触发"},
    "scope.meas_area": {"en": "Area", "zh": "面积"},
    "scope.meas_slew_rise": {"en": "Rise Slew", "zh": "上升斜率"},
    "scope.meas_slew_fall": {"en": "Fall Slew", "zh": "下降斜率"},
    "scope.meas_cyc_rms": {"en": "Cycle RMS", "zh": "周期RMS"},
    "scope.meas_cyc_mean": {"en": "Cycle Mean", "zh": "周期平均"},
    "scope.cursor_hint": {"en": "Cursors: click & drag a line; orange/green vertical = time Δt & 1/Δt, dashed horizontal = amplitude ΔY",
                          "zh": "光标：点击并拖动线条；橙/绿竖线测时间 Δt 与 1/Δt，虚线横条测幅度 ΔY"},
    "scope.menu.copy": {"en": "Copy Image", "zh": "复制图像"},
    "scope.menu.save_png": {"en": "Save as PNG…", "zh": "保存为 PNG 图片…"},
    "scope.menu.export_csv": {"en": "Export CSV…", "zh": "导出 CSV…"},
    "scope.menu.export_npz": {"en": "Export NPZ…", "zh": "导出 NPZ…"},
    "scope.menu.export_bin": {"en": "Export BIN…", "zh": "导出 BIN…"},
    "scope.menu.auto": {"en": "Auto Scale", "zh": "Auto 自动设置"},
    "scope.menu.clear": {"en": "Clear Plot", "zh": "清屏"},
    "scope.png_title": {"en": "Save Waveform Image", "zh": "保存波形图像"},
    "scope.png_done": {"en": "Image saved to\n{path}", "zh": "图像已保存到\n{path}"},
    "scope.unit_label": {"en": "Unit", "zh": "单位"},
    "scope.unit_ph": {"en": "e.g. mV", "zh": "如 mV"},
    "scope.unit_tip": {"en": "Measurement & Y-axis unit (optional)", "zh": "测量读数与纵轴单位（可留空）"},

    # 触发类型扩展
    "scope.trig_type_edge": {"en": "Edge", "zh": "边沿"},
    "scope.trig_type_pulse": {"en": "Pulse Width", "zh": "脉宽"},
    "scope.trig_type_runt": {"en": "Runt", "zh": "欠幅"},
    "scope.trig_type_timeout": {"en": "Timeout", "zh": "超时"},
    "scope.trig_type_window": {"en": "Window", "zh": "窗口"},
    "scope.trig_type_rt": {"en": "Rise/Fall Time", "zh": "上升/下降时间"},
    "scope.pw_width": {"en": "Width", "zh": "脉宽"},
    "scope.runt_hi_tip": {"en": "Runt high threshold (low threshold = trigger level)",
                          "zh": "欠幅高阈值（低阈值复用触发电平）"},
    "scope.to_state": {"en": "State", "zh": "状态"},
    "scope.to_above": {"en": "Above", "zh": "高于电平"},
    "scope.to_below": {"en": "Below", "zh": "低于电平"},
    "scope.to_time_tip": {"en": "Timeout duration: trigger when the signal holds the state longer than this (seconds)",
                          "zh": "超时时长：信号保持该状态超过此时间即触发（秒）"},
    "scope.win_levels": {"en": "Window", "zh": "窗口"},
    "scope.win_hi_tip": {"en": "Window upper threshold", "zh": "窗口上限电平"},
    "scope.win_lo_tip": {"en": "Window lower threshold", "zh": "窗口下限电平"},
    "scope.rt_time": {"en": "Rise/Fall", "zh": "升降时间"},
    "scope.rt_time_tip": {"en": "Transition time threshold: trigger when edge rise/fall time exceeds this (seconds)",
                          "zh": "转换时间阈值：边沿上升/下降耗时超过此时间即触发（秒）"},

    # 显示模式 / 余辉
    "scope.display": {"en": "Display", "zh": "显示"},
    "scope.display_vector": {"en": "Vectors", "zh": "矢量线"},
    "scope.display_dot": {"en": "Dots", "zh": "点阵"},
    "scope.group_math": {"en": "Math (M1-M4)", "zh": "数学（M1-M4）"},
    "scope.math_ph": {"en": "e.g. ch1+ch2, sin(ch1)*3", "zh": "如 ch1+ch2、sin(ch1)*3"},
    "scope.math_tip": {"en": "Expression using ch1..chN; operators + - * / ^, functions abs/sqrt/log/ln/exp/sin/cos/tan/pow/min/max, logic not/and/or/xor, calculus diff/integ, filters lowpass(signal,cutoff)/highpass(signal,cutoff)/bandpass(signal,center,bandwidth)/bandstop(signal,center,bandwidth) (cutoff 0~1, 1=Nyquist), constants pi/e",
                       "zh": "表达式引用 ch1..chN；支持 + - * / ^、abs/sqrt/log/ln/exp/sin/cos/tan/pow/min/max、逻辑 not/and/or/xor、微积分 diff/integ、滤波 lowpass(信号,截止)/highpass(信号,截止)/bandpass(信号,中心,带宽)/bandstop(信号,中心,带宽)（截止 0~1，1=奈奎斯特）、常量 pi/e"},
    "scope.math_note": {"en": "Enabled math traces are overlaid and selectable as measurement/trigger source.",
                        "zh": "启用的数学波形会叠加显示，并可作为测量/触发源选择。"},
    "scope.cursor_xa": {"en": "X A", "zh": "X A"},
    "scope.cursor_xb": {"en": "X B", "zh": "X B"},
    "scope.cursor_ya": {"en": "Y A", "zh": "Y A"},
    "scope.cursor_yb": {"en": "Y B", "zh": "Y B"},
    "scope.cursor_xa_tip": {"en": "Show/hide time cursor A (vertical, orange)", "zh": "显示/隐藏时间光标 A（竖线，橙色）"},
    "scope.cursor_xb_tip": {"en": "Show/hide time cursor B (vertical, green)", "zh": "显示/隐藏时间光标 B（竖线，绿色）"},
    "scope.cursor_ya_tip": {"en": "Show/hide amplitude cursor A (horizontal, dashed)", "zh": "显示/隐藏幅度光标 A（横线，虚线）"},
    "scope.cursor_yb_tip": {"en": "Show/hide amplitude cursor B (horizontal, dashed)", "zh": "显示/隐藏幅度光标 B（横线，虚线）"},
    "scope.cur_mode": {"en": "Cursor Mode", "zh": "光标模式"},
    "scope.cur_mode_off": {"en": "OFF", "zh": "关闭"},
    "scope.cur_mode_manual": {"en": "Manual", "zh": "手动"},
    "scope.cur_mode_track": {"en": "Track", "zh": "跟踪"},
    "scope.cur_mode_auto": {"en": "Auto", "zh": "自动"},
    "scope.cur_source": {"en": "Source", "zh": "源"},
    "scope.cur_track_scaling": {"en": "Track Scaling", "zh": "缩放跟随"},
    "scope.cur_coupling": {"en": "Coupling", "zh": "联动"},
    "scope.cur_set_wave": {"en": "Set to Wave", "zh": "对齐波形"},
    "scope.cur_set_screen": {"en": "Set to Screen", "zh": "重置屏幕"},
    "scope.cur_track_scaling_tip": {"en": "Keep cursor's relative phase while zooming",
                                    "zh": "缩放时保持光标相对波形的归一化位置"},
    "scope.cur_coupling_tip": {"en": "Move X1/X2 together (ΔX constant); Y1/Y2 together (ΔY constant)",
                               "zh": "移动 X1 时 X2 联动（ΔX 恒定）；移动 Y1 时 Y2 联动（ΔY 恒定）"},
    "scope.cur_set_wave_tip": {"en": "Align X cursors to zero crossings, Y cursors to peaks",
                               "zh": "X 光标对齐过零点，Y 光标对齐峰值"},
    "scope.cur_set_screen_tip": {"en": "Reset X1/Y1 to 1/3 and X2/Y2 to 2/3 of the screen",
                                 "zh": "X1/Y1 重置到屏幕 1/3 处，X2/Y2 重置到 2/3 处"},
    "scope.page_first": {"en": "⏮ First", "zh": "⏮ 首页"},
    "scope.page_prev": {"en": "◀ Prev", "zh": "◀ 上一页"},
    "scope.page_next": {"en": "Next ▶", "zh": "下一页 ▶"},
    "scope.page_last": {"en": "Last ⏭", "zh": "尾页 ⏭"},
    "scope.page_total_ch": {"en": "{n} channels total", "zh": "共 {n} 个通道"},
    "scope.cur_keys_hint": {"en": "Drag line / hover+wheel / ←→↑↓ (Shift=coarse), Tab cycle, Esc clear",
                            "zh": "拖拽 / 悬停+滚轮 / ←→↑↓（Shift=粗调），Tab 循环，Esc 取消"},

    # FFT
    "fft.window": {"en": "Window", "zh": "窗函数"},
    "fft.db": {"en": "dB Magnitude", "zh": "dB 幅度"},
    "fft.cont": {"en": "Continuous", "zh": "连续刷新"},
    "fft.now": {"en": "FFT Now", "zh": "立即 FFT"},
    "fft.window.rect": {"en": "Rect", "zh": "矩形 (Rect)"},
    "fft.window.hann": {"en": "Hann", "zh": "汉宁 (Hann)"},
    "fft.window.hamming": {"en": "Hamming", "zh": "汉明 (Hamming)"},
    "fft.window.blackman": {"en": "Blackman", "zh": "布莱克曼 (Blackman)"},
    "fft.window.flattop": {"en": "Flat Top", "zh": "平顶 (Flat Top)"},
    "fft.mode": {"en": "Display", "zh": "显示"},
    "fft.mode.amp": {"en": "Amplitude", "zh": "幅度"},
    "fft.mode.phase": {"en": "Phase", "zh": "相位"},
    "fft.mode.real": {"en": "Real", "zh": "实部"},
    "fft.mode.imag": {"en": "Imag", "zh": "虚部"},
    "fft.y_phase": {"en": "Phase", "zh": "相位"},
    "fft.no_channel": {"en": "No channel", "zh": "无通道"},
    "fft.insufficient": {"en": "Insufficient data", "zh": "数据不足"},
    "fft.error": {"en": "FFT error", "zh": "FFT 计算错误"},
    "fft.no_peak": {"en": "Peaks: none", "zh": "峰值：无"},
    "fft.peaks": {"en": "Peaks", "zh": "峰值"},
    "fft.x_freq": {"en": "Frequency", "zh": "频率"},
    "fft.y_mag": {"en": "Amplitude", "zh": "幅度"},
    "fft.copy": {"en": "Copy", "zh": "复制"},
    "fft.save_png": {"en": "Save PNG", "zh": "保存 PNG"},
    "fft.png_title": {"en": "Save FFT Image", "zh": "保存 FFT 图像"},
    "fft.rel": {"en": "ADC fs≈{fs} Hz · Nyquist fN=fs/2≈{nyq} Hz · Resolution Δf=fs/N≈{df} Hz",
                "zh": "ADC 采样率 fs≈{fs} Hz · 奈奎斯特 fN=fs/2≈{nyq} Hz · 频率分辨率 Δf=fs/N≈{df} Hz"},
    "fft.rel_none": {"en": "Enter a valid ADC sample rate to compute FFT parameters.",
                     "zh": "请输入有效的 ADC 采样率以计算 FFT 参数。"},
    "fft.adc_fs": {"en": "ADC Sampling Rate", "zh": "ADC 采样率"},
    "fft.adc_fs_tip": {"en": "Enter the ADC sample rate actually used by the device when streaming serial data. FFT frequency axis, Nyquist and resolution are all derived from this value.",
                       "zh": "输入串口接收数据时设备实际使用的 ADC 采样率。FFT 频率轴、奈奎斯特频率与频率分辨率均基于该值解析。"},
    "fft.bad_fs": {"en": "Invalid ADC sample rate", "zh": "ADC 采样率无效"},
    "fft.ch_tip": {"en": "Select the signal channel for spectrum analysis.", "zh": "选择做频谱分析的信号通道。"},
    "fft.window_tip": {"en": "Window function: Rect (narrowest main lobe, high sidelobe) / Hann / Hamming / Blackman / Flat Top (best amplitude accuracy).", "zh": "窗函数：矩形（主瓣最窄但旁瓣高）/ 汉宁 / 汉明 / 布莱克曼 / 平顶（幅值精度最佳）。"},
    "fft.mode_tip": {"en": "What to display on the vertical axis: Amplitude / Phase / Real / Imaginary.", "zh": "纵轴展示内容：幅度 / 相位 / 实部 / 虚部。"},
    "fft.points_tip": {"en": "FFT points (power of 2). More points → higher spectral-line density (zero-padding improves visual resolution) but more CPU.", "zh": "FFT 点数（2 的幂）。点数越多谱线密度越高（零填充提升视觉分辨率），但 CPU 占用越高。"},
    "fft.auto": {"en": "Auto Scale", "zh": "自动调整"},
    "fft.auto_tip": {"en": "One-click rescale: focus X on the detected peaks and scale Y so the spectrum fits the screen best.",
                     "zh": "一键自动调整：X 轴聚焦到检测到的峰，Y 轴按最大峰自适应缩放，使谱形处于最佳观察状态。"},
    "fft.cont_tip": {"en": "Continuous refresh: auto-recompute every 0.5 s while the data version changes. Unchecked = keep the spectrum frozen until you press FFT Now or switch parameters.",
                      "zh": "连续刷新：数据更新时每 0.5s 自动重算。取消勾选后谱形保持静止，直到点击“立即 FFT”或切换参数。"},

    # 分布图（直方图）
    "dist.title": {"en": "Channel Distribution (histogram of each trace)",
                   "zh": "通道分布图（各通道数值直方图）"},
    "dist.x_value": {"en": "Value", "zh": "数值"},
    "dist.y_count": {"en": "Count", "zh": "计数"},
    "dist.no_data": {"en": "No data yet", "zh": "暂无数据"},
    "dist.ac_note": {"en": "AC-coupled traces are centered around zero", "zh": "AC 耦合通道以零为中心"},
    "dist.limit": {"en": "Data limit", "zh": "数据上限"},
    "dist.save_all": {"en": "Save All", "zh": "保存全部"},
    "dist.save_all_tip": {"en": "Export every distribution as PNG into a selected folder",
                          "zh": "将每个分布图导出为 PNG 并保存到选定文件夹"},
    "dist.save_one": {"en": "Save PNG…", "zh": "保存 PNG…"},
    "dist.copy": {"en": "Copy Image", "zh": "复制图像"},
    "dist.export_csv": {"en": "Export Distribution CSV…", "zh": "导出分布图数据 CSV…"},
    "dist.csv_title": {"en": "Export Distribution CSV", "zh": "导出分布图数据 CSV"},
    "dist.csv_done": {"en": "Saved: {path}", "zh": "已导出：{path}"},
    "dist.reset": {"en": "Reset", "zh": "复位"},
    "dist.png_title": {"en": "Save Distribution Image", "zh": "保存分布图"},
    "dist.dir_title": {"en": "Select Folder for All Distributions", "zh": "选择保存全部分布图的文件夹"},
    "dist.all_done": {"en": "Saved {n} distribution image(s) to\n{path}",
                      "zh": "已保存 {n} 张分布图到\n{path}"},
    "dist.stats_mean": {"en": "μ", "zh": "μ"},
    "dist.stats_std": {"en": "σ", "zh": "σ"},
    "dist.stats_n": {"en": "Sample Count", "zh": "样本数"},
    "dist.stats_min": {"en": "min", "zh": "min"},
    "dist.stats_max": {"en": "max", "zh": "max"},
    "dist.stats_skew": {"en": "skew", "zh": "偏度"},
    "dist.stats_kurt": {"en": "kurt", "zh": "峰度"},
    # 分布图统计信息分类
    "dist.cat_central": {"en": "Central Tendency", "zh": "集中趋势"},
    "dist.cat_dispersion": {"en": "Dispersion", "zh": "离散程度"},
    "dist.cat_shape": {"en": "Shape", "zh": "分布形态"},
    "dist.cat_quantile": {"en": "Quantiles", "zh": "分位数与边界"},
    # 集中趋势指标
    "dist.stats_median": {"en": "Median", "zh": "中位数"},
    "dist.stats_mode": {"en": "Mode", "zh": "众数"},
    "dist.stats_trim_mean": {"en": "TrimMean", "zh": "切尾均值"},
    "dist.stats_geo_mean": {"en": "GeoMean", "zh": "几何均值"},
    # 离散程度指标
    "dist.stats_var": {"en": "Var", "zh": "方差"},
    "dist.stats_range": {"en": "Range", "zh": "极差"},
    "dist.stats_iqr": {"en": "IQR", "zh": "IQR"},
    "dist.stats_mad": {"en": "MAD", "zh": "MAD"},
    "dist.stats_cv": {"en": "CV", "zh": "变异系数"},
    "dist.stats_sem": {"en": "SEM", "zh": "均值标准误"},
    # 分位数指标
    "dist.stats_q1": {"en": "Q1", "zh": "Q1"},
    "dist.stats_q3": {"en": "Q3", "zh": "Q3"},
    "dist.stats_3sigma": {"en": "3σ", "zh": "3σ"},

    # 波形窗口轴
    "export.title": {"en": "Export", "zh": "导出"},
    "export.csv_title": {"en": "Export CSV", "zh": "导出 CSV"},
    "export.npz_title": {"en": "Export NPZ", "zh": "导出 NPZ"},
    "export.bin_title": {"en": "Export BIN", "zh": "导出 BIN"},
    "export.no_data": {"en": "No data to export.", "zh": "暂无数据可导出"},
    "export.done": {"en": "Saved to\n{path}", "zh": "已导出到\n{path}"},
    "export.failed": {"en": "Export failed", "zh": "导出失败"},
    "save.title": {"en": "Save", "zh": "保存"},
    "save.rx_title": {"en": "Save received content", "zh": "保存接收内容"},
    "save.done": {"en": "Saved to\n{path}", "zh": "已保存到\n{path}"},
    "save.file_ok": {"en": "Text (*.txt)", "zh": "文本 (*.txt)"},
    "save.csv_ok": {"en": "CSV (*.csv)", "zh": "CSV (*.csv)"},
    "save.npz_ok": {"en": "NumPy (*.npz)", "zh": "NumPy (*.npz)"},
    "save.bin_ok": {"en": "Binary (*.bin)", "zh": "二进制 (*.bin)"},
    "save.png_ok": {"en": "PNG (*.png)", "zh": "PNG (*.png)"},

    # 关于 / 手册
    "about.title": {"en": "About OtherScope", "zh": "关于其他示波器"},
    "about.content": {"en": '<div style=\'font-family:Segoe UI,Microsoft YaHei,sans-serif;line-height:1.6;\'>\n<p style=\'font-size:18px;font-weight:600;margin:0 0 6px 0;\'>OtherScope</p>\n<p style=\'font-size:13px;margin:0 0 2px 0;\'>Version {VERSION} · Initial Release</p>\n<p style=\'font-size:13px;margin:0 0 12px 0;color:#666;\'>Copyright © 2026 WennianYan (严文年)</p>\n<p style=\'font-size:12px;margin:0 0 4px 0;\'>This software is open source, licensed under the Apache License, Version 2.0 (the "License").</p>\n<p style=\'font-size:12px;margin:0 0 4px 0;\'>You may use, modify, and distribute this software in compliance with the License.</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'>You may obtain a copy of the License at:</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'><a href=\'https://github.com/WennianYan/OtherScope/blob/main/LICENSE\'>https://github.com/WennianYan/OtherScope/blob/main/LICENSE</a></p>\n<p style=\'font-size:12px;margin:0 0 10px 0;\'>(or <a href=\'https://gitee.com/WennianYan/other-scope/blob/main/LICENSE\'>https://gitee.com/WennianYan/other-scope/blob/main/LICENSE</a>)</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'>OtherScope is an independent open-source project. It is not affiliated with, endorsed by, or a product of any oscilloscope or test-equipment manufacturer; all other trademarks are the property of their respective owners.<br>This software is provided "AS IS", without any express or implied warranty.</p>\n<p style=\'font-size:12px;margin:0 0 12px 0;\'>See the License for the specific language governing permissions and limitations under the License.</p>\n<p style=\'font-size:12px;font-weight:600;margin:0 0 4px 0;\'>Source code and more information:</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'>- GitHub: <a href=\'https://github.com/WennianYan/OtherScope\'>https://github.com/WennianYan/OtherScope</a></p>\n<p style=\'font-size:12px;margin:0 0 10px 0;\'>- Gitee:&nbsp;&nbsp;<a href=\'https://gitee.com/WennianYan/other-scope\'>https://gitee.com/WennianYan/other-scope</a></p>\n<p style=\'font-size:11px;margin:0;color:#888;\'>The copyright and license terms of third-party open source components included in this software are listed in the relevant files.</p>\n<p style=\'font-size:11px;margin:0;color:#888;\'>Third-party components:</p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- PySide6 ≥ 6.8 (LGPL-3.0, with GPL exception) — <a href=\'https://doc.qt.io/qtforpython/licenses.html\'>https://doc.qt.io/qtforpython/licenses.html</a></p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- pyqtgraph ≥ 0.14.0 (MIT) — <a href=\'https://github.com/pyqtgraph/pyqtgraph\'>https://github.com/pyqtgraph/pyqtgraph</a></p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- pyserial ≥ 3.5 (BSD-3-Clause) — <a href=\'https://github.com/pyserial/pyserial\'>https://github.com/pyserial/pyserial</a></p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- numpy ≥ 1.25 (BSD-3-Clause) — <a href=\'https://numpy.org/\'>https://numpy.org/</a></p>\n</div>', "zh": '<div style=\'font-family:Microsoft YaHei,Segoe UI,sans-serif;line-height:1.6;\'>\n<p style=\'font-size:18px;font-weight:600;margin:0 0 6px 0;\'>其他示波器（OtherScope）</p>\n<p style=\'font-size:13px;margin:0 0 2px 0;\'>版本 {VERSION} · 初始发布</p>\n<p style=\'font-size:13px;margin:0 0 12px 0;color:#666;\'>版权所有 © 2026 严文年（WennianYan）</p>\n<p style=\'font-size:12px;margin:0 0 4px 0;\'>本软件是开源软件，使用 Apache License, Version 2.0（"本许可证"）授权。</p>\n<p style=\'font-size:12px;margin:0 0 4px 0;\'>您可以在遵守本许可证的前提下使用、修改和分发本软件。</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'>您可以在以下地址获取本许可证的副本：</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'><a href=\'https://github.com/WennianYan/OtherScope/blob/main/LICENSE\'>https://github.com/WennianYan/OtherScope/blob/main/LICENSE</a></p>\n<p style=\'font-size:12px;margin:0 0 10px 0;\'>（或 <a href=\'https://gitee.com/WennianYan/other-scope/blob/main/LICENSE\'>https://gitee.com/WennianYan/other-scope/blob/main/LICENSE</a>）</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'>OtherScope 是独立开源项目，与任何示波器 / 测试仪器厂商无关联，亦非其产品；文中出现的其他商标均归其各自所有者所有。<br>本软件基于"现状"提供，无任何明示或暗示的保证。</p>\n<p style=\'font-size:12px;margin:0 0 12px 0;\'>详见本许可证中关于免责和限制责任的条款。</p>\n<p style=\'font-size:12px;font-weight:600;margin:0 0 4px 0;\'>源代码及更多信息：</p>\n<p style=\'font-size:12px;margin:0 0 2px 0;\'>- GitHub: <a href=\'https://github.com/WennianYan/OtherScope\'>https://github.com/WennianYan/OtherScope</a></p>\n<p style=\'font-size:12px;margin:0 0 10px 0;\'>- Gitee:&nbsp;&nbsp;<a href=\'https://gitee.com/WennianYan/other-scope\'>https://gitee.com/WennianYan/other-scope</a></p>\n<p style=\'font-size:11px;margin:0;color:#888;\'>本软件包含的第三方开源组件，其版权和许可条款均已在相关文件中列明。</p>\n<p style=\'font-size:11px;margin:0;color:#888;\'>第三方组件：</p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- PySide6 ≥ 6.8（LGPL-3.0，含 GPL 兼容例外）— <a href=\'https://doc.qt.io/qtforpython/licenses.html\'>https://doc.qt.io/qtforpython/licenses.html</a></p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- pyqtgraph ≥ 0.14.0（MIT）— <a href=\'https://github.com/pyqtgraph/pyqtgraph\'>https://github.com/pyqtgraph/pyqtgraph</a></p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- pyserial ≥ 3.5（BSD-3-Clause）— <a href=\'https://github.com/pyserial/pyserial\'>https://github.com/pyserial/pyserial</a></p><p style=\'font-size:11px;margin:0 0 2px 12px;color:#888;\'>- numpy ≥ 1.25（BSD-3-Clause）— <a href=\'https://numpy.org/\'>https://numpy.org/</a></p>\n</div>'},
    "manual.title": {"en": "OtherScope User Manual", "zh": "其他示波器 使用手册"},
}


def tr(key: str) -> str:
    """按当前语言查询翻译文本；缺失时回退到 key 末段而非显示完整键名。

    Args:
        key: 翻译键（如 "scope.timebase"）。

    Returns:
        当前语言下的译文；无译文时回退英文，再回退 key 末段。
    """
    entry = STRINGS.get(key)
    if entry is None:
        # 翻译缺失时回退到 key 末段（如 "scope.timebase" → "timebase"），
        # 而非显示完整翻译键名，避免用户看到原始 key 字符串。
        return key.rsplit(".", 1)[-1] if "." in key else key
    if _current_lang in entry and entry.get(_current_lang):
        return entry[_current_lang]
    if entry.get(LANG_EN):
        return entry[LANG_EN]
    return key.rsplit(".", 1)[-1] if "." in key else key


def trf(key: str, **kwargs) -> str:
    """按当前语言查询带占位符的翻译文本并格式化（str.format）。

    Args:
        key: 翻译键。
        **kwargs: 格式化占位参数（如 path=...）。

    Returns:
        已替换占位符的译文。
    """
    """带占位符的翻译；对多余/缺失的占位符均安全。"""
    s = tr(key)
    try:
        return s.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return s