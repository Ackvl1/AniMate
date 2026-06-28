"""MemoryProvider ABC — 长期记忆插件接口。

参考 Hermes MemoryProvider 设计。Anima Agent 的长期记忆模块统一通过此接口接入。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class MemoryProvider(ABC):
    """抽象基类：定义长期记忆的标准接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """短标识 (e.g. 'default', 'holographic')."""

    @abstractmethod
    def is_available(self) -> bool:
        """检查可用性。纯本地 SQLite 实现永远返回 True。"""

    @abstractmethod
    def initialize(self, session_id: str) -> None:
        """绑定到 session，初始化存储资源。"""

    def prefetch(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """每轮对话前检索相关长期事实。返回事实列表。"""
        return []

    def queue_prefetch(self, query: str) -> None:
        """异步触发预取（下一轮用）。默认同步执行。"""

    def sync_turn(self, user_content: str, assistant_content: str) -> None:
        """每轮对话后记录到长期记忆。默认为空操作。"""

    def on_session_switch(self, new_session_id: str, old_session_id: str) -> None:
        """session rotation 时回调。更新内部 session_id 跟踪。"""

    def on_session_end(self, messages: list[dict], llm=None) -> None:
        """会话结束时提取长期事实。默认空操作。"""

    @abstractmethod
    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """返回此 provider 暴露的工具 schema 列表。"""

    @abstractmethod
    def handle_tool_call(self, tool_name: str, args: dict[str, Any]) -> str:
        """处理 LLM 调用的记忆工具。返回 JSON 字符串。"""

    def shutdown(self) -> None:
        """释放资源。"""
