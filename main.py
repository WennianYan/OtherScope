# -*- coding: utf-8 -*-
"""其他示波器（OtherScope）—— 程序入口。
运行：
    pip install -r requirements.txt
    python main.py
"""
import sys
import os
import faulthandler
import traceback as _tb


def _enable_crash_log():
    """启用崩溃日志：把未捕获异常与段错误信息写入 OtherScope_crash.log，
    避免程序闪退时用户看不到任何错误原因。"""
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "OtherScope_crash.log")
        fh = open(log_path, "a", encoding="utf-8")
        faulthandler.enable(file=fh)
        faulthandler.register(10, file=fh)  # SIGUSR1（Windows 无效，无害）
        sys.excepthook = lambda typ, val, tb: (
            fh.write("\n==== 未捕获异常 ====\n" + "".join(_tb.format_exception(typ, val, tb)) + "\n"),
            fh.flush())[1]
    except Exception:
        pass


def _wait_key():
    """等待用户按任意键（跨平台），避免启动失败时终端闪退。

    自动化启动模式（环境变量 OTHERSCOPE_AUTO_LAUNCH=1）下不等待，
    让外层 auto_launcher.py 的重试循环继续工作。
    """
    if os.environ.get("OTHERSCOPE_AUTO_LAUNCH") == "1":
        return
    print("\n按任意键退出...")
    try:
        if os.name == "nt":
            os.system("pause")
        else:
            import termios
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                new = termios.tcgetattr(fd)
                new[3] = new[3] & ~termios.ICANON & ~termios.ECHO
                termios.tcsetattr(fd, termios.TCSANOW, new)
                sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSANOW, old)
    except Exception:
        try:
            input()
        except Exception:
            pass


def _check_deps():
    """检查关键依赖版本，提示可能导致崩溃/异常的版本组合。

    已知问题：pyqtgraph 0.13.x 在 Python 3.12+（尤其 3.13/3.14）上，
    用 QPicture 绘制坐标轴会触发原生 access violation 崩溃（闪退），
    该问题在 pyqtgraph 0.14.0 通过 PR #3471（改为直接绘制、不再用 QPicture）修复。
    这里检测到危险组合时给出明确升级提示。
    """
    py = sys.version_info
    if py < (3, 12):
        return
    try:
        import pyqtgraph as _pg
        ver = tuple(int(x) for x in _pg.__version__.split(".")[:3])
        if ver < (0, 14, 0):
            print("=" * 62)
            print("警告：检测到可能导致崩溃的依赖版本")
            print("=" * 62)
            print(f"  当前 Python: {sys.version.split()[0]}")
            print(f"  当前 pyqtgraph: {_pg.__version__}（要求 >=0.14.0）")
            print("  原因：pyqtgraph <0.14.0 在 Python 3.12+ 下绘制坐标轴")
            print("  可能触发 access violation（闪退）。")
            print("  请升级依赖后重启程序：")
            print("    pip install -U pyqtgraph>=0.14.0")
            print("  或运行启动器自动修复：python launcher.py")
            print("=" * 62)
    except Exception:
        pass


def main():
    _enable_crash_log()
    # 自举启动器：打包态（单文件 exe）双击运行时，检测缺失系统库、
    # 自动安装并重启、异常图形提醒。源码方式运行时仅增强检测不阻断。
    try:
        from bootstrap import bootstrap as _bootstrap
        _bootstrap()
    except Exception:
        pass
    try:
        from PySide6.QtWidgets import QApplication
        from OtherScope.main_window import MainWindow
    except ImportError as exc:
        print("=" * 60)
        print("启动失败：缺少依赖项")
        print("=" * 60)
        print(f"错误信息：{exc}")
        print("\n请先安装依赖项：")
        print("  pip install PySide6 pyqtgraph pyserial numpy")
        print("\n或使用 requirements.txt：")
        print("  pip install -r requirements.txt")
        _wait_key()
        sys.exit(1)
    except Exception as exc:
        print("=" * 60)
        print("启动失败：导入模块时发生错误")
        print("=" * 60)
        print(f"错误信息：{exc}")
        import traceback
        traceback.print_exc()
        _wait_key()
        sys.exit(1)

    _check_deps()
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("其他示波器 OtherScope")
        # QFont 警告兜底：某些系统/样式下默认字体点数为 -1，导致
        # "QFont::setPointSize: Point size <= 0" 告警与坐标轴绘制异常。
        # 仅在检测到无效点数（<=0）时才修正，避免无谓覆盖用户系统字体。
        try:
            f = app.font()
            if f.pointSize() <= 0:
                f.setPointSize(9)
                app.setFont(f)
        except Exception:  # noqa: BLE001
            pass
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception as exc:
        print("=" * 60)
        print("程序运行时发生错误")
        print("=" * 60)
        print(f"错误信息：{exc}")
        import traceback
        traceback.print_exc()
        _wait_key()
        sys.exit(1)


if __name__ == "__main__":
    main()
