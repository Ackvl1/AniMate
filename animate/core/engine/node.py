"""Node ABC — 图引擎的节点基类（无状态纯函数）"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from animate.core.engine.context import RunContext

    # EventEmitter 类型：Node 通过它发射事件
    EventEmitter = Any


@dataclass
class NodeResult:
    """Node.run() 的输出。"""
    next_node: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] | None = None  # Phase 6: 状态差异


@dataclass(init=False)
class AgentEvent:
    """图引擎流式事件。"""
    type: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __init__(self, type: str = "", **data):
        self.type = type
        self.data = data

    def __getattr__(self, name):
        if name in self.data:
            return self.data[name]
        raise AttributeError(f"AgentEvent has no '{name}' in data")


class Node(ABC):
    """图引擎节点基类——无状态纯函数。

    每个 Node 声明自己的 reads/writes 字段：
    - reads: 本节点读取的 ctx 字段名（用于冲突检测）
    - writes: 本节点写入的 ctx 字段名（用于冲突检测）

    run() 是唯一接口：输入 ctx，输出 NodeResult。
    """

    reads: set[str] = set()
    writes: set[str] = set()

    def __init_subclass__(cls, **kwargs):
        """每个子类获得独立的 reads/writes copy，防止类属性共享。"""
        super().__init_subclass__(**kwargs)
        cls.reads = set(cls.reads)
        cls.writes = set(cls.writes)

    @abstractmethod
    async def run(self, ctx: RunContext, emit: EventEmitter) -> NodeResult:
        """执行节点逻辑。

        Args:
            ctx: 共享运行时上下文
            emit: 事件发射器，Node 通过它广播 AgentEvent

        Returns:
            NodeResult，包含下一节点名（可选）和携带数据
        """
        ...
