"""
LLM 响应模型 — LLMResult 和 ToolCall
模型目录 — 从 core/config.yaml 加载
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ── 从 core/config 导入目录（单一数据源） ──────────────

from animate.core.config import LLM_CATALOG, EMBEDDING_CATALOG


def find_provider_by_model(model_name: str) -> str | None:
    """通过模型名找到所属 LLM provider。"""
    for provider, info in LLM_CATALOG.items():
        if model_name in info["models"]:
            return provider
    return None


@dataclass
class ToolCall:
    """LLM 返回的工具调用。"""
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_assistant_message(self, content: str = "") -> dict:
        """转换为 OpenAI messages 格式的 assistant 消息，保留思考文本。"""
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": self.id,
                    "type": "function",
                    "function": {
                        "name": self.name,
                        "arguments": json.dumps(self.arguments, ensure_ascii=False),
                    },
                }
            ],
        }

    def to_tool_message(self, result: str) -> dict:
        """转换为 OpenAI messages 格式的 tool 消息。"""
        return {
            "role": "tool",
            "tool_call_id": self.id,
            "content": result,
        }

    @classmethod
    def from_openai(cls, raw: Any) -> list[ToolCall] | None:
        """从 openai SDK 的 tool_calls 原始对象解析。"""
        if not raw:
            return None
        result = []
        for tc in raw:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            result.append(cls(id=tc.id, name=tc.function.name, arguments=args))
        return result


@dataclass
class LLMResult:
    """LLM 调用结果，包含文本和可选的工具调用。"""
    content: str
    tool_calls: list[ToolCall] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
