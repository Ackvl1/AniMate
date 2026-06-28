"""LocalTool ABC — 本地工具基类"""

from abc import ABC, abstractmethod


class LocalTool(ABC):
    """本地工具基类。子类只需定义 name / description / execute。

    安全属性（fail-closed 默认值）：
      - is_read_only: False  → 默认视为有副作用（写操作）
      - is_parallel_safe: False → 默认不能并发执行
      - is_destructive: False   → 默认非破坏性
    """

    name: str = ""
    description: str = ""
    parameters: dict = None  # JSON Schema

    # Fail-closed 安全属性（默认最严格）
    is_read_only: bool = False
    is_parallel_safe: bool = False
    is_destructive: bool = False

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """执行工具。kwargs 由 LLM tool_call arguments 映射而来。"""

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
                # 安全元信息（LLM 可见，用于自主决策）
                "x_is_read_only": self.is_read_only,
                "x_is_destructive": self.is_destructive,
            },
        }
