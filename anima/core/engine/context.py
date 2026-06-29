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
    log_db: Any | None = None


# ── 写保护：每个字段声明谁可以写 ──
FIELD_WRITERS: dict[str, set[str]] = {
    "user_input": {"__entry__"},
    "messages": {"system_prompt", "merge", "react"},
    "raw_text": {"react"},
    "final_text": {"after"},
    "emotion": {"system_prompt", "react", "after"},
    "gesture": {"react", "after"},
    "llm_call_count": {"react", "reflect"},
    "accumulated_usage": {"react", "reflect"},
    "is_retry": {"reflect"},
    "feedback": {"reflect"},
    "retry_feedback_injected": {"system_prompt", "reflect"},
    "rag_vector_chunks": {"rag_vector"},
    "rag_keyword_chunks": {"rag_keyword"},
    "system_parts": {"system_prompt"},
    "memory_facts": {"memory"},
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
            self.trace_id = uuid.uuid4().hex[:12]

    def check_write_permission(self, field_name: str, node_name: str) -> bool:
        """检查节点是否有权限写入指定字段。"""
        allowed = FIELD_WRITERS.get(field_name, set())
        if not allowed:
            return True  # 未声明的字段允许任意写入
        return node_name in allowed
    
    def snapshot(self) -> dict:
        """返回可序列化的数据字段快照（排除 services）"""
        return {
            "user_input": self.user_input,
            "messages": list(self.messages),
            "emotion": self.emotion,
            "gesture": self.gesture,
            "raw_text": self.raw_text,
            "final_text": self.final_text,
            "is_retry": self.is_retry,
            "feedback": self.feedback,
            "llm_call_count": self.llm_call_count,
            "accumulated_usage": self.accumulated_usage,
            "extras": dict(self.extras),
        }
    
    def restore(self, snapshot: dict) -> None:
        """从快照恢复数据字段"""
        for key, value in snapshot.items():
            if key == "messages":
                self.messages.clear()
                self.messages.extend(value)
            elif key == "extras":
                self.extras.clear()
                self.extras.update(value)
            else:
                setattr(self, key, value)
