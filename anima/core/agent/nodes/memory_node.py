"""MemoryNode — 长期记忆图接入点。在 fan_out 之前检索事实并注入 ctx.extras。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from anima.core.engine.node import Node, NodeResult
from anima.core.log import setup_logger

if TYPE_CHECKING:
    from anima.core.engine.context import RunContext
    from anima.core.memory.provider import MemoryProvider

logger = setup_logger(__name__)


class MemoryNode(Node):
    """从 MemoryProvider 检索长期事实，写入 ctx.extras["memory_facts"]。

    注册在 graph 的 fan_out 之前，与 RAG 节点不会并行冲突。
    """

    reads = {"user_input"}
    writes = {"memory_facts"}

    def __init__(self, provider: MemoryProvider):
        self._provider = provider

    async def run(self, ctx: RunContext, emit) -> NodeResult:
        await emit("node.start", name="memory")
        try:
            facts = self._provider.prefetch(ctx.user_input, limit=5)
        except Exception as e:
            logger.warning("[%s] MemoryNode prefetch failed: %s", ctx.trace_id, e)
            facts = []

        await emit("node.done", name="memory", count=len(facts))
        return NodeResult(
            diff={"memory_facts": facts},
        )
