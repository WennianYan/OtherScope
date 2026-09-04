# -*- coding: utf-8 -*-
"""全局状态快照与配置持久化。

设计要点：
- ``ScopeState``：跨组件共享运行时状态的**单一数据源**快照（纯数据类）。
  主窗口在「保存/恢复」时成组读写它，自动化测试也用它做稳定的对象模型，
  为将来的「导入/导出配置」「撤销/重做」提供统一口径，避免状态散落各处。
- ``AppConfig``：基于 ``QSettings`` 的持久化，把语言 / 主题 / 串口 / 示波器
  偏好写入系统配置存储，跨会话保留用户习惯。读取时按快照字段类型归一化
  （``QSettings`` 从 INI/注册表读回时可能返回字符串），有效防止类型漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, fields

from PySide6.QtCore import QSettings


# ---------------------------------------------------------------------------
# ScopeState：运行时状态快照（单一数据源）
# ---------------------------------------------------------------------------
@dataclass
class ScopeState(object):
    """应用运行时状态的稳定快照，字段即持久化键。"""

    language: str = "en"          # "zh" / "en"
    theme: str = "dark"           # "dark" / "light"
    # 串口
    port: str = ""
    baudrate: int = 115200
    data_bits: int = 8
    stop_bits: str = "1"
    parity: str = "N"
    flow: str = "none"
    dtr: bool = True
    rts: bool = False
    # SOP V3.0：默认 Remote Mode（本地回显关闭），与 WindTerm 一致
    local_echo: bool = False
    # 示波器
    # BUG-18 修复：时基保存真实秒数值而非下拉框索引，避免版本间档位变化导致错位。
    # 同时保留 timebase_index 用于向后兼容旧配置（加载时优先用 value，fallback 到 index）。
    timebase_value: float = 0.1    # 时基真实值（秒/div），默认 100 ms/div
    timebase_index: int = 4        # [兼容旧版] 时基组合框索引
    max_points: int = 100000      # 每通道数据上限
    v_unit: str = "V"             # 测量读数与纵轴单位

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScopeState":
        """从字典重建状态对象（仅取已声明字段，忽略未知键）。"""
        valid = {field.name for field in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})


# ---------------------------------------------------------------------------
# AppConfig：配置持久化
# ---------------------------------------------------------------------------
class AppConfig(object):
    """基于 ``QSettings`` 的键值配置存取。

    键名集中声明在 ``ScopeState`` 中，杜绝散落魔法字符串；未设置时按默认值
    返回，绝不抛异常（配置损坏不影响启动）。
    """

    ORG = "OtherScope"
    APP = "OtherScope"

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings if settings is not None else QSettings(self.ORG, self.APP)

    def value(self, key: str, default=None):
        """读取配置值；未设置或为 None 时返回默认值。"""
        v = self._settings.value(key, default)
        return default if v is None else v

    def set_value(self, key: str, value):
        self._settings.setValue(key, value)

    def sync(self):
        self._settings.sync()

    def has_state(self) -> bool:
        """是否已写入过任何配置（用于区分首次运行与后续运行）。"""
        return bool(self._settings.allKeys())

    def save_state(self, state: ScopeState):
        for k, v in state.to_dict().items():
            self.set_value(k, v)

    def load_state(self, defaults: ScopeState | None = None) -> ScopeState:
        """从 QSettings 读取全部配置键并归一化为 ScopeState。

        Args:
            defaults: 提供类型模板与默认值；为 None 时用内置默认 ScopeState。

        Returns:
            已按模板类型归一化的状态对象；非法枚举值回退为默认。
        """
        defaults = defaults if defaults is not None else ScopeState()
        template = defaults.to_dict()
        data = {k: self.value(k, template[k]) for k in template}
        return ScopeState.from_dict(_coerce(data, template))


# 枚举字段的合法取值白名单（非法配置值回退为默认，防止污染运行态；
# 取值须与 main_window 的 _PARITY_OPTIONS/_FLOW_OPTIONS/停止位一致，防误回退）
_ENUM_WHITELIST = {
    "language": ("en", "zh"),
    "theme": ("dark", "light"),
    "parity": ("N", "E", "O", "M", "S"),
    "flow": ("none", "rts", "xon"),
    "stop_bits": ("1", "1.5", "2"),
}


def _coerce(data: dict, template: dict) -> dict:
    """按模板类型把 QSettings 读回的字符串归一化为正确的 Python 类型，
    并对枚举字段做白名单校验，非法值回退为模板默认值（BUG-N 加固）。"""
    for k, tpl in template.items():
        if k not in data:
            continue
        data[k] = _cast(data[k], tpl)
        if k in _ENUM_WHITELIST and data[k] not in _ENUM_WHITELIST[k]:
            data[k] = tpl
    return data


def _cast(v, type_name):
    if isinstance(type_name, bool):
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "on", "yes")
    if isinstance(type_name, int):
        try:
            return int(v)
        except (TypeError, ValueError):
            return type_name
    if isinstance(type_name, float):
        try:
            return float(v)
        except (TypeError, ValueError):
            return type_name
    return "" if v is None else v