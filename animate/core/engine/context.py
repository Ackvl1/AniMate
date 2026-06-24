"""RunContext — 图引擎共享运行时上下文（带写保护声明）"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunServices:
    """运行时服务容器 — 每个 chat 调用可能变化的服务。

    稳定的依赖在 Node 构造时注入，运行时可变的通过此容器传入。
    """
    memory: Any | None = None


# ── 写保护：每个字段声明谁可以写 ──
FIELD_WRITERS: dict[str, set[str]] = {
    "user_input": {"input", "before"},
    "messages": {"before", "react"},
    "raw_text": {"react"},
    "final_text": {"after"},
    "emotion": {"before", "react", "emotion", "after"},
    "gesture": {"react", "emotion", "after"},
    "llm_call_count": {"react"},
    "is_retry": {"reflect"},
    "feedback": {"reflect"},
}


@dataclass
class RunContext:
    """图引擎节点之间共享的运行时上下文。

    字段按职责分组，可在运行时逐步填充。
    """

    # ── 输入 ──
    user_input: str = ""

    # ── 运行时追踪 ──
    trace_id: str = ""
    llm_call_count: int = 0
    accumulated_usage: int = 0
    is_retry: bool = False
    feedback: str = ""

    # ── 运行时服务 ──
    services: RunServices = field(default_factory=RunServices)

    # ── LLM 对话消息 ──
    messages: list[dict] = field(default_factory=list)

    # ── 输出数据 ──
    emotion: str = ""
    gesture: str | None = None
    raw_text: str = ""
    final_text: str = ""

    # ── 未知/扩展字段 ──
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = uuid.uuid4().hex[:8]

    def check_write_permission(self, field_name: str, node_name: str) -> bool:
        """检查节点是否有权限写入指定字段。"""
        allowed = FIELD_WRITERS.get(field_name, set())
        if not allowed:
            return True  # 未声明的字段允许任意写入
        return node_name in allowed
