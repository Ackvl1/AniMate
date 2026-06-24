"""Tests for async Node — 图引擎运行 async Node"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from animate.core.engine.graph import Graph
from animate.core.engine.node import Node, NodeResult
from animate.core.engine.context import RunContext


@pytest.mark.asyncio
async def test_graph_can_run_async_node():
    """图引擎应能运行 async Node 并正确路由。"""

    events = []

    async def emit(type, **data):
        events.append((type, data))

    class GreetNode(Node):
        async def run(self, ctx, emit):
            await emit("text_token", text=f"你好，{ctx.user_input}")
            return NodeResult(next_node="done", data={"greeting": True})

    g = Graph()
    g.add_node("start", GreetNode())
    g.add_node("done", GreetNode())
    g.add_edge("start", "done")
    g.set_entry("start")

    ctx = RunContext(user_input="世界")
    engine = g.create_engine(max_steps=5)
    await engine.run(ctx)

    assert "start" in engine.executed_nodes
    assert "done" in engine.executed_nodes
    assert len(engine.executed_nodes) == 2
