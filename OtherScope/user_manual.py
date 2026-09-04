# -*- coding: utf-8 -*-
"""内置使用手册（简体中文 / English）。

以 HTML 形式提供，供「帮助 -> 使用手册」菜单在 QTextBrowser 中展示。
所有内容为本地静态，无外部依赖，与当前版本代码逐控件对应。

内容要求：专业详细、条理清晰，逐窗口、逐控件说明使用方法，不遗漏任何控件。
"""

from __future__ import annotations


def _cmp_table_html(zh: bool) -> str:
    """全球主流串口调试工具功能对比表（基于公开官方文档/手册调研）。"""
    tools = ["SSCOM", "XCOM v2", "Tera Term", "RealTerm", "CoolTerm",
             "HTerm", "WindTerm", "SecureCRT", "Xshell", "PuTTY",
             "Serial Studio", "OtherScope"]
    rows = [
        ("接收/发送同一面板(终端式)", ["△", "△", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "△", "△"]),
        ("即时输入+本地回显(复刻WindTerm)", ["△", "△", "△", "△", "△", "△", "✓", "△", "△", "△", "△"]),
        ("接收 HEX 显示",            ["✓", "✓", "△", "✓", "✓", "✓", "△", "△", "✓", "△", "✓"]),
        ("多色差异化显示(TX/RX/时间戳/ANSI)", ["△", "△", "△", "△", "△", "△", "✓", "△", "△", "△", "△"]),
        ("接收时间戳",               ["✓", "✓", "△", "✓", "✓", "✓", "✓", "✓", "✓", "△", "✓"]),
        ("自动滚动/暂停/换行",        ["✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓"]),
        ("文本/HEX/转义发送",        ["✓", "✓", "△", "△", "✓", "✓", "△", "△", "△", "△", "✓"]),
        ("发送命令行/历史(↑↓)",      ["△", "△", "△", "△", "△", "△", "△", "△", "✓", "△", "△"]),
        ("快捷发送栏",               ["△", "△", "△", "△", "✓", "✓", "△", "△", "✓", "△", "△"]),
        ("周期定时发送",             ["✓", "✓", "✓", "✓", "△", "✓", "△", "△", "△", "△", "△"]),
        ("文件收发",                 ["✓", "△", "✓", "✓", "✓", "✓", "△", "△", "△", "△", "△"]),
        ("校验 XOR8/SUM8/CRC16",     ["△", "✓", "✓", "✓", "△", "△", "△", "△", "△", "△", "△"]),
        ("DTR/RTS 控制线",           ["△", "✓", "✓", "✓", "✓", "△", "△", "✓", "✓", "✓", "△"]),
        ("编码切换(UTF-8/GBK…)",     ["△", "△", "△", "△", "△", "△", "✓", "✓", "✓", "△", "△"]),
        ("日志/会话保存",            ["✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "✓", "△"]),
        ("串口枚举/一键刷新",         ["✓", "✓", "✓", "✓", "✓", "△", "✓", "△", "△", "△", "✓"]),
        ("多会话/分屏",              ["△", "△", "△", "△", "△", "△", "✓", "✓", "✓", "△", "△"]),
        ("实时波形示波器",            ["△", "△", "△", "△", "✓", "△", "△", "△", "△", "△", "✓"]),
        ("按接口速率精确时间轴",      ["△", "△", "△", "△", "△", "△", "△", "△", "△", "△", "△"]),
        ("自动测量(幅值/频率/边沿)",   ["△", "△", "△", "△", "△", "△", "△", "△", "△", "△", "△"]),
        ("边沿触发/光标/单次",        ["△", "△", "△", "△", "△", "△", "△", "△", "△", "△", "△"]),
        ("AC/DC 通道耦合",            ["△", "△", "△", "△", "△", "△", "△", "△", "△", "△", "△"]),
        ("点阵/余辉/分布图直方图",     ["△", "△", "△", "△", "△", "△", "△", "△", "△", "△", "△"]),
        ("FFT 频谱分析",             ["△", "△", "△", "△", "△", "△", "△", "△", "△", "△", "△"]),
        ("中文/英文国际化切换",       ["△", "△", "△", "△", "△", "△", "✓", "△", "△", "△", "△"]),
        ("脚本/自动化",              ["△", "△", "✓", "△", "△", "△", "✓", "✓", "✓", "△", "△"]),
    ]
    mark = {"✓": "✓", "△": "△", "—": "—"}
    head = "".join(f"<th>{t}</th>" for t in tools)
    body = []
    for feat, vals in rows:
        cells = "".join(f"<td>{mark.get(v, v)}</td>" for v in vals)
        cells += "<td>✓</td>"  # OtherScope
        body.append(f"<tr><td>{feat}</td>{cells}</tr>")
    note = (("注：✓ 支持 · △ 部分/间接支持或未明确 · 依据公开官方文档/手册与社区资料综合评估，"
             "最后一列为 OtherScope（本项目）。") if zh else
            ("Note: ✓ supported · △ partial/indirect or not explicitly documented; based on public "
             "docs/manuals and community sources. Last column is OtherScope (this app)."))
    return (f'<table class="cmp"><thead><tr><th>{("功能维度" if zh else "Feature")}</th>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table><p class='note'>{note}</p>")


def manual_html(zh: bool) -> str:
    """生成程序「帮助→使用手册」对话框的完整 HTML 内容。

    Args:
        zh: 为 True 输出中文手册，False 输出英文手册。

    Returns:
        完整 HTML 文档字符串（含内联 CSS），可直接 setHtml 渲染。
    """
    title = "其他示波器 · 使用手册" if zh else "OtherScope User Manual"
    css = (
        "<style>"
        "body{font-family:'Noto Sans CJK SC','Segoe UI',sans-serif;line-height:1.7;color:#e6e9ef;"
        "background:#141821;padding:20px 26px;max-width:1120px;margin:auto;}"
        "h1,h2,h3,h4{color:#00c8ff;}h1{border-bottom:2px solid #2a3140;padding-bottom:8px;}"
        "h2{margin-top:30px;border-left:4px solid #00c8ff;padding-left:10px;}"
        "h3{margin-top:20px;}h4{margin-top:14px;color:#7fd8ff;}"
        "code{background:#222a36;padding:2px 6px;border-radius:4px;"
        "color:#ffd000;font-family:Consolas,Monaco,monospace;}"
        "pre{background:#0e1218;padding:12px;border-radius:6px;overflow:auto;}"
        "table{border-collapse:collapse;font-size:12px;margin:12px 0;}"
        "th,td{border:1px solid #2c3442;padding:5px 7px;text-align:center;vertical-align:top;}"
        "th{background:#1c2330;color:#00c8ff;}td:first-child{text-align:left;font-weight:600;background:#1a2029;}"
        "table.cmp{display:block;overflow-x:auto;white-space:nowrap;}"
        "table.ctl td:first-child{white-space:nowrap;}"
        ".note{color:#9aa4b2;font-size:12px;}"
        ".warn{color:#ffd000;}"
        ".tip{color:#00ff9c;}"
        "ul,ol{margin:6px 0 6px 0;padding-left:22px;}"
        "li{margin:3px 0;}"
        "</style>"
    )

    # ================================================================ 简体中文
    zh_body = f"""
<h1>其他示波器（OtherScope）· 使用手册</h1>
<p>版本 V1.0 · 2026</p>
<p>其他示波器（OtherScope）是一款集 <b>通讯调试终端</b>（串口 / 网口）+ <b>实时波形示波器</b> + <b>FFT 频谱分析</b> + <b>数据分布图统计</b> 于一体的专业桌面工程工具。纯本地运行，无广告，无网络依赖。</p>

<h2>一、核心特色</h2>
<ul>
<li><b>统一通讯终端</b>：串口与网口共用同一套接收/发送/回显框架，两种通讯方式互斥，同一时刻仅能使用一种。通过菜单「设置 → 通讯接口」切换。</li>
<li><b>专业终端交互</b>：接收与发送合并为终端式面板，底部输入行回车即发，↑/↓ 回溯历史命令，Esc 清空输入。支持行号、时间戳、本地回显、ANSI 颜色码解析。</li>
<li><b>回显模型</b>：遵循行业标准（PuTTY / WindTerm）。带回显下位机（如 RT-Thread msh、Linux shell）时关闭本地回显，屏幕完全由设备回显驱动；不带回显设备时开启本地回显，终端自行显示输入字符。</li>
<li><b>实时波形示波器</b>：8 通道物理通道 + 4 通道数学运算通道，标准示波器操作范式：时基（Time/Div）、垂直灵敏度（Volts/Div）、垂直位置（Position）、AC/DC 耦合、边沿触发、自动测量、光标测量。</li>
<li><b>精确时间轴</b>：波形横轴按通讯接口速率精确计算（波特率 × 每字节比特数 × 接收字节偏移），杜绝墙钟抖动。</li>
<li><b>FFT 频谱分析</b>：独立模块，支持五种窗函数、幅度/相位/实部/虚部显示、dB 刻度、峰值列表。</li>
<li><b>数据分布图</b>：各通道数值直方图 + 完整统计学参数（均值/标准差/方差/偏度/峰度/分位数等），支持右键导出 CSV。</li>
<li><b>国际化与主题</b>：简体中文 / English 随时切换，深色/浅色主题可选。</li>
</ul>

<h2>二、安装与运行</h2>
<p>系统要求：Python 3.8+，依赖 PySide6、pyqtgraph、numpy、pyserial。</p>
<h3>方式一：单文件免安装版（推荐，无需 Python）</h3>
<p>提供三个平台的<b>单文件可执行程序</b>（类似 Windows 的 EXE，整个程序只有一个文件，双击即运行）：</p>
<ul>
<li><b>Windows</b>：<code>OtherScope.exe</code>（单个文件，双击直接运行）</li>
<li><b>macOS</b>：<code>OtherScope.app</code>（双击即运行的标准应用）</li>
<li><b>Linux</b>：<code>OtherScope</code>（单个可执行文件，<code>chmod +x OtherScope &amp;&amp; ./OtherScope</code>）</li>
</ul>
<p>单文件运行时自动执行<b>自举环境修复</b>：检测系统缺失的 Qt 运行库（如 Linux 的
libGL / libEGL / libxkbcommon / libxcb-cursor 等），发现缺失时自动下载安装，
安装完成后自动重启程序；所有异常均以弹窗提醒，绝不静默失败。</p>
<p>重新打包方法（需在对应系统上运行构建脚本，产物在 dist 目录）：</p>
<ul>
<li>Windows：双击 <code>build\\build_windows.bat</code>（自动生成 dist\\OtherScope.exe）</li>
<li>macOS：双击 <code>build/build_macos.command</code>（自动生成 dist/OtherScope.app）</li>
<li>Linux：双击或执行 <code>./build/build_linux.sh</code>（自动生成 dist/OtherScope）</li>
</ul>
<h3>方式二：源码运行（自动检测并安装依赖）</h3>
<ul>
<li>Windows：双击 <code>run_windows.bat</code></li>
<li>macOS：双击 <code>run_macos.command</code>（首次需执行 <code>chmod +x run_macos.command</code>）</li>
<li>Linux：执行 <code>./run_linux.sh</code>（首次需执行 <code>chmod +x run_linux.sh</code>）</li>
</ul>
<p>手动启动：</p>
<pre>pip install PySide6 pyqtgraph numpy pyserial
python main.py</pre>
<h3>第三方开源组件</h3>
<p>本软件为 Apache License 2.0 开源项目，包含以下第三方组件，各自按各自许可证授权使用（详见「帮助 → 关于」对话框与对应项目官方许可文件）：</p>
<table class="ctl">
<tr><th>组件</th><th>最低版本</th><th>许可证</th></tr>
<tr><td>PySide6</td><td>≥ 6.8</td><td>LGPL-3.0</td></tr>
<tr><td>pyqtgraph</td><td>≥ 0.14.0</td><td>MIT</td></tr>
<tr><td>pyserial</td><td>≥ 3.5</td><td>BSD-3-Clause</td></tr>
<tr><td>numpy</td><td>≥ 1.25</td><td>BSD-3-Clause</td></tr>
</table>

<h2>三、界面总览</h2>
<p>主界面采用顶部菜单栏 + 中央页签区布局。页签包括：<b>通讯终端</b>、<b>波形示波器</b>、<b>FFT 频谱</b>、<b>数据分布</b>。</p>

<h3>3.1 菜单栏</h3>
<table class="ctl">
<tr><th>菜单</th><th>子项</th><th>功能说明</th></tr>
<tr><td rowspan="4">文件(F)</td><td>保存接收数据</td><td>将通讯终端接收区内容保存为文本文件</td></tr>
<tr><td>发送文件</td><td>选择文件并通过当前通讯接口发送</td></tr>
<tr><td>导出波形 CSV</td><td>将波形示波器当前通道数据导出为 CSV 格式</td></tr>
<tr><td>退出</td><td>关闭程序</td></tr>
<tr><td rowspan="5">视图(V)</td><td>通讯终端</td><td>切换到通讯终端页签</td></tr>
<tr><td>波形示波器</td><td>切换到波形示波器页签</td></tr>
<tr><td>FFT 频谱</td><td>切换到 FFT 频谱页签</td></tr>
<tr><td>数据分布</td><td>切换到数据分布图页签</td></tr>
<tr><td>主题</td><td>深色 / 浅色主题切换</td></tr>
<tr><td rowspan="2">语言(L)</td><td>简体中文</td><td>切换界面语言为简体中文</td></tr>
<tr><td>English</td><td>切换界面语言为英文</td></tr>
<tr><td rowspan="2">设置(S)</td><td>通讯接口 → 串口</td><td>选择串口通讯方式（与网口互斥）</td></tr>
<tr><td>通讯接口 → 网口</td><td>选择网口通讯方式（与串口互斥）</td></tr>
<tr><td rowspan="2">帮助(H)</td><td>使用手册</td><td>打开本使用手册</td></tr>
<tr><td>关于</td><td>显示软件名称、版本、作者、邮箱、日期信息</td></tr>
</table>
<p class="tip">导出/保存完成对话框：所有导出、保存操作（保存接收数据、导出波形、保存 PNG、分布图导出等）完成后，都会弹出成功提示对话框，提供三个按钮：<b>「打开」</b>——用系统默认程序直接打开目标文件；<b>「打开文件夹」</b>——在文件管理器中定位并选中目标文件（若目标是目录则直接打开目录）；<b>「确定」</b>——关闭对话框。</p>

<h2>四、通讯终端窗口</h2>
<p>通讯终端是串口与网口共用的统一交互界面。两种通讯方式通过菜单「设置 → 通讯接口」切换，互斥运行。</p>

<h3>4.1 通讯方式与设置面板</h3>
<p>设置面板位于接收区上方，分为「通讯方式」（菜单控制，界面不显示控件）和对应通讯参数设置。</p>

<h4>4.1.1 串口设置</h4>
<p>当菜单选择「串口」时显示串口设置面板，分为两行：</p>
<p>第一行：</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>串口</td><td>下拉列表</td><td>选择可用串口号（如 COM3、/dev/ttyUSB0）。下拉末尾的「虚拟串口 (Demo，无需硬件)」无需硬件即可演示正弦波数据流（采样率 400 帧/秒）。点击「刷新」重新枚举系统串口。</td></tr>
<tr><td>刷新</td><td>按钮</td><td>重新扫描系统可用串口，更新下拉列表。</td></tr>
<tr><td>波特率</td><td>下拉列表</td><td>选择通讯波特率（300 ~ 921600，含常用标准值）。</td></tr>
<tr><td>数据位</td><td>下拉列表</td><td>数据位数：5 / 6 / 7 / 8（默认 8）。</td></tr>
<tr><td>停止位</td><td>下拉列表</td><td>停止位数：1 / 1.5 / 2（默认 1）。</td></tr>
<tr><td>校验</td><td>下拉列表</td><td>校验方式：None（无）/ Even（偶）/ Odd（奇）/ Mark（标记）/ Space（空格）。</td></tr>
</table>
<p>第二行：</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>流控</td><td>下拉列表</td><td>流控方式：None（无）/ RTS/CTS（硬件）/ XON/XOFF（软件）。</td></tr>
<tr><td>编码</td><td>下拉列表</td><td>接收/发送字符编码：utf-8 / GBK / ASCII / ISO-8859-1（latin-1）。</td></tr>
<tr><td>控制线 DTR</td><td>复选框</td><td>设置 DTR（数据终端就绪）控制线电平。勾选=高电平，取消=低电平。</td></tr>
<tr><td>控制线 RTS</td><td>复选框</td><td>设置 RTS（请求发送）控制线电平。勾选=高电平，取消=低电平。串口打开按钮位于此控件之后。</td></tr>
<tr><td>打开/关闭</td><td>按钮</td><td>打开或关闭当前串口。打开后按钮变为「关闭」，参数控件锁定。</td></tr>
</table>

<h4>4.1.2 网口设置</h4>
<p>当菜单选择「网口」时显示网口设置面板，所有控件置于一行：</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>协议</td><td>下拉列表</td><td>网口协议：TCP 客户端 / TCP 服务器 / UDP。</td></tr>
<tr><td>主机/远程 IP</td><td>输入框</td><td>目标设备 IP 地址（TCP 客户端 / UDP 模式）。</td></tr>
<tr><td>远程端口</td><td>输入框</td><td>目标设备端口号（TCP 客户端 / UDP 模式）。</td></tr>
<tr><td>本地 IP</td><td>输入框</td><td>本地绑定 IP 地址（TCP 服务器 / UDP 模式，默认 0.0.0.0，TCP 服务器模式下可填写本机网卡 IP）。</td></tr>
<tr><td>本地端口</td><td>输入框</td><td>本地监听端口号（TCP 服务器 / UDP 模式）。</td></tr>
<tr><td>连接/关闭</td><td>按钮</td><td>建立或断开网口连接，位于网口设置控件行的最后。</td></tr>
</table>

<h3>4.2 接收显示区</h3>
<p>接收显示区是通讯终端的核心区域，显示从通讯接口接收到的所有数据。</p>

<h4>4.2.1 接收工具栏</h4>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>HEX 显示</td><td>复选框</td><td>勾选后接收数据以十六进制转储格式显示（含地址偏移、ASCII 列）。取消后以文本格式显示。</td></tr>
<tr><td>HEX 列宽</td><td>下拉列表</td><td>HEX 显示时每行字节数：8 / 16 / 24 / 32（默认 16）。</td></tr>
<tr><td>时间戳</td><td>复选框</td><td>勾选后每行接收数据前附加时间戳（格式：HH:MM:SS.mmm）。</td></tr>
<tr><td>时间戳格式</td><td>下拉列表</td><td>时间戳精度选择：秒 / 毫秒（默认 秒）。</td></tr>
<tr><td>行号</td><td>复选框</td><td>勾选后每行接收数据前附加递增行号。</td></tr>
<tr><td>自动滚动</td><td>复选框</td><td>勾选后接收新数据时自动滚动到底部。取消后保持当前查看位置。</td></tr>
<tr><td>自动换行</td><td>复选框</td><td>勾选后超长行自动换行显示。取消后水平滚动查看。下位机带回显（如 msh 提示符）时建议取消，避免提示符后意外换行。</td></tr>
<tr><td>回车行尾</td><td>下拉列表</td><td>按下回车发送当前输入行时自动附加的行尾字符：无 / \n（LF）/ \r（CR）/ \r\n（CRLF）。与发送选项条的「行尾」下拉双向同步。</td></tr>
<tr><td>暂停</td><td>复选框</td><td>勾选后暂停接收显示（数据仍在后台接收，仅暂停屏幕刷新）。取消后恢复。</td></tr>
<tr><td>清屏</td><td>按钮</td><td>清空接收显示区内容。</td></tr>
<tr><td>接收缓存行数</td><td>数值输入</td><td>接收区最大保留量，支持「行数」与「容量」两种模式（1000 / 5000 / 10000 / 50000 / 100000 行，或 1 / 10 / 100 MB、1 / 5 / 10 GB，全局上限 10 GB），超出后最旧数据自动移除（FIFO）。默认 10000 行。</td></tr>
<tr><td>本地回显</td><td>复选框</td><td>串口与网口共用。勾选后终端自行显示发送的字符（适用于不带回显的下位机）。取消后不显示发送字符（适用于带回显的下位机，如 RT-Thread msh、Linux shell，屏幕完全由设备回显驱动）。</td></tr>
<tr><td>保存接收</td><td>按钮</td><td>将当前接收显示区内容保存为文本文件，完成后弹出「打开 / 打开文件夹 / 确定」对话框。</td></tr>
<tr><td>接收计数</td><td>标签</td><td>实时显示本次接收的累计字节数（含已暂停/清屏前的累计），清零前持续累加。</td></tr>
<tr><td>清零计数</td><td>按钮</td><td>将接收字节计数归零，重新开始统计。</td></tr>
</table>

<h4>4.2.2 接收区交互</h4>
<ul>
<li><b>即时输入</b>：点击接收区即可直接键入字符，按键始终发送到通讯接口。输入行为与系统文本编辑器一致：可显示字符直接插入，退格键删除前一字符，Delete 删除后一字符，左右方向键移动光标。</li>
<li><b>回车发送</b>：按下回车键发送当前输入行内容（含回车符）。</li>
<li><b>历史回溯</b>：↑/↓ 方向键回溯之前发送过的命令。</li>
<li><b>清空输入</b>：Esc 键清空当前输入行。</li>
<li><b>选中复制</b>：鼠标拖拽选中接收区文本，Ctrl+C 复制。</li>
</ul>

<h3>4.3 发送区</h3>
<h4>4.3.1 发送选项</h4>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>HEX 发送</td><td>复选框</td><td>勾选后输入内容按十六进制字节发送（如 "41 42 43"，每字节以空格分隔）。取消后按所选编码发送文本字符串。</td></tr>
<tr><td>转义处理</td><td>复选框</td><td>勾选后解释转义序列（\r 回车、\n 换行、\t 制表、\\ 反斜杠等）。未勾选时按字面字符发送。</td></tr>
<tr><td>回车行尾</td><td>下拉列表</td><td>发送时自动附加的行尾字符：无 / \n（LF）/ \r（CR）/ \r\n（CRLF）。默认跟随操作系统：Windows 默认 \r\n，Linux/macOS 默认 \n。</td></tr>
<tr><td>校验</td><td>下拉列表</td><td>发送数据附加校验值：无 / XOR8 / SUM8 / SUM16 / LRC / CRC8-MAXIM / CRC8-ATM / CRC16-Modbus / CRC16-CCITT / CRC16-XMODEM / CRC16-IBM / CRC16-USB / CRC16-DNP / CRC32 / CRC32-MPEG2 / Adler32 / Fletcher-16 / Fletcher-32 / Parity-Even / Parity-Odd。</td></tr>
<tr><td>周期发送</td><td>复选框+输入</td><td>勾选后按设定周期（毫秒）自动重复发送当前内容。</td></tr>
<tr><td>发送</td><td>按钮</td><td>立即发送输入框内容。</td></tr>
</table>

<h4>4.3.2 快捷发送栏</h4>
<p>快捷发送栏提供多个预设命令按钮，点击即发送对应内容。每个按钮可自定义标题和发送内容，支持右键编辑。适用于频繁发送的固定指令。</p>
<h4>4.3.3 发送面板布局</h4>
<p>接收显示区与发送面板之间有一条<b>可拖拽的分隔条</b>：向上拖动分隔条可增大发送面板、缩小接收区，向下拖动则反之。二者高度<b>严格等量联动</b>（接收区减小多少、发送面板就增大多少，总高度恒定），发送面板锚定窗口底部，顶边随分隔条上下移动。</p>
<p>发送面板由三段组成：<b>发送选项条</b>（固定高度，不随面板伸缩）→ <b>输入行</b>（可伸缩，吸收面板全部高度变化；内容较多时自动出现滚动条）→ <b>快捷发送栏</b>（固定高度）。面板内部始终紧凑，无多余空白。</p>
<p>发送状态提示（如“串口未打开，发送已忽略”“发送失败”“发送中 n/m”）显示在<b>发送选项条最右侧</b>，以高亮黄色加粗显示；输入行左侧无多余符号。</p>

<h2>五、波形示波器窗口</h2>
<p>波形示波器将通讯接口接收的数值数据实时绘制成波形，支持 8 个物理通道（ch1~ch8）+ 4 个数学通道（M1~M4）。操作范式对标专业台式示波器（Tektronix / Keysight / RIGOL）。</p>

<h3>5.1 数据格式行</h3>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>数据格式（printf 风格）</td><td>输入框</td><td>定义如何从接收数据流中解析各通道数值。使用 printf 格式符，如 <code>ch1:%fmv,ch2:%fmv</code> 表示解析 ch1 和 ch2 的浮点值（单位 mV）。支持 %f（浮点）、%d（整数）、%x（十六进制）等格式。通道名与单位自动解析。</td></tr>
<tr><td>自动识别</td><td>按钮</td><td>分析当前通讯接口最近收到的数据行，自动推断其中的 printf 风格格式串，并写入左侧格式输入框。仅写入格式框、不自动应用；点击右侧「应用并重绘」后按新格式重新解析并绘制波形。适用于数据格式未知、需快速确认解析方案的情形。</td></tr>
<tr><td>应用并重绘</td><td>按钮</td><td>应用数据格式设置并重新解析已有数据、重绘波形。</td></tr>
<tr><td>已识别通道</td><td>标签</td><td>显示当前数据格式中识别到的通道列表（如 "已识别 8 个数值通道：ch1, ch2, ..., ch8"）。</td></tr>
</table>

<h3>5.2 顶部控制条</h3>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>时基</td><td>下拉列表</td><td>水平时间刻度（Time/Div），标准 1-2-5 序列：1 µs/div ~ 1000 s/div。调节 X 轴每格代表的时间值。</td></tr>
<tr><td>AutoSet</td><td>按钮</td><td>自动设置（Auto Setup）：一次按键自动配置时基、垂直灵敏度、触发电平与触发源。垂直方向：启用通道≥2 且均有数据时按<b>通道分离排列</b>（Keysight Autoscale 风格）——通道按编号从上到下各占一段屏幕、波形互不重叠，每通道 V/div 独立设置为波动占其区域 70%（区域内最大化、不削顶），垂直位置（Position）设为区域中心并补偿直流偏置；单通道时按叠加（Overlay）模式——波形幅度最大化至约 70% 屏高（6~7 格），0V 参考地线默认居中；仅当直流偏置导致波形溢出屏幕（峰值&gt;屏顶−0.5 格或谷值&lt;屏底+0.5 格）时才引入垂直偏移（Position）将波形拉回，且偏移限制在 ±3 格——波形中点始终保持在屏幕中部区域，既不会贴顶也不会贴底；偏置过大时自动增大 V/div 使波形收缩回中部并保证不削顶（No Clipping）。触发源仅从物理通道（ch1~ch8）中自动选择电压最高通道（幅值相近时优先编号较小通道）；已启用数学通道（M1~M4）参与各通道垂直档位最大化，但不作为触发源。触发电平设为信号中位（50%），时基使屏幕稳定显示 2~5 个完整周期（最接近 3 个）。AutoSet 不改变任何通道的 DC/AC 耦合设置。</td></tr>
<tr><td>数据上限</td><td>下拉列表</td><td>每通道最大缓存数据点数（如 80 M 点/通道）。超出后最旧数据自动移除（FIFO）。</td></tr>
<tr><td>刷新率</td><td>数值输入</td><td>波形屏幕刷新频率（Hz），默认 20 Hz。</td></tr>
<tr><td>触发模式</td><td>下拉列表</td><td>自动 / 正常 / 单次。自动：无触发时自动滚动，有触发时稳定显示；正常：仅在触发条件满足时更新波形；单次：捕获一次触发后停止。</td></tr>
<tr><td>触发类型</td><td>下拉列表</td><td>边沿 / 脉宽 / 欠幅 / 超时 / 窗口 / 上升下降时间。默认边沿触发。</td></tr>
<tr><td>触发源</td><td>下拉列表</td><td>选择触发信号来源通道（ch1~ch8 或数学通道 M1~M4）。</td></tr>
<tr><td>边沿方向</td><td>下拉列表</td><td>上升沿 / 下降沿 / 任意沿。</td></tr>
<tr><td>触发电平</td><td>数值输入</td><td>触发阈值电压值。</td></tr>
<tr><td>运行/暂停</td><td>按钮</td><td>运行时实时更新波形；暂停时冻结当前显示（数据仍在后台接收）。</td></tr>
<tr><td>单次采集</td><td>按钮</td><td>执行一次单次触发采集，捕获后自动停止。</td></tr>
<tr><td>清屏</td><td>按钮</td><td>清空所有通道波形数据。</td></tr>
<tr><td>导出 CSV</td><td>按钮</td><td>将当前波形数据导出为 CSV 文件。</td></tr>
</table>
<p><b>波形数据导出（多格式）</b>：除顶部「导出 CSV」按钮外，波形显示区<b>右键菜单</b>还提供「复制图像 / 存 PNG / 导出 CSV / 导出 NPZ / 导出 BIN / Auto / 清屏」。所有导出均包含<b>已打开的全部通道</b>（物理通道 + 已启用数学通道）的耦合数据（DC 原样 / AC 去直流）：
<ul>
<li><b>CSV</b>：每通道 <code>通道名_t</code>（时间）与 <code>通道名_y</code>（数值）两列，UTF-8 编码。</li>
<li><b>NPZ</b>：NumPy 压缩格式，每通道两个数组 <code>&lt;名&gt;_t</code> / <code>&lt;名&gt;_y</code>，便于 Python 科学计算复现。</li>
<li><b>BIN</b>：float32 小端二进制，逐通道以 <code>[N][x0,y0,x1,y1,…]</code> 交错写入。</li>
<li><b>PNG</b>：当前波形图直接保存为图片。</li>
</ul>
完成后弹出「打开 / 打开文件夹 / 确定」对话框。</p>

<h3>5.3 旋钮区</h3>
<p>三个虚拟旋钮对应示波器的三个核心物理旋钮：</p>
<table class="ctl">
<tr><th>旋钮</th><th>英文</th><th>功能说明</th></tr>
<tr><td>时基</td><td>Timebase</td><td>水平时间刻度（Time/Div）。按住中心旋转拖动增大/减小，滚轮细调。</td></tr>
<tr><td>触发电平</td><td>Trigger Level</td><td>触发阈值电压。调节触发点在垂直方向的位置。</td></tr>
<tr><td>水平位置</td><td>Horizontal Position</td><td>触发点在屏幕水平方向的位置。水平位置=0 时触发点位于屏幕正中央；正值触发点右移（观察触发前波形），负值左移（观察触发后波形）。单位为时间（s/ms/µs）。</td></tr>
</table>
<p class="tip">旋钮操作：按住中心旋转拖动（顺时针增大）/ 滚轮细调，实时无卡顿。</p>

<h3>5.4 通道面板</h3>
<p>通道面板位于波形显示区左侧，管理所有通道的显示与参数。通道数 ≤5 时全部显示，无分页控件；通道数 >5 时分页显示，每页 5 个通道。</p>

<h4>5.4.1 通道设置行</h4>
<p>每个通道一行，包含以下控件（表头与通道行严格对齐）：</p>
<table class="ctl">
<tr><th>列</th><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>显示</td><td>通道开关</td><td>复选框</td><td>勾选显示该通道波形，取消隐藏。仅控制显示，不影响数据接收与缓存。</td></tr>
<tr><td>通道</td><td>通道名</td><td>标签</td><td>通道标识符（ch1~ch8 或 M1~M4），颜色与波形颜色一致。</td></tr>
<tr><td>耦合</td><td>耦合方式</td><td>下拉列表</td><td>DC / AC。DC：直接显示原始数据；AC：去除直流分量（原始值 − 最近 10000 点滑窗均值，等效隔直耦合电容只保留交流成分），以 0V 为中心显示交流部分。AC 耦合时垂直位置强制为 0。物理通道与数学通道（M1~M4）使用<b>同一</b>滑窗均值 AC 算法，任意「源通道耦合 × 数学通道耦合」组合下波形均一致（如 ch1=DC、M1=AC 与 ch1=AC、M1=AC 等价）。</td></tr>
<tr><td>垂直灵敏度</td><td>Volts/Div / Scale</td><td>可编辑下拉</td><td>Y 轴每格代表的电压值。标准 1-2-5 序列：1 mV/div ~ 10 V/div（探头 1X、输入阻抗 1MΩ 时粗调档位）。可手动输入任意值。调节后波形围绕垂直位置基准点缩放。</td></tr>
<tr><td>垂直位置</td><td>Position</td><td>数值输入</td><td>波形在屏幕垂直方向的位置，单位为格（div）。范围 ±5 div，分辨率 0.01 div，默认 0。连续可调，无固定档位。正值波形上移，负值下移。也可在波形显示区鼠标拖动通道标签（➡ch1）或悬停滚轮调节，实时同步到此输入框。</td></tr>
<tr><td>单位</td><td>单位</td><td>可编辑下拉</td><td>通道数值单位（V / mV / µV / nV / kV / MV 等），默认 V。是所有单位换算的唯一来源。从数据格式串自动解析，也可手动选择或输入。</td></tr>
<tr><td>颜色</td><td>颜色块</td><td>颜色选择</td><td>该通道波形颜色。整格铺满颜色并居中显示。双击颜色块弹出调色板换色。</td></tr>
</table>

<h4>5.4.2 分页控件（通道数 >5 时显示）</h4>
<table class="ctl">
<tr><th>控件</th><th>功能说明</th></tr>
<tr><td>⏮ 首页</td><td>跳转到第 1 页。第 1 页时禁用。</td></tr>
<tr><td>◀ 上一页</td><td>逐页上翻。第 1 页时禁用。</td></tr>
<tr><td>页码</td><td>手动输入目标页码（1-based），范围 1~总页数。</td></tr>
<tr><td>/ 总页数</td><td>显示总页数。</td></tr>
<tr><td>共 N 个通道</td><td>显示通道总数（物理通道 + 已启用数学通道）。</td></tr>
<tr><td>下一页 ▶</td><td>逐页下翻。最后一页时禁用。</td></tr>
<tr><td>尾页 ⏭</td><td>跳转到最后一页。最后一页时禁用。</td></tr>
</table>

<h3>5.5 自动测量面板</h3>
<p>自动测量面板实时计算并显示所选通道的 24 项波形参数，所有结果带单位：</p>
<table class="ctl">
<tr><th>测量项</th><th>英文</th><th>说明</th></tr>
<tr><td>Vpp</td><td>Peak-to-Peak</td><td>峰峰值 = Vmax - Vmin</td></tr>
<tr><td>Vmax</td><td>Maximum</td><td>最大值</td></tr>
<tr><td>Vmin</td><td>Minimum</td><td>最小值</td></tr>
<tr><td>高电平</td><td>High Level</td><td>逻辑高电平值（基于直方图双峰分析）</td></tr>
<tr><td>低电平</td><td>Low Level</td><td>逻辑低电平值</td></tr>
<tr><td>幅值</td><td>Amplitude</td><td>幅值 = 高电平 - 低电平</td></tr>
<tr><td>RMS</td><td>Root Mean Square</td><td>均方根值（全程）</td></tr>
<tr><td>均值</td><td>Mean</td><td>算术平均值（全程）</td></tr>
<tr><td>标准差</td><td>Std Dev</td><td>标准偏差</td></tr>
<tr><td>过冲</td><td>Overshoot</td><td>上升沿过冲百分比</td></tr>
<tr><td>预冲</td><td>Preshoot</td><td>上升沿预冲百分比</td></tr>
<tr><td>频率</td><td>Frequency</td><td>信号频率</td></tr>
<tr><td>周期</td><td>Period</td><td>信号周期</td></tr>
<tr><td>下降时间</td><td>Fall Time</td><td>从 90% 到 10% 的下降时间</td></tr>
<tr><td>上升时间</td><td>Rise Time</td><td>从 10% 到 90% 的上升时间</td></tr>
<tr><td>占空比</td><td>Duty Cycle</td><td>正脉宽占周期百分比</td></tr>
<tr><td>正脉宽</td><td>Positive Width</td><td>正脉冲宽度</td></tr>
<tr><td>负脉宽</td><td>Negative Width</td><td>负脉冲宽度</td></tr>
<tr><td>触发</td><td>Trigger</td><td>触发电平值</td></tr>
<tr><td>面积</td><td>Area</td><td>波形积分面积</td></tr>
<tr><td>上升斜率</td><td>Rise Slew</td><td>上升沿最大斜率</td></tr>
<tr><td>下降斜率</td><td>Fall Slew</td><td>下降沿最大斜率</td></tr>
<tr><td>周期 RMS</td><td>Cycle RMS</td><td>单周期均方根值</td></tr>
<tr><td>周期均值</td><td>Cycle Mean</td><td>单周期平均值</td></tr>
</table>
<p>通道选择：下拉选择测量目标通道。单位：显示当前通道单位。</p>

<h3>5.6 数学运算面板（M1~M4）</h3>
<p>数学通道基于物理通道数据进行自定义表达式运算，结果作为独立通道显示、测量和触发。</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>M1~M4 启用</td><td>复选框</td><td>勾选启用对应数学通道，启用后自动添加到通道面板（显示开关/耦合/垂直灵敏度/垂直位置/单位/颜色），控制逻辑与物理通道完全一致。取消后从通道面板移除。</td></tr>
<tr><td>表达式</td><td>输入框</td><td>数学运算表达式。支持：通道引用（ch1~ch8）、算术运算（+ - * / ^ 幂）、一元负号、常量（pi/e）、函数（abs/sqrt/log/lg/log10/ln/loge/exp/sin/cos/tan/not/diff/integ/integral/pow/min/max/and/or/xor/lowpass/highpass/bandpass/bandstop）。示例：<code>ch1+ch2</code>、<code>sin(ch1)*3</code>、<code>ch1*ch2+1</code>、<code>lowpass(ch1,0.1)</code>。</td></tr>
<tr><td>颜色块</td><td>颜色选择</td><td>数学通道波形颜色。</td></tr>
</table>
<p class="tip">单位自动换算：如 ch1 单位为 V，ch2 单位为 mV，表达式 <code>ch1+ch2</code> 自动换算为 ch1 + ch2×0.001（统一为 V）。数学通道数据源为原始数据经表达式运算的结果，垂直灵敏度/垂直位置只影响屏幕显示，不影响测量值。</p>
<p class="tip">默认单位自动跟随：数学通道默认单位自动等于其表达式中<strong>第一个出现的物理通道</strong>的单位——如 M1=ch1 跟随 ch1；M1=ch2+1 跟随 ch2；M1=ch3+ch1 跟随 ch3。手动修改某数学通道的单位后，该通道停止自动跟随（保持手动设置）。</p>
<p class="tip">AC/DC 耦合：数学通道与物理通道共用同一滑窗均值 AC 算法。数学通道对表达式中各源通道的<strong>耦合数据</strong>（源通道 DC 时即原始数据，AC 时已去直流）做表达式运算，再按本通道自身耦合处理结果（DC 原样 / AC 去直流）。因此 M1=ch1 时：ch1=DC、M1=AC 与 ch1 设 AC 的波形完全一致；ch1=AC、M1=DC 亦与 ch1=AC 一致；ch1=AC、M1=AC 是对已去直流信号再次去直流，残差极小（视觉不可辨）。在线逐点与全量重放严格一致，无初值暂态。</p>

<h3>5.7 波形显示区</h3>
<p>波形显示区是示波器的核心输出区域，采用标准示波器栅格（Graticule）：</p>
<ul>
<li><b>栅格结构</b>：水平 10 大格，垂直 10 大格。中心十字为实线（屏幕正中央），其余大格线为离散点显示。</li>
<li><b>大格交叉点</b>：11×11 个较亮的点（size=5），标记大格线交叉位置。</li>
<li><b>小格点</b>：仅在大格经纬线上，每大格之间 9 个小点（size=2，较暗），将每大格分为 10 小格。大格内部无小点。</li>
<li><b>Y 轴范围</b>：中心为垂直位置 0，向上 5 格，向下 5 格。正极值 = 垂直灵敏度 × 5，负极值 = −垂直灵敏度 × 5。</li>
<li><b>X 轴范围</b>：水平方向 10 格，中心对应水平位置 0（触发点位于屏幕正中央）。右侧极值 = 时基 × 5，左侧极值 = −时基 × 5。</li>
<li><b>栅格静态</b>：背景栅格在整个软件运行周期保持静态显示，不随鼠标滚轮移动或缩放，不随数据滚动。仅波形数据点移动。</li>
</ul>

<h4>5.7.1 屏幕标记元素</h4>
<table class="ctl">
<tr><th>元素</th><th>专业术语</th><th>说明</th></tr>
<tr><td>⬇ 触发点</td><td>Horizontal Time Reference / Trigger Point</td><td>位于波形显示区最顶部，⬇ 顶部与显示区顶部重合。标记时间零点（t=0）位置，即触发事件发生时刻。水平位置调节时触发点左右移动。</td></tr>
<tr><td>➡ch1~➡ch8</td><td>Channel Identifier / Channel Label</td><td>位于波形显示区最左侧，➡ 左侧与显示区左侧重合。颜色与波形颜色一致，标记该通道的 0V 垂直参考基准位置。垂直位置调节时基准点上下移动，波形围绕该点缩放。可鼠标拖动或悬停滚轮调节垂直位置。</td></tr>
<tr><td>中心十字</td><td>Center Crosshair</td><td>屏幕正中央的水平+垂直实线，唯一实线栅格元素。</td></tr>
</table>

<h4>5.7.2 波形显示选项</h4>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>显示模式</td><td>下拉列表</td><td>矢量线（Vector，点之间连线）/ 点阵（Dots，仅显示采样点）。</td></tr>
<tr><td>余辉</td><td>下拉列表</td><td>关闭 / 可变 / 无限。余辉模式保留历史波形轨迹，便于观察偶发信号。</td></tr>
</table>

<h3>5.8 光标测量面板</h3>
<p>光标测量提供精确的波形参数读数，支持 X/Y 双组光标。</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>光标模式</td><td>下拉列表</td><td>关闭 / 手动 / 跟踪 / 自动。关闭：不显示光标；手动：用户自由拖动光标位置；跟踪：光标自动吸附波形——鼠标在波形区移动时 X 光标锁定到鼠标位置最近的波形采样点、Y 光标跟随该点电压，调整垂直灵敏度/垂直位置（或缩放）后光标自动重新吸附波形不脱靶；自动：自动测量并显示读数。</td></tr>
<tr><td>XA / XB</td><td>按钮</td><td>选择/显示水平光标 A / B 的时间位置。</td></tr>
<tr><td>YA / YB</td><td>按钮</td><td>选择/显示垂直光标 A / B 的电压位置。</td></tr>
<tr><td>源</td><td>下拉列表</td><td>光标跟踪的目标通道。</td></tr>
<tr><td>缩放跟随</td><td>复选框</td><td>勾选后光标按数据锚定（Track Scaling）：缩放/平移（时基、水平位置、垂直灵敏度变化）时光标相对波形的相位位置保持不变（X 光标保持绝对时间、Y 光标保持物理值）；不勾选时光标按屏幕锚定，缩放/平移时线固定在屏幕位置不动。</td></tr>
<tr><td>联动</td><td>复选框</td><td>勾选时 XA/XB 或 YA/YB 联动移动（保持间距不变）。</td></tr>
<tr><td>对齐波形</td><td>按钮</td><td>将光标自动对齐到波形特征点（边沿/峰值）。</td></tr>
<tr><td>重置屏幕</td><td>按钮</td><td>重置光标位置到默认值，恢复波形显示区布局。</td></tr>
</table>
<p><b>光标读数</b>：底部状态栏实时显示光标测量结果：橙/绿竖线测时间 Δt 与 1/Δt，虚线横条测幅度 ΔV。</p>
<p class="tip">光标操作：点击并拖动线条移动；悬停滚轮微调；Shift+拖动粗调；Tab 循环切换光标；Esc 取消当前操作。</p>

<h2>六、FFT 频谱窗口</h2>
<p>FFT 频谱分析模块独立运行，对所选通道数据执行快速傅里叶变换，显示频域特性。</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>通道</td><td>下拉列表</td><td>选择 FFT 分析的目标通道。</td></tr>
<tr><td>FFT 模式</td><td>下拉列表</td><td>幅度（Amplitude）/ 相位（Phase）/ 实部（Real）/ 虚部（Imag）。</td></tr>
<tr><td>窗函数</td><td>下拉列表</td><td>矩形（Rectangular）/ 汉宁（Hann）/ 汉明（Hamming）/ 布莱克曼（Blackman）/ 平顶（Flattop）。窗函数减少频谱泄漏，不同窗函数适用于不同测量场景。</td></tr>
<tr><td>采样率</td><td>数值输入</td><td>ADC 采样率（Hz），用于计算频率轴、奈奎斯特频率和频率分辨率。</td></tr>
<tr><td>FFT 点数</td><td>下拉列表</td><td>FFT 计算点数（如 1024 / 2048 / 4096 / 8192）。点数越多频率分辨率越高。</td></tr>
<tr><td>dB 显示</td><td>复选框</td><td>勾选后幅度以对数 dB 刻度显示。</td></tr>
<tr><td>峰值列表</td><td>面板</td><td>自动识别并列出频谱峰值的频率和幅度。</td></tr>
<tr><td>保存 PNG</td><td>按钮</td><td>将当前 FFT 频谱图保存为 PNG 图片，完成后弹出「打开 / 打开文件夹 / 确定」对话框。</td></tr>
</table>

<h2>七、数据分布图窗口</h2>
<p>数据分布图显示各通道数值的统计分布直方图和完整统计学参数。</p>
<table class="ctl">
<tr><th>控件</th><th>类型</th><th>功能说明</th></tr>
<tr><td>通道选择</td><td>标签页/下拉</td><td>选择查看分布的通道，各通道独立显示。</td></tr>
<tr><td>分箱数</td><td>数值输入</td><td>直方图分箱数量（bin count）。</td></tr>
<tr><td>点数</td><td>标签</td><td>当前参与统计的样本点数。</td></tr>
<tr><td>重置</td><td>按钮</td><td>清空统计数据重新开始。</td></tr>
<tr><td>高斯拟合</td><td>曲线</td><td>在直方图上叠加正态分布拟合曲线。</td></tr>
<tr><td>3σ 标识线</td><td>红色虚线</td><td>标记均值 ±3σ 范围，顶部标注数值，动态跟随数据更新。</td></tr>
</table>
<p><b>统计学参数</b>：均值、中位数、众数、方差、标准差、IQR（四分位距）、MAD（平均绝对偏差）、偏度、峰度、最小值、最大值、各分位数（P1/P5/P25/P50/P75/P95/P99）等。</p>
<p class="tip"><b>右键菜单</b>：在分布图上鼠标右键可选择：<b>复位</b>（清空本通道统计重新累积）、<b>存 PNG</b>（本通道分布图保存为图片，含统计读数）、<b>导出 CSV</b>（直方图 bin 中心值+计数，UTF-8 BOM 便于 Excel 直接打开）、<b>复制图像</b>（分布图复制到剪贴板）。保存与导出完成后同样弹出「打开 / 打开文件夹 / 确定」对话框。</p>

<h2>八、全球主流调试工具功能对比</h2>
{_cmp_table_html(True)}

<h2>九、使用技巧与常见问题</h2>
<h3>9.1 使用技巧</h3>
<ul>
<li><b>带回显下位机</b>（如 RT-Thread msh、Linux shell）：关闭「本地回显」，屏幕完全由设备回显驱动，输入紧跟设备提示符（如 <code>msh &gt;help</code>）。这是 PuTTY / WindTerm 的默认行为（Local Echo = Off）。</li>
<li><b>不带回显下位机</b>：开启「本地回显」，终端自行显示发送字符，否则用户看不见输入内容（Local Echo = On）。</li>
<li><b>本地回显 + 设备回显同时开启</b>会导致每个字符显示两次（本地回显一次 + 设备回显一次），这是正常现象，应根据下位机类型选择合适的回显模式。</li>
<li><b>AutoSet 自动设置</b>：连接信号后点击 AutoSet，程序自动检测各启用通道信号：仅从物理通道（ch1~ch8）自动选择电压最高通道（幅值相近时优先编号较小通道）为触发源并设为 50% 中位触发电平（已启用数学通道 M1~M4 参与各通道垂直档位最大化，但不作为触发源）；调整时基使屏幕显示 2~5 个完整周期（最接近 3 个）；垂直档位：启用通道≥2 且均有数据时自动<b>通道分离排列</b>——通道按编号从上到下各占一段屏幕、互不重叠，每通道 V/div 独立最大化至波动占其区域 70%（不削顶），垂直位置设为区域中心并补偿直流偏置；单通道时叠加居中（波形占约 70% 屏高、0V 地线居中），直流偏置导致波形溢出屏幕时自动引入垂直偏移拉回（偏移限制在 ±3 格），偏置过大时自动增大 V/div 收缩回中部并保证不削顶。AutoSet 不改变任何通道的 DC/AC 耦合。</li>
<li><b>通道标签拖动</b>：在波形显示区左侧拖动 ➡chN 标签可快速调节该通道的垂直位置，悬停滚轮也可微调，数值实时同步到通道面板。</li>
<li><b>数学通道单位换算</b>：表达式中不同单位的通道自动换算为统一单位（如 V + mV 自动换算），无需手动换算。</li>
<li><b>分页浏览通道</b>：通道数超过 5 个时使用分页控件（首页/上一页/页码/下一页/尾页）浏览，每页显示 5 个通道。</li>
<li><b>控件悬停帮助</b>：将鼠标悬停在任意控件上会显示该控件的功能说明（tooltip）；波形页全部控件均已覆盖。串口/终端页部分控件（端口、波特率、发送按钮等）悬停 3 秒还会弹出更详细的使用说明与最终视觉效果悬浮框。</li>
</ul>

<h3>9.2 常见问题 FAQ</h3>
<ul>
<li><b>Q：波形不显示？</b><br>A：检查①数据格式是否正确解析通道（查看「已识别通道」标签）；②通道显示开关是否勾选；③通讯接口是否已打开并接收数据；④垂直灵敏度是否过大（波形缩成一条线）。</li>
<li><b>Q：串口找不到？</b><br>A：点击「刷新」重新枚举；检查 USB 转串口驱动是否安装；检查设备管理器（Windows）或 /dev（Linux/macOS）确认串口号。</li>
<li><b>Q：网口连接失败？</b><br>A：检查①协议选择是否正确（TCP 客户端/服务器/UDP）；②IP 地址和端口号是否正确；③防火墙是否阻止；④TCP 服务器模式下本地 IP 和端口是否可绑定。</li>
<li><b>Q：输入字符显示两次？</b><br>A：这是因为「本地回显」开启且下位机也带回显。关闭「本地回显」即可（带回显设备应关闭本地回显）。</li>
<li><b>Q：触发电平如何设置？</b><br>A：通过顶部「触发电平」数值输入或旋钮区「触发电平」旋钮调节，电平值应在信号高低电平之间才能稳定触发。</li>
<li><b>Q：如何导出波形数据？</b><br>A：菜单「文件 → 导出波形 CSV」或波形页「导出 CSV」按钮，将当前所有通道数据导出为 CSV 文件。</li>
</ul>

<h3>9.3 快捷键一览</h3>
<h4>通讯终端（输入区获得焦点时）</h4>
<table class="ctl">
<tr><th>按键</th><th>功能</th></tr>
<tr><td>Enter</td><td>发送当前输入行</td></tr>
<tr><td>Shift+Enter</td><td>输入框内换行（多行输入）</td></tr>
<tr><td>↑ / ↓</td><td>浏览发送历史（更旧 / 更新）</td></tr>
<tr><td>Ctrl+↑ / Ctrl+↓</td><td>浏览发送历史</td></tr>
<tr><td>Esc</td><td>清空输入行</td></tr>
<tr><td>Ctrl+C</td><td>有选中文本时复制；无选中时发送 Ctrl-C（0x03 中断字符）</td></tr>
<tr><td>Ctrl+V</td><td>粘贴剪贴板文本</td></tr>
<tr><td>Ctrl+A</td><td>全选输入内容</td></tr>
<tr><td>Tab</td><td>发送制表符（显示为可见缩进）</td></tr>
<tr><td>方向键 / Home / End / PgUp / PgDn / Insert / Delete / F1~F12</td><td>发送标准终端控制序列（本地不渲染控制标记）</td></tr>
</table>
<h4>波形窗口（光标测量开启时）</h4>
<table class="ctl">
<tr><th>按键</th><th>功能</th></tr>
<tr><td>Tab</td><td>循环切换活动光标（X1 / X2 / Y1 / Y2）</td></tr>
<tr><td>方向键</td><td>微调活动光标位置</td></tr>
<tr><td>Shift+方向键</td><td>粗调活动光标位置</td></tr>
<tr><td>Esc</td><td>退出光标编辑状态</td></tr>
<tr><td>➡chN 标签拖拽</td><td>快速调节该通道垂直位置；悬停滚轮微调</td></tr>
<tr><td>波形区滚轮</td><td>水平缩放时基（悬停时微调）</td></tr>
</table>
"""

    # ================================================================ English
    en_body = f"""
<h1>OtherScope · User Manual</h1>
<p>Version V1.0 · 2026</p>
<p>OtherScope is a professional desktop engineering tool integrating a <b>communication debug terminal</b> (Serial / Ethernet) + <b>real-time waveform oscilloscope</b> + <b>FFT spectrum analysis</b> + <b>data distribution statistics</b>. Runs entirely locally, ad-free, no network dependency.</p>

<h2>1. Highlights</h2>
<ul>
<li><b>Unified Communication Terminal</b>: Serial and Ethernet share the same RX/TX/echo framework. The two modes are mutually exclusive — only one can be active at a time. Switch via menu "Settings → Communication Interface".</li>
<li><b>Professional Terminal Interaction</b>: RX and TX merged into a terminal-style panel. Press Enter in the bottom input line to send; ↑/↓ recalls command history; Esc clears input. Supports line numbers, timestamps, local echo, and ANSI color code parsing.</li>
<li><b>Echo Model</b>: Follows industry standards (PuTTY / WindTerm). For echo-capable devices (e.g., RT-Thread msh, Linux shell), disable local echo — the screen is driven entirely by device echo. For non-echo devices, enable local echo — the terminal displays typed characters itself.</li>
<li><b>Real-Time Waveform Oscilloscope</b>: 8 physical channels (ch1~ch8) + 4 math channels (M1~M4). Standard oscilloscope paradigm: Timebase (Time/Div), Vertical Sensitivity (Volts/Div), Vertical Position (Position), AC/DC coupling, edge trigger, automatic measurements, cursor measurements.</li>
<li><b>Precise Time Axis</b>: Waveform horizontal axis calculated from interface baud rate (baud × bits-per-byte × byte offset), eliminating wall-clock jitter.</li>
<li><b>FFT Spectrum Analysis</b>: Independent module with five window functions, amplitude/phase/real/imaginary display, dB scale, and peak list.</li>
<li><b>Data Distribution</b>: Per-channel value histogram + complete statistical parameters (mean/std/variance/skewness/kurtosis/quantiles), with right-click CSV export.</li>
<li><b>Internationalization & Themes</b>: Simplified Chinese / English switchable anytime; dark/light themes available.</li>
</ul>

<h2>2. Installation & Run</h2>
<p><b>Requirements</b>: Python 3.8+, dependencies: PySide6, pyqtgraph, numpy, pyserial.</p>
<p><b>Recommended launch</b> (auto-detects and installs dependencies):</p>
<ul>
<li>Windows: double-click <code>run_windows.bat</code></li>
<li>macOS: double-click <code>run_macos.command</code> (first run: <code>chmod +x run_macos.command</code>)</li>
<li>Linux: run <code>./run_linux.sh</code> (first run: <code>chmod +x run_linux.sh</code>)</li>
</ul>
<p><b>Manual launch</b>:</p>
<pre>pip install PySide6 pyqtgraph numpy pyserial
python main.py</pre>
<h3>Third-Party Open-Source Components</h3>
<p>This software is an Apache License 2.0 open-source project. It includes the following third-party components, each licensed under its own license (see the "Help → About" dialog and the respective project's official license files):</p>
<table class="ctl">
<tr><th>Component</th><th>Minimum Version</th><th>License</th></tr>
<tr><td>PySide6</td><td>≥ 6.8</td><td>LGPL-3.0</td></tr>
<tr><td>pyqtgraph</td><td>≥ 0.14.0</td><td>MIT</td></tr>
<tr><td>pyserial</td><td>≥ 3.5</td><td>BSD-3-Clause</td></tr>
<tr><td>numpy</td><td>≥ 1.25</td><td>BSD-3-Clause</td></tr>
</table>

<h2>3. Interface Overview</h2>
<p>The main interface uses a top menu bar + central tab area layout. Tabs: <b>Communication Terminal</b>, <b>Waveform Oscilloscope</b>, <b>FFT Spectrum</b>, <b>Data Distribution</b>.</p>

<h3>3.1 Menu Bar</h3>
<table class="ctl">
<tr><th>Menu</th><th>Sub-item</th><th>Description</th></tr>
<tr><td rowspan="4">File(F)</td><td>Save RX Data</td><td>Save terminal receive area content to a text file</td></tr>
<tr><td>Send File</td><td>Select a file and send via the active communication interface</td></tr>
<tr><td>Export Waveform CSV</td><td>Export current oscilloscope channel data to CSV format</td></tr>
<tr><td>Exit</td><td>Close the application</td></tr>
<tr><td rowspan="5">View(V)</td><td>Communication Terminal</td><td>Switch to terminal tab</td></tr>
<tr><td>Waveform Oscilloscope</td><td>Switch to oscilloscope tab</td></tr>
<tr><td>FFT Spectrum</td><td>Switch to FFT tab</td></tr>
<tr><td>Data Distribution</td><td>Switch to distribution tab</td></tr>
<tr><td>Theme</td><td>Dark / Light theme toggle</td></tr>
<tr><td rowspan="2">Language(L)</td><td>简体中文</td><td>Switch UI to Simplified Chinese</td></tr>
<tr><td>English</td><td>Switch UI to English</td></tr>
<tr><td rowspan="2">Settings(S)</td><td>Comm Interface → Serial</td><td>Select serial communication (mutually exclusive with Ethernet)</td></tr>
<tr><td>Comm Interface → Ethernet</td><td>Select Ethernet communication (mutually exclusive with serial)</td></tr>
<tr><td rowspan="2">Help(H)</td><td>User Manual</td><td>Open this user manual</td></tr>
<tr><td>About</td><td>Show software name, version, author, email, date</td></tr>
</table>
<p class="tip"><b>Save/Export Completion Dialog</b>: Every export/save operation (save received data, export waveform, save PNG, distribution export, etc.) shows a success dialog with three buttons: <b>Open</b> — open the target file with the system default program; <b>Open Folder</b> — reveal/select the target file in the file manager (or open the directory if the target is a folder); <b>OK</b> — close the dialog.</p>

<h2>4. Communication Terminal</h2>
<p>The communication terminal is a unified interface shared by serial and Ethernet. Switch via menu "Settings → Communication Interface"; the two modes are mutually exclusive.</p>

<h3>4.1 Communication Mode & Settings Panel</h3>

<h4>4.1.1 Serial Settings</h4>
<p>When "Serial" is selected in the menu, the serial settings panel appears in two rows:</p>
<p>Row 1:</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Port</td><td>Dropdown</td><td>Select available serial port (e.g., COM3, /dev/ttyUSB0). The "Virtual Port (Demo, no hardware)" at the bottom of the list streams a sine-wave demo without hardware (400 frames/s). Click "Refresh" to re-enumerate.</td></tr>
<tr><td>Refresh</td><td>Button</td><td>Re-scan system serial ports and update the dropdown list.</td></tr>
<tr><td>Baud Rate</td><td>Dropdown</td><td>Communication baud rate (300 ~ 921600, standard values).</td></tr>
<tr><td>Data Bits</td><td>Dropdown</td><td>Data bits: 5 / 6 / 7 / 8 (default 8).</td></tr>
<tr><td>Stop Bits</td><td>Dropdown</td><td>Stop bits: 1 / 1.5 / 2 (default 1).</td></tr>
<tr><td>Parity</td><td>Dropdown</td><td>Parity: None / Even / Odd / Mark / Space.</td></tr>
</table>
<p>Row 2:</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Flow Control</td><td>Dropdown</td><td>Flow control: None / RTS/CTS (hardware) / XON/XOFF (software).</td></tr>
<tr><td>Encoding</td><td>Dropdown</td><td>RX/TX character encoding: utf-8 / GBK / ASCII / ISO-8859-1 (latin-1).</td></tr>
<tr><td>Control Line DTR</td><td>Checkbox</td><td>Set DTR (Data Terminal Ready) line level. Checked=high, unchecked=low.</td></tr>
<tr><td>Control Line RTS</td><td>Checkbox</td><td>Set RTS (Request To Send) line level. Checked=high, unchecked=low. The serial Open button is placed after this control.</td></tr>
<tr><td>Open/Close</td><td>Button</td><td>Open or close the current serial port. When open, the button changes to "Close" and parameter controls are locked.</td></tr>
</table>

<h4>4.1.2 Ethernet Settings</h4>
<p>When "Ethernet" is selected, the Ethernet settings panel appears with all controls in one row:</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Protocol</td><td>Dropdown</td><td>Ethernet protocol: TCP Client / TCP Server / UDP.</td></tr>
<tr><td>Host / Remote IP</td><td>Input</td><td>Target device IP address (TCP Client / UDP mode).</td></tr>
<tr><td>Remote Port</td><td>Input</td><td>Target device port number (TCP Client / UDP mode).</td></tr>
<tr><td>Local IP</td><td>Input</td><td>Local binding IP address (TCP Server / UDP mode, default 0.0.0.0; fill in a local NIC IP in TCP Server mode).</td></tr>
<tr><td>Local Port</td><td>Input</td><td>Local listening port number (TCP Server / UDP mode).</td></tr>
<tr><td>Connect/Close</td><td>Button</td><td>Establish or close Ethernet connection, placed at the end of the Ethernet settings row.</td></tr>
</table>

<h3>4.2 Receive Display Area</h3>

<h4>4.2.1 Receive Toolbar</h4>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>HEX Display</td><td>Checkbox</td><td>When checked, received data is shown in hex dump format (with address offset and ASCII column). Unchecked for text format.</td></tr>
<tr><td>HEX Column Width</td><td>Dropdown</td><td>Bytes per row in HEX display: 8 / 16 / 24 / 32 (default 16).</td></tr>
<tr><td>Timestamp</td><td>Checkbox</td><td>When checked, each received line is prefixed with a timestamp (format: HH:MM:SS.mmm).</td></tr>
<tr><td>Timestamp Format</td><td>Dropdown</td><td>Timestamp precision: seconds / milliseconds (default seconds).</td></tr>
<tr><td>Line Number</td><td>Checkbox</td><td>When checked, each received line is prefixed with an incrementing line number.</td></tr>
<tr><td>Auto Scroll</td><td>Checkbox</td><td>When checked, the display auto-scrolls to the bottom on new data. Unchecked to hold current view position.</td></tr>
<tr><td>Auto Wrap</td><td>Checkbox</td><td>When checked, long lines wrap automatically. Unchecked for horizontal scrolling. For echo-capable devices (e.g., msh prompt), it is recommended to disable to avoid unexpected line breaks after the prompt.</td></tr>
<tr><td>Enter Line Ending</td><td>Dropdown</td><td>Line ending automatically appended when pressing Enter to send the current input line: None / \n (LF) / \r (CR) / \r\n (CRLF). Two-way synced with the "Line Ending" dropdown in the send options.</td></tr>
<tr><td>Pause</td><td>Checkbox</td><td>When checked, pauses display refresh (data continues to be received in background). Uncheck to resume.</td></tr>
<tr><td>Clear Screen</td><td>Button</td><td>Clear the receive display area.</td></tr>
<tr><td>RX Buffer Lines</td><td>Number input</td><td>Maximum retention for the receive area, in two modes — "lines" (1000/5000/10000/50000/100000) or "capacity" (1/10/100 MB, 1/5/10 GB; global cap 10 GB); oldest data is removed when exceeded (FIFO). Default 10000 lines.</td></tr>
<tr><td>Local Echo</td><td>Checkbox</td><td>Shared by serial and Ethernet. When checked, the terminal displays sent characters itself (for non-echo devices). When unchecked, sent characters are not displayed (for echo-capable devices like RT-Thread msh, Linux shell — the screen is driven entirely by device echo).</td></tr>
<tr><td>Save Received</td><td>Button</td><td>Save the current receive area content to a text file; after completion, a dialog with "Open / Open Folder / OK" appears.</td></tr>
<tr><td>RX Count</td><td>Label</td><td>Live cumulative byte count received this session (keeps accumulating across pause/clear until reset).</td></tr>
<tr><td>Reset Count</td><td>Button</td><td>Reset the receive byte count to zero and start over.</td></tr>
</table>

<h4>4.2.2 Receive Area Interaction</h4>
<ul>
<li><b>Instant Input</b>: Click the receive area to type directly; keystrokes are always sent to the communication interface. Input behavior matches the system text editor: printable characters insert directly, Backspace deletes the previous character, Delete deletes the next character, left/right arrows move the cursor.</li>
<li><b>Enter to Send</b>: Press Enter to send the current input line content (including the line ending character).</li>
<li><b>History Recall</b>: ↑/↓ arrow keys recall previously sent commands.</li>
<li><b>Clear Input</b>: Esc key clears the current input line.</li>
<li><b>Select & Copy</b>: Mouse drag to select text in the receive area, Ctrl+C to copy.</li>
</ul>

<h3>4.3 Send Area</h3>
<h4>4.3.1 Send Options</h4>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>HEX Send</td><td>Checkbox</td><td>When checked, the input content is sent as hexadecimal bytes (e.g., "41 42 43", space-separated). Unchecked, the text string is sent using the selected encoding.</td></tr>
<tr><td>Escape Processing</td><td>Checkbox</td><td>When checked, escape sequences are interpreted (\r CR, \n LF, \t TAB, \\ backslash, etc.). When unchecked, characters are sent literally.</td></tr>
<tr><td>Line Ending</td><td>Dropdown</td><td>Auto-appended line ending when sending: None / \\n (LF) / \\r (CR) / \\r\\n (CRLF). Default follows OS: Windows \\r\\n, Linux/macOS \\n.</td></tr>
<tr><td>Checksum</td><td>Dropdown</td><td>Append checksum to sent data: None / XOR8 / SUM8 / SUM16 / LRC / CRC8-MAXIM / CRC8-ATM / CRC16-Modbus / CRC16-CCITT / CRC16-XMODEM / CRC16-IBM / CRC16-USB / CRC16-DNP / CRC32 / CRC32-MPEG2 / Adler32 / Fletcher-16 / Fletcher-32 / Parity-Even / Parity-Odd.</td></tr>
<tr><td>Periodic Send</td><td>Checkbox+Input</td><td>When checked, automatically repeats sending current content at the set interval (milliseconds).</td></tr>
<tr><td>Send</td><td>Button</td><td>Immediately send the input box content.</td></tr>
</table>

<h4>4.3.2 Quick Send Bar</h4>
<p>The quick send bar provides multiple preset command buttons; clicking sends the corresponding content. Each button can have a custom title and send content (right-click to edit). Suitable for frequently sent fixed commands.</p>
<h4>4.3.3 Send Panel Layout</h4>
<p>A <b>draggable splitter</b> separates the receive area from the send panel: dragging it upward enlarges the send panel while shrinking the receive area, and vice versa. The two heights change in strict proportion (each pixel the receive area shrinks is gained by the send panel; total height stays constant). The send panel is anchored to the bottom of the window, and its top edge moves with the splitter.</p>
<p>The send panel consists of three sections: the <b>send option bar</b> (fixed height), the <b>input line</b> (stretchable, absorbing all panel height changes; a scrollbar appears when the content is long), and the <b>quick send bar</b> (fixed height). The panel stays compact with no blank gaps.</p>
<p>Send status hints (e.g., "Port closed, send ignored", "Send failed", "Sending n/m") are shown at the <b>far right of the send option bar</b> in highlighted yellow bold text; there is no extra prompt symbol to the left of the input line.</p>

<h2>5. Waveform Oscilloscope</h2>
<p>The waveform oscilloscope plots numeric data received from the communication interface in real time, supporting 8 physical channels (ch1~ch8) + 4 math channels (M1~M4). The operation paradigm follows professional bench oscilloscopes (Tektronix / Keysight / RIGOL).</p>

<h3>5.1 Data Format Row</h3>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Data Format (printf-style)</td><td>Input</td><td>Defines how to parse channel values from the received data stream. Uses printf format specifiers, e.g., <code>ch1:%fmv,ch2:%fmv</code> parses ch1 and ch2 float values (unit mV). Supports %f (float), %d (integer), %x (hex), etc. Channel names and units are auto-parsed.</td></tr>
<tr><td>Auto Recognize</td><td>Button</td><td>Analyzes the most recent data lines received from the communication interface, infers the printf-style format string, and writes it into the format input box on the left. It only fills the format box without auto-applying — click "Apply & Redraw" on the right to re-parse and redraw with the new format. Useful when the data format is unknown and you need a quick parsing scheme.</td></tr>
<tr><td>Apply & Redraw</td><td>Button</td><td>Apply the data format setting, re-parse existing data, and redraw waveforms.</td></tr>
<tr><td>Recognized Channels</td><td>Label</td><td>Shows the list of channels recognized in the current data format (e.g., "8 numeric channels recognized: ch1, ch2, ..., ch8").</td></tr>
</table>

<h3>5.2 Top Control Bar</h3>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Timebase</td><td>Dropdown</td><td>Horizontal time scale (Time/Div), standard 1-2-5 sequence: 1 µs/div ~ 1000 s/div. Adjusts the time value per horizontal division.</td></tr>
<tr><td>AutoSet</td><td>Button</td><td>Auto setup: one-click auto-configures timebase, vertical sensitivity, trigger level and trigger source. Vertical: Overlay mode — each channel independently maximizes waveform amplitude to ~70% of screen height (6–7 divisions), 0 V ground level centered by default; only when DC offset pushes the waveform off-screen (peak &gt; top−0.5 div or trough &lt; bottom+0.5 div) is a vertical offset (Position) applied to pull it back (no clipping). Trigger source: highest-voltage channel (lowest-numbered channel when amplitudes are comparable); trigger level set to signal median (50%); timebase shows ~3 complete cycles. Auto never changes any channel's DC/AC coupling.</td></tr>
<tr><td>Data Limit</td><td>Dropdown</td><td>Maximum cached data points per channel (e.g., 80 M points/channel). Oldest data is removed when exceeded (FIFO).</td></tr>
<tr><td>Refresh Rate</td><td>Number input</td><td>Waveform screen refresh rate (Hz), default 20 Hz.</td></tr>
<tr><td>Trigger Mode</td><td>Dropdown</td><td>Auto / Normal / Single. Auto: auto-scrolls when no trigger, stable display when triggered; Normal: updates waveform only when trigger condition is met; Single: captures one trigger then stops.</td></tr>
<tr><td>Trigger Type</td><td>Dropdown</td><td>Edge / Pulse Width / Runt / Timeout / Window / Rise-Fall Time. Default edge trigger.</td></tr>
<tr><td>Trigger Source</td><td>Dropdown</td><td>Select trigger signal source channel (ch1~ch8 or math channels M1~M4).</td></tr>
<tr><td>Edge Direction</td><td>Dropdown</td><td>Rising / Falling / Either edge.</td></tr>
<tr><td>Trigger Level</td><td>Number input</td><td>Trigger threshold voltage value.</td></tr>
<tr><td>Run/Pause</td><td>Button</td><td>Run: updates waveform in real time; Pause: freezes current display (data continues receiving in background).</td></tr>
<tr><td>Single</td><td>Button</td><td>Perform a single trigger acquisition; stops automatically after capture.</td></tr>
<tr><td>Clear</td><td>Button</td><td>Clear all channel waveform data.</td></tr>
<tr><td>Export CSV</td><td>Button</td><td>Export current waveform data to a CSV file.</td></tr>
</table>
<p><b>Waveform Export (multiple formats)</b>: Besides the top "Export CSV" button, the waveform plot <b>right-click menu</b> offers "Copy Image / Save PNG / Export CSV / Export NPZ / Export BIN / Auto / Clear". All exports include <b>all open channels</b> (physical + enabled math channels) with coupled data (DC raw / AC DC-removed):
<ul>
<li><b>CSV</b>: two columns per channel, <code>name_t</code> (time) and <code>name_y</code> (value), UTF-8 encoded.</li>
<li><b>NPZ</b>: NumPy compressed format, two arrays per channel <code>&lt;name&gt;_t</code> / <code>&lt;name&gt;_y</code>, ideal for Python scientific reproduction.</li>
<li><b>BIN</b>: float32 little-endian binary, interleaved per channel as <code>[N][x0,y0,x1,y1,…]</code>.</li>
<li><b>PNG</b>: the current waveform plot saved directly as an image.</li>
</ul>
On completion, an "Open / Open Folder / OK" dialog is shown.</p>

<h3>5.3 Knob Zone</h3>
<p>Three virtual knobs correspond to the three core physical knobs of an oscilloscope:</p>
<table class="ctl">
<tr><th>Knob</th><th>English</th><th>Description</th></tr>
<tr><td>Timebase</td><td>Timebase</td><td>Horizontal time scale (Time/Div). Hold center and rotate-drag to increase/decrease, scroll wheel for fine adjustment.</td></tr>
<tr><td>Trigger Level</td><td>Trigger Level</td><td>Trigger threshold voltage. Adjusts the vertical position of the trigger point.</td></tr>
<tr><td>Horizontal Position</td><td>Horizontal Position</td><td>Horizontal position of the trigger point on screen. When =0, the trigger point is at screen center; positive values shift the trigger point right (view pre-trigger waveform), negative shift left (view post-trigger waveform). Unit: time (s/ms/µs).</td></tr>
</table>
<p class="tip">Knob operation: hold center and rotate-drag (clockwise increases) / scroll wheel for fine adjustment, real-time without lag.</p>

<h3>5.4 Channel Panel</h3>
<p>The channel panel is on the left of the waveform display area, managing display and parameters for all channels. When ≤5 channels, all are shown without pagination; when >5 channels, paged display with 5 channels per page.</p>

<h4>5.4.1 Channel Setting Row</h4>
<p>One row per channel, with the following controls (header and channel rows strictly aligned):</p>
<table class="ctl">
<tr><th>Column</th><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Display</td><td>Channel switch</td><td>Checkbox</td><td>Check to show this channel waveform, uncheck to hide. Only controls display; does not affect data reception or caching.</td></tr>
<tr><td>Channel</td><td>Channel name</td><td>Label</td><td>Channel identifier (ch1~ch8 or M1~M4), color matches waveform color.</td></tr>
<tr><td>Coupling</td><td>Coupling mode</td><td>Dropdown</td><td>DC / AC. DC: displays raw data directly; AC: removes the DC component (raw value minus the mean of the latest 10000-sample sliding window, equivalent to an AC-coupling capacitor keeping only the AC part), displays AC content centered at 0V. Vertical position is forced to 0 in AC coupling. Physical and math channels (M1-M4) share the <b>same</b> sliding-window AC algorithm, so any "source-coupling × math-coupling" combination yields identical waveforms (e.g. ch1=DC/M1=AC is equivalent to ch1=AC/M1=AC).</td></tr>
<tr><td>Vertical Sensitivity</td><td>Volts/Div / Scale</td><td>Editable dropdown</td><td>Voltage value per vertical division. Standard 1-2-5 sequence: 1 mV/div ~ 10 V/div (coarse settings at 1X probe, 1MΩ input impedance). Arbitrary values can be entered manually. Waveform scales around the vertical position reference point when adjusted.</td></tr>
<tr><td>Vertical Position</td><td>Position</td><td>Number input</td><td>Vertical position of the waveform on screen, in divisions (div). Range ±5 div, resolution 0.01 div, default 0. Continuously adjustable, no fixed steps. Positive moves waveform up, negative down. Can also be adjusted by dragging the channel label (➡ch1) on the waveform display or hovering the scroll wheel; value syncs to this input in real time.</td></tr>
<tr><td>Unit</td><td>Unit</td><td>Editable dropdown</td><td>Channel value unit (V / mV / µV / nV / kV / MV, etc.), default V. The sole source for all unit conversions. Auto-parsed from the data format string, or manually selected/entered.</td></tr>
<tr><td>Color</td><td>Color swatch</td><td>Color picker</td><td>Waveform color for this channel. The entire cell is filled with the color and centered. Double-click the swatch to open the color picker.</td></tr>
</table>

<h4>5.4.2 Pagination Controls (shown when >5 channels)</h4>
<table class="ctl">
<tr><th>Control</th><th>Description</th></tr>
<tr><td>⏮ First</td><td>Jump to page 1. Disabled on page 1.</td></tr>
<tr><td>◀ Prev</td><td>Go to previous page. Disabled on page 1.</td></tr>
<tr><td>Page</td><td>Manually enter target page number (1-based), range 1~total pages.</td></tr>
<tr><td>/ Total Pages</td><td>Shows total page count.</td></tr>
<tr><td>N channels total</td><td>Shows total channel count (physical + enabled math channels).</td></tr>
<tr><td>Next ▶</td><td>Go to next page. Disabled on last page.</td></tr>
<tr><td>Last ⏭</td><td>Jump to last page. Disabled on last page.</td></tr>
</table>

<h3>5.5 Automatic Measurement Panel</h3>
<p>The automatic measurement panel calculates and displays 24 waveform parameters for the selected channel in real time, all results with units:</p>
<table class="ctl">
<tr><th>Measurement</th><th>English</th><th>Description</th></tr>
<tr><td>Vpp</td><td>Peak-to-Peak</td><td>Vmax - Vmin</td></tr>
<tr><td>Vmax</td><td>Maximum</td><td>Maximum value</td></tr>
<tr><td>Vmin</td><td>Minimum</td><td>Minimum value</td></tr>
<tr><td>High Level</td><td>High Level</td><td>Logic high level (from histogram bimodal analysis)</td></tr>
<tr><td>Low Level</td><td>Low Level</td><td>Logic low level</td></tr>
<tr><td>Amplitude</td><td>Amplitude</td><td>High Level - Low Level</td></tr>
<tr><td>RMS</td><td>Root Mean Square</td><td>RMS value (full record)</td></tr>
<tr><td>Mean</td><td>Mean</td><td>Arithmetic mean (full record)</td></tr>
<tr><td>Std Dev</td><td>Standard Deviation</td><td>Standard deviation</td></tr>
<tr><td>Overshoot</td><td>Overshoot</td><td>Rising edge overshoot percentage</td></tr>
<tr><td>Preshoot</td><td>Preshoot</td><td>Rising edge preshoot percentage</td></tr>
<tr><td>Frequency</td><td>Frequency</td><td>Signal frequency</td></tr>
<tr><td>Period</td><td>Period</td><td>Signal period</td></tr>
<tr><td>Fall Time</td><td>Fall Time</td><td>Fall time from 90% to 10%</td></tr>
<tr><td>Rise Time</td><td>Rise Time</td><td>Rise time from 10% to 90%</td></tr>
<tr><td>Duty Cycle</td><td>Duty Cycle</td><td>Positive width as percentage of period</td></tr>
<tr><td>Positive Width</td><td>Positive Width</td><td>Positive pulse width</td></tr>
<tr><td>Negative Width</td><td>Negative Width</td><td>Negative pulse width</td></tr>
<tr><td>Trigger</td><td>Trigger</td><td>Trigger level value</td></tr>
<tr><td>Area</td><td>Area</td><td>Waveform integral area</td></tr>
<tr><td>Rise Slew</td><td>Rise Slew Rate</td><td>Maximum rising edge slope</td></tr>
<tr><td>Fall Slew</td><td>Fall Slew Rate</td><td>Maximum falling edge slope</td></tr>
<tr><td>Cycle RMS</td><td>Cycle RMS</td><td>Single-cycle RMS value</td></tr>
<tr><td>Cycle Mean</td><td>Cycle Mean</td><td>Single-cycle mean value</td></tr>
</table>
<p>Channel Select: dropdown to select the measurement target channel. Unit: displays current channel unit.</p>

<h3>5.6 Math Panel (M1~M4)</h3>
<p>Math channels perform custom expression operations on physical channel data, with results displayed, measured, and triggered as independent channels.</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>M1~M4 Enable</td><td>Checkbox</td><td>Check to enable the corresponding math channel. When enabled, it is automatically added to the channel panel (display switch/coupling/vertical sensitivity/vertical position/unit/color), with control logic identical to physical channels. Uncheck to remove from the channel panel.</td></tr>
<tr><td>Expression</td><td>Input</td><td>Math operation expression. Supports: channel references (ch1~ch8), arithmetic (+ - * / ^ power), unary minus, constants (pi/e), functions (abs/sqrt/log/lg/log10/ln/loge/exp/sin/cos/tan/not/diff/integ/integral/pow/min/max/and/or/xor/lowpass/highpass/bandpass/bandstop). Examples: <code>ch1+ch2</code>, <code>sin(ch1)*3</code>, <code>ch1*ch2+1</code>, <code>lowpass(ch1,0.1)</code>.</td></tr>
<tr><td>Color swatch</td><td>Color picker</td><td>Math channel waveform color.</td></tr>
</table>
<p class="tip">Automatic unit conversion: if ch1 is in V and ch2 is in mV, expression <code>ch1+ch2</code> automatically converts to ch1 + ch2×0.001 (unified to V). Math channel data source is the result of expression operations on raw data; vertical sensitivity/position only affect screen display, not measurement values.</p>
<p class="tip">Default unit auto-follow: a math channel's default unit automatically equals the unit of the <strong>first referenced physical channel</strong> in its expression — e.g., M1=ch1 follows ch1; M1=ch2+1 follows ch2; M1=ch3+ch1 follows ch3. After manually editing a math channel's unit, that channel stops auto-following (manual setting is kept).</p>
<p class="tip">AC/DC coupling: math channels share the same sliding-window AC algorithm as physical channels. A math channel evaluates its expression on each source channel's <strong>coupled data</strong> (raw data when the source is DC, already DC-removed when the source is AC), then applies its own coupling to the result (DC pass-through / AC DC-removal). Thus for M1=ch1: ch1=DC/M1=AC is exactly identical to ch1 set to AC; ch1=AC/M1=DC is also identical to ch1=AC; ch1=AC/M1=AC applies AC removal to an already-DC-removed signal, so the residual is negligible (visually indistinguishable). Online per-sample and full replay are strictly identical, with no initialization transient.</p>

<h3>5.7 Waveform Display Area</h3>
<p>The waveform display area is the core output of the oscilloscope, using a standard oscilloscope graticule:</p>
<ul>
<li><b>Graticule Structure</b>: 10 major horizontal divisions, 10 major vertical divisions. The center cross is solid (screen center); all other major grid lines are shown as discrete dots.</li>
<li><b>Major Grid Intersections</b>: 11×11 brighter dots (size=5), marking major grid line intersections.</li>
<li><b>Minor Grid Dots</b>: Only on major grid lines, 9 small dots (size=2, dimmer) between each major division, dividing each major division into 10 minor divisions. No minor dots inside major grid cells.</li>
<li><b>Y-Axis Range</b>: Center at vertical position 0, 5 divisions up, 5 divisions down. Positive limit = Vertical Sensitivity × 5, negative limit = −Vertical Sensitivity × 5.</li>
<li><b>X-Axis Range</b>: 10 horizontal divisions, center corresponds to horizontal position 0 (trigger point at screen center). Right limit = Timebase × 5, left limit = −Timebase × 5.</li>
<li><b>Static Graticule</b>: The background graticule remains static throughout the entire application runtime — it does not move or scale with mouse wheel, nor scroll with data. Only waveform data points move.</li>
</ul>

<h4>5.7.1 Screen Marker Elements</h4>
<table class="ctl">
<tr><th>Element</th><th>Technical Term</th><th>Description</th></tr>
<tr><td>⬇ Trigger Point</td><td>Horizontal Time Reference / Trigger Point</td><td>Located at the very top of the waveform display area, ⬇ top aligned with area top. Marks the time zero (t=0) position — the moment the trigger event occurs. Moves horizontally with horizontal position adjustment.</td></tr>
<tr><td>➡ch1~➡ch8</td><td>Channel Identifier / Channel Label</td><td>Located at the far left of the waveform display area, ⬅ left aligned with area left. Color matches waveform color. Marks the channel's 0V vertical reference position. Moves vertically with vertical position adjustment; waveform scales around this point. Can be dragged or hover-scrolled to adjust vertical position.</td></tr>
<tr><td>Center Cross</td><td>Center Crosshair</td><td>Horizontal + vertical solid lines at screen center, the only solid graticule element.</td></tr>
</table>

<h4>5.7.2 Waveform Display Options</h4>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Display Mode</td><td>Dropdown</td><td>Vector (lines between points) / Dots (sample points only).</td></tr>
<tr><td>Persistance</td><td>Dropdown</td><td>Off / Variable / Infinite. Persistence mode retains historical waveform traces for observing sporadic signals.</td></tr>
</table>

<h3>5.8 Cursor Measurement Panel</h3>
<p>Cursor measurement provides precise waveform parameter readings with dual X/Y cursor groups.</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Cursor Mode</td><td>Dropdown</td><td>Off / Manual / Track / Auto. Off: no cursors; Manual: user freely drags cursor positions; Track: cursors auto-track waveform edges; Auto: auto-measures and displays readings.</td></tr>
<tr><td>XA / XB</td><td>Buttons</td><td>Select/display time position of horizontal cursor A / B.</td></tr>
<tr><td>YA / YB</td><td>Buttons</td><td>Select/display voltage position of vertical cursor A / B.</td></tr>
<tr><td>Source</td><td>Dropdown</td><td>Target channel for cursor tracking.</td></tr>
<tr><td>Zoom Follow</td><td>Checkbox</td><td>When checked, cursor positions auto-adjust with timebase/vertical sensitivity scaling.</td></tr>
<tr><td>Link</td><td>Checkbox</td><td>When checked, XA/XB or YA/YB move in tandem (maintaining spacing).</td></tr>
<tr><td>Align to Wave</td><td>Button</td><td>Auto-align cursors to waveform feature points (edges/peaks).</td></tr>
<tr><td>Reset Screen</td><td>Button</td><td>Reset cursor positions to defaults and restore waveform display layout.</td></tr>
</table>
<p><b>Cursor Readout</b>: The bottom status bar displays cursor measurement results in real time: orange/green vertical lines measure time Δt and 1/Δt; dashed horizontal bars measure amplitude ΔV.</p>
<p class="tip">Cursor operation: click and drag lines to move; hover scroll wheel for fine adjustment; Shift+drag for coarse adjustment; Tab cycles through cursors; Esc cancels current operation.</p>

<h2>6. FFT Spectrum</h2>
<p>The FFT spectrum analysis module runs independently, performing Fast Fourier Transform on selected channel data to display frequency-domain characteristics.</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Channel</td><td>Dropdown</td><td>Select the target channel for FFT analysis.</td></tr>
<tr><td>FFT Mode</td><td>Dropdown</td><td>Amplitude / Phase / Real / Imaginary.</td></tr>
<tr><td>Window</td><td>Dropdown</td><td>Rectangular / Hann / Hamming / Blackman / Flattop. Window functions reduce spectral leakage; different windows suit different measurement scenarios.</td></tr>
<tr><td>Sample Rate</td><td>Number input</td><td>ADC sample rate (Hz), used to calculate frequency axis, Nyquist frequency, and frequency resolution.</td></tr>
<tr><td>FFT Points</td><td>Dropdown</td><td>FFT calculation points (e.g., 1024 / 2048 / 4096 / 8192). More points = higher frequency resolution.</td></tr>
<tr><td>dB Display</td><td>Checkbox</td><td>When checked, amplitude is displayed on logarithmic dB scale.</td></tr>
<tr><td>Peak List</td><td>Panel</td><td>Auto-identifies and lists frequency and amplitude of spectrum peaks.</td></tr>
<tr><td>Save PNG</td><td>Button</td><td>Saves the current FFT spectrum plot as a PNG image; on completion an "Open / Open Folder / OK" dialog is shown.</td></tr>
</table>

<h2>7. Data Distribution</h2>
<p>The data distribution view displays statistical distribution histograms and complete statistical parameters for each channel.</p>
<table class="ctl">
<tr><th>Control</th><th>Type</th><th>Description</th></tr>
<tr><td>Channel Select</td><td>Tabs/Dropdown</td><td>Select the channel to view distribution; each channel displayed independently.</td></tr>
<tr><td>Bin Count</td><td>Number input</td><td>Histogram bin count.</td></tr>
<tr><td>Point Count</td><td>Label</td><td>Current number of sample points in statistics.</td></tr>
<tr><td>Reset</td><td>Button</td><td>Clear statistical data and restart.</td></tr>
<tr><td>Gaussian Fit</td><td>Curve</td><td>Overlays normal distribution fit curve on the histogram.</td></tr>
<tr><td>3σ Marker Lines</td><td>Red dashed</td><td>Marks mean ±3σ range with value labels at top, dynamically following data updates.</td></tr>
</table>
<p><b>Statistical Parameters</b>: Mean, median, mode, variance, standard deviation, IQR (Interquartile Range), MAD (Mean Absolute Deviation), skewness, kurtosis, minimum, maximum, quantiles (P1/P5/P25/P50/P75/P95/P99), etc.</p>
<p class="tip"><b>Right-click Menu</b>: Right-click on a distribution chart to choose: <b>Reset</b> (clear this channel statistics and re-accumulate), <b>Save PNG</b> (save this channel chart with statistics as PNG), <b>Export CSV</b> (histogram bin centers + counts, UTF-8 BOM for direct Excel opening), <b>Copy Image</b> (copy the chart to clipboard). Save/export completion also shows the "Open / Open Folder / OK" dialog.</p>

<h2>8. Global Serial Tool Feature Comparison</h2>
{_cmp_table_html(False)}

<h2>9. Tips & FAQ</h2>
<h3>9.1 Tips</h3>
<ul>
<li><b>Echo-capable devices</b> (e.g., RT-Thread msh, Linux shell): disable "Local Echo" — the screen is driven entirely by device echo, with input following the device prompt (e.g., <code>msh &gt;help</code>). This is the default behavior of PuTTY / WindTerm (Local Echo = Off).</li>
<li><b>Non-echo devices</b>: enable "Local Echo" — the terminal displays typed characters itself, otherwise the user cannot see input (Local Echo = On).</li>
<li><b>Local echo + device echo simultaneously</b> causes each character to appear twice (once local, once device). This is normal behavior; select the appropriate echo mode based on the device type.</li>
<li><b>Auto Setup</b>: After connecting a signal, click Auto — the program auto-detects each enabled channel, selects the trigger source only from physical channels (ch1-ch8), picking the highest-voltage one (lowest-numbered when amplitudes are comparable) with a 50% median trigger level (enabled math channels M1-M4 participate in per-channel vertical scaling but are not used as the trigger source), sets the timebase to show 2-5 complete cycles (closest to ~3), and arranges vertical scaling as follows: with 2+ enabled channels that all have data, they are <b>separated</b> top-down (Keysight Autoscale style) — each channel gets its own screen band, waveforms never overlap, per-channel V/div is maximized so the fluctuation fills 70% of its band (unclipped), and the vertical position is set to the band center with DC-bias compensation; with a single channel it uses the overlay mode — waveform ~70% of screen height, 0 V ground centered, pulling the waveform back with a vertical offset only if DC offset overflows — the offset is clamped to ±3 div so the waveform midpoint always stays in the central region; if the bias is too large the V/div is increased automatically to shrink the waveform back toward center while keeping it unclipped. Auto never changes any channel's DC/AC coupling.</li>
<li><b>Channel Label Drag</b>: Drag the ➡chN label on the left of the waveform display to quickly adjust that channel's vertical position; hovering the scroll wheel also fine-tunes, with values syncing to the channel panel in real time.</li>
<li><b>Math Channel Unit Conversion</b>: Channels with different units in expressions are automatically converted to a unified unit (e.g., V + mV auto-converts), no manual conversion needed.</li>
<li><b>Paged Channel Browsing</b>: When more than 5 channels, use pagination controls (First/Prev/Page/Next/Last) to browse, 5 channels per page.</li>
</ul>

<h3>9.2 FAQ</h3>
<ul>
<li><b>Q: No waveform displayed?</b><br>A: Check ① data format correctly parses channels (see "Recognized Channels" label); ② channel display switch is checked; ③ communication interface is open and receiving data; ④ vertical sensitivity is not too large (waveform collapsed to a line).</li>
<li><b>Q: Serial port not found?</b><br>A: Click "Refresh" to re-enumerate; check USB-to-serial driver is installed; verify port in Device Manager (Windows) or /dev (Linux/macOS).</li>
<li><b>Q: Ethernet connection failed?</b><br>A: Check ① protocol selection correct (TCP Client/Server/UDP); ② IP address and port correct; ③ firewall not blocking; ④ in TCP Server mode, local IP and port can be bound.</li>
<li><b>Q: Characters appear twice?</b><br>A: This is because "Local Echo" is enabled AND the device also echoes. Disable "Local Echo" (echo-capable devices should have local echo off).</li>
<li><b>Q: How to set trigger level?</b><br>A: Adjust via the top "Trigger Level" number input or the "Trigger Level" knob in the knob zone. The level should be between the signal's high and low levels for stable triggering.</li>
<li><b>Q: How to export waveform data?</b><br>A: Menu "File → Export Waveform CSV" or the "Export CSV" button on the oscilloscope page exports all current channel data to a CSV file.</li>
</ul>

<h3>9.3 Keyboard Shortcuts</h3>
<h4>Communication Terminal (input line focused)</h4>
<table class="ctl">
<tr><th>Key</th><th>Function</th></tr>
<tr><td>Enter</td><td>Send current input line</td></tr>
<tr><td>Shift+Enter</td><td>Insert newline in input (multi-line input)</td></tr>
<tr><td>↑ / ↓</td><td>Browse send history (older / newer)</td></tr>
<tr><td>Ctrl+↑ / Ctrl+↓</td><td>Browse send history</td></tr>
<tr><td>Esc</td><td>Clear input line</td></tr>
<tr><td>Ctrl+C</td><td>Copy if text selected; otherwise send Ctrl-C (0x03 break character)</td></tr>
<tr><td>Ctrl+V</td><td>Paste clipboard text</td></tr>
<tr><td>Ctrl+A</td><td>Select all input</td></tr>
<tr><td>Tab</td><td>Send a tab character (rendered as visible indent)</td></tr>
<tr><td>Arrow / Home / End / PgUp / PgDn / Insert / Delete / F1-F12</td><td>Send standard terminal control sequences (no control markers rendered locally)</td></tr>
</table>
<h4>Waveform Window (cursor measurement enabled)</h4>
<table class="ctl">
<tr><th>Key</th><th>Function</th></tr>
<tr><td>Tab</td><td>Cycle active cursor (X1 / X2 / Y1 / Y2)</td></tr>
<tr><td>Arrow keys</td><td>Fine-adjust active cursor position</td></tr>
<tr><td>Shift+Arrow keys</td><td>Coarse-adjust active cursor position</td></tr>
<tr><td>Esc</td><td>Exit cursor editing</td></tr>
<tr><td>➡chN label drag</td><td>Quickly adjust that channel's vertical position; hover scroll wheel fine-tunes</td></tr>
<tr><td>Waveform scroll wheel</td><td>Horizontal zoom of timebase (fine-tune on hover)</td></tr>
</table>
"""

    body = zh_body if zh else en_body
    return f"<html><head><meta charset='utf-8'><title>{title}</title>{css}</head><body>{body}</body></html>"
