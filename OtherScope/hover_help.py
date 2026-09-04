# -*- coding: utf-8 -*-
"""串口终端页控件「悬停 3 秒详细说明」辅助模块。

- 鼠标悬停在控件正上方 3 秒后，弹出该控件的【详细功能使用说明 + 最终视觉效果】。
- 支持状态感知：带选中/不选中状态的控件（复选框、可切换按钮），
  根据控件当前状态动态生成说明——选中时说明「选中」的用法与效果，
  未选中时说明「未选中」的用法与效果。
- 鼠标移出控件立即隐藏提示并取消计时。

用法：
    from .hover_help import install_hover_help, state_text
    install_hover_help(chk_echo, state_text(lambda: chk_echo.isChecked(), ON_HTML, OFF_HTML))
"""
from PySide6.QtCore import QObject, QTimer, QEvent, QRect
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip

# 悬停延迟（毫秒）与提示显示时长（毫秒）
DEFAULT_DELAY_MS = 3000
SHOW_MS = 15000

# 已安装过滤器的全局注册表：窗口关闭时统一停止其显示计时器（BUG-O 清理）
_INSTALLED_FILTERS = []


class _HoverHelpFilter(QObject):
    """按控件注册的事件过滤器：Enter 启动 3 秒计时，超时弹出详细说明。"""

    def __init__(self, widget, text_fn, delay_ms=DEFAULT_DELAY_MS):
        super().__init__(widget)          # 以控件为父对象，保证过滤器生命周期
        self._widget = widget
        self._text_fn = text_fn
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show)

    def eventFilter(self, widget, event):
        event_type = event.type()
        try:
            enter = QEvent.Type.Enter
            leave = QEvent.Type.Leave
        except AttributeError:            # 兼容旧式枚举访问
            enter, leave = QEvent.Enter, QEvent.Leave
        if event_type == enter:
            self._timer.start()
        elif event_type == leave:
            self._timer.stop()
            QToolTip.hideText()
        return False                      # 不拦截原事件

    def _shutdown(self):
        """停止本过滤器计时器并隐藏提示（窗口关闭前调用）。"""
        self._timer.stop()
        try:
            QToolTip.hideText()
        except Exception:             # noqa: BLE001 隐藏失败不影响退出
            pass

    def _show(self):
        try:
            if self._widget is None or not self._widget.isVisible():
                return
            text = self._text_fn()
        except Exception:                 # noqa: BLE001 说明生成失败不弹即可
            return
        if text:
            try:
                QToolTip.showText(QCursor.pos(), text, self._widget, QRect(), SHOW_MS)
            except Exception:             # noqa: BLE001
                pass


def install_hover_help(widget, text_fn, delay_ms=DEFAULT_DELAY_MS):
    """给控件安装「悬停 delay_ms 毫秒后显示说明」。
    text_fn() 返回要显示的 HTML 文本（可返回空串表示不显示）。
    返回过滤器对象（被 Qt 事件系统引用，无需外部持有）。
    同一控件重复安装时复用既有过滤器，避免产生重复计时器。"""
    if widget is None:
        return None
    for filter_obj in _INSTALLED_FILTERS:
        try:
            if filter_obj._widget is widget:
                return filter_obj
        except RuntimeError:          # 已销毁的过滤器，跳过并继续查找
            continue
    filter_obj = _HoverHelpFilter(widget, text_fn, delay_ms)
    widget.installEventFilter(filter_obj)
    _INSTALLED_FILTERS.append(filter_obj)
    return filter_obj


def shutdown_hover():
    """窗口关闭前统一停止所有悬停帮助计时器并隐藏提示（BUG-O 清理）。

    只停止、不清空注册表：若计时器在本次清理后又意外启动（如语言/主题
    切换重建控件），closeEvent 再次调用本函数仍能统一停止；重复调用幂等
    （已停止的计时器再次 stop 无害）。"""
    for filter_obj in _INSTALLED_FILTERS:
        try:
            filter_obj._shutdown()
        except Exception:             # noqa: BLE001 单个清理失败不影响其余
            pass


def state_text(checked_get, on_text, off_text):
    """状态感知说明生成器：checked_get() 返回控件当前是否选中，
    选中显示 on_text，未选中显示 off_text。"""
    return lambda: (on_text if checked_get() else off_text)
