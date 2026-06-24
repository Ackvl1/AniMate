"""Tests for new engine Node ABC — async run + emit + NodeResult"""
import pytest
from unittest.mock import AsyncMock

from animate.core.engine.node import Node, NodeResult, AgentEvent
from animate.core.engine.context import RunContext, RunServices


class TestNodeABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Node()

    def test_subclass_must_implement_run(self):
        with pytest.raises(TypeError):
            type("IncompleteNode", (Node,), {})()

    @pytest.mark.asyncio
    async def test_subclass_can_implement_run(self):
        class TestNode(Node):
            async def run(self, ctx, emit):
                return NodeResult(next_node="react")

        node = TestNode()
        ctx = RunContext(user_input="hi")
        result = await node.run(ctx, AsyncMock())
        assert result.next_node == "react"

    @pytest.mark.asyncio
    async def test_run_returns_node_result(self):
        class TestNode(Node):
            async def run(self, ctx, emit):
                return NodeResult(next_node="done", data={"key": "val"})

        node = TestNode()
        ctx = RunContext(user_input="hi")
        result = await node.run(ctx, AsyncMock())
        assert isinstance(result, NodeResult)
        assert result.data["key"] == "val"

    @pytest.mark.asyncio
    async def test_run_can_return_none(self):
        class EndNode(Node):
            async def run(self, ctx, emit):
                return NodeResult()

        node = EndNode()
        ctx = RunContext(user_input="hi")
        result = await node.run(ctx, AsyncMock())
        assert result.next_node is None

    @pytest.mark.asyncio
    async def test_emit_called_during_run(self):
        events = []

        async def emit(type, **data):
            events.append((type, data))

        class EmitNode(Node):
            async def run(self, ctx, emit):
                await emit("text_token", text="hello")
                return NodeResult(next_node="done")

        node = EmitNode()
        ctx = RunContext(user_input="hi")
        await node.run(ctx, emit)
        assert len(events) == 1
        assert events[0][0] == "text_token"

    @pytest.mark.asyncio
    async def test_reads_writes_declared(self):
        """Node 可以声明 reads/writes"""
        class TestNode(Node):
            reads = {"user_input"}
            writes = {"messages"}
            async def run(self, ctx, emit):
                return NodeResult(next_node=None)

        node = TestNode()
        assert node.reads == {"user_input"}
        assert node.writes == {"messages"}
