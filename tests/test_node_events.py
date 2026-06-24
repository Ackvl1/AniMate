"""Tests for node-level logging — node.start / node.done 事件"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from animate.core.engine.context import RunContext
from animate.core.engine.node import Node, NodeResult
from animate.core.agent.nodes import (
    RAGVectorNode, RAGKeywordNode, SystemPromptNode, MergeNode,
    ReactNode, AfterNode, ReflectNode,
)
from animate.core.llm.models import LLMResult
from animate.core.tools.registry import ToolRegistry


class TestNodeEvents:
    """验证每个节点正确 emit node.start 和 node.done"""

    @pytest.mark.asyncio
    async def test_rag_vector_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        vs = MagicMock()
        vs.search.return_value = [("chunk1", 0.9), ("chunk2", 0.8)]
        node = RAGVectorNode(vector_store=vs)
        ctx = RunContext(user_input="test")
        await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types, f"应 emit node.start, 实际: {types}"
        assert "node.done" in types, f"应 emit node.done, 实际: {types}"

    @pytest.mark.asyncio
    async def test_rag_keyword_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        ks = MagicMock()
        ks.search.return_value = [("keyword_chunk", 0.85)]
        node = RAGKeywordNode(keyword_store=ks)
        ctx = RunContext(user_input="test")
        await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types
        assert "node.done" in types

    @pytest.mark.asyncio
    async def test_system_prompt_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        node = SystemPromptNode(persona="你是祥子")
        ctx = RunContext(user_input="hi")
        await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types
        assert "node.done" in types

    @pytest.mark.asyncio
    async def test_merge_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        node = MergeNode()
        ctx = RunContext(user_input="hi")
        ctx.extras["rag_vector_chunks"] = ["v1", "v2"]
        ctx.extras["rag_keyword_chunks"] = ["k1"]
        ctx.extras["system_parts"] = ["prompt"]
        await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types
        assert "node.done" in types

    @pytest.mark.asyncio
    async def test_react_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        llm = MagicMock()
        llm.chat_stream.return_value = [
            {"type": "delta", "content": "你好"},
            {"type": "done"},
        ]
        node = ReactNode(llm=llm, tools=ToolRegistry())
        ctx = RunContext(user_input="hi")
        ctx.messages = [{"role": "system", "content": "你"}]
        result = await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types
        assert "node.done" in types

    @pytest.mark.asyncio
    async def test_after_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        node = AfterNode()
        ctx = RunContext(user_input="hi")
        ctx.raw_text = "回复文本"
        await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types
        assert "node.done" in types

    @pytest.mark.asyncio
    async def test_reflect_emits_node_events(self):
        events = []
        async def emit(type, **data):
            events.append((type, data))

        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResult(
            content="<analysis>语气合适</analysis>\n<summary>{\"level\": 0, \"feedback\": \"完美\"}</summary>"
        )
        node = ReflectNode(llm=mock_llm)
        ctx = RunContext(user_input="hi")
        ctx.final_text = "好的回复"
        await node.run(ctx, emit)

        types = [e[0] for e in events]
        assert "node.start" in types
        assert "node.done" in types
