"""Tests for ReflectNode (新引擎接口) — LLM 质量评估 + retry 决策"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from animate.core.engine.context import RunContext
from animate.core.engine.node import Node, NodeResult
from animate.core.agent.nodes.reflect import ReflectNode
from animate.core.llm.models import LLMResult


class MockLLM:
    def __init__(self, reply: str = '{"level": 0, "feedback": ""}'):
        self.reply = reply
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1
        return LLMResult(content=self.reply)


@pytest.mark.asyncio
async def test_empty_text_returns_node_result_none():
    """空回复应返回 next_node=None。"""
    node = ReflectNode(llm=MockLLM())
    ctx = RunContext(user_input="hi")
    ctx.final_text = ""
    result = await node.run(ctx, AsyncMock())
    assert result.next_node is None


@pytest.mark.asyncio
async def test_good_quality_returns_none():
    """质量好时 next_node=None（结束）。"""
    node = ReflectNode(llm=MockLLM(reply='{"level": 0, "feedback": "完美"}'))
    ctx = RunContext(user_input="hi")
    ctx.final_text = "本小姐很好"
    result = await node.run(ctx, AsyncMock())
    assert result.next_node is None


@pytest.mark.asyncio
async def test_bad_quality_returns_react():
    """质量差时 next_node='react'。"""
    node = ReflectNode(llm=MockLLM(reply='{"level": 3, "feedback": "语气不对"}'))
    ctx = RunContext(user_input="hi")
    ctx.final_text = "本小姐很好"
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "react"
    assert "语气不对" in ctx.feedback


@pytest.mark.asyncio
async def test_need_retrieve_returns_before():
    """需要重检索时 next_node='before'。"""
    node = ReflectNode(llm=MockLLM(reply='{"level": 4, "feedback": "需要查知识库"}'))
    ctx = RunContext(user_input="祥子的背景")
    ctx.final_text = "不知道"
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "before"


@pytest.mark.asyncio
async def test_exceeds_max_llm_calls_returns_none():
    """超过 llm_call_count 上限时跳过评估。"""
    node = ReflectNode(llm=MockLLM())
    ctx = RunContext(user_input="hi")
    ctx.final_text = "test"
    ctx.llm_call_count = 20
    result = await node.run(ctx, AsyncMock())
    assert result.next_node is None


@pytest.mark.asyncio
async def test_emit_event_on_reflect():
    """reflect 评估后应 emit reflect.result 事件。"""
    events = []

    async def emit(type, **data):
        events.append((type, data))

    node = ReflectNode(llm=MockLLM(reply='{"level": 0, "feedback": "完美"}'))
    ctx = RunContext(user_input="hi")
    ctx.final_text = "好"
    await node.run(ctx, emit)

    assert any(e[0] == "reflect.result" for e in events)


@pytest.mark.asyncio
async def test_level_2_returns_react():
    """level 2（需重格式化）应返回 react。"""
    node = ReflectNode(llm=MockLLM(reply='{"level": 2, "feedback": "格式需修正"}'))
    ctx = RunContext(user_input="hi")
    ctx.final_text = "本小姐很好"
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "react"
