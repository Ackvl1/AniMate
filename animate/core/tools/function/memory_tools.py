"""Memory 工具 — MemoryProvider 工具包装 + SessionSearch

将 MemoryProvider 的工具 schema 和 SessionSearch 包装为 LocalTool，
统一 to_schema() 格式（继承基类，自动带 type: "function"）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from animate.core.tools.base import LocalTool
from animate.core.log import setup_logger

if TYPE_CHECKING:
    from animate.core.memory.provider import MemoryProvider
    from animate.core.session.store import SessionStore

logger = setup_logger(__name__)


class MemoryProviderToolWrapper(LocalTool):
    """将 MemoryProvider.get_tool_schemas() 的工具包装为 LocalTool。

    解决原来的 _MemoryToolWrapper 不继承 LocalTool 导致
    to_schema() 缺少 type: "function" 的问题。
    """

    def __init__(self, schema: dict[str, Any], provider: MemoryProvider):
        self.name = schema["name"]
        self.description = schema.get("description", "") or ""
        self.parameters = schema.get("parameters") or {"type": "object", "properties": {}}
        self._provider = provider
        # 安全属性：记忆工具有写操作（add/update/remove），非只读
        self.is_read_only = False
        self.is_parallel_safe = False
        self.is_destructive = False

    def execute(self, **kwargs) -> str:
        return self._provider.handle_tool_call(self.name, kwargs)


class SessionSearchTool(LocalTool):
    """搜索历史对话记录。

    让 LLM 可以回溯之前压缩掉的原始对话内容。
    """

    name = "session_search"
    description = "搜索历史对话记录。可以找到之前压缩掉的原始对话内容。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "最大返回条数", "default": 5},
        },
        "required": ["query"],
    }

    # 安全属性：搜索是只读的
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False

    def __init__(self, session_store: SessionStore, session_id: str):
        self._session_store = session_store
        self._session_id = session_id

    def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 5)
        results = self._session_store.search_ancestors(
            self._session_id, query, limit=limit
        )
        return json.dumps(results, ensure_ascii=False)
