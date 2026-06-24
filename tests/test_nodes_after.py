"""Tests for AfterNode (inline marker 版) — emotion/gesture 校验 + 复合规则"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from animate.core.engine.context import RunContext
from animate.core.engine.node import Node, NodeResult
from animate.core.agent.nodes.after import AfterNode


@pytest.mark.asyncio
async def test_is_node_subclass():
    node = AfterNode()
    assert isinstance(node, Node)


@pytest.mark.asyncio
async def test_empty_text_returns_reflect():
    """空文本直接返回 reflect。"""
    node = AfterNode()
    ctx = RunContext(user_input="hi")
    ctx.raw_text = ""
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "reflect"
    assert ctx.final_text == ""


@pytest.mark.asyncio
async def test_plain_text_passthrough():
    """纯文本直接透传。"""
    node = AfterNode()
    ctx = RunContext(user_input="hello")
    ctx.raw_text = "你好世界"
    ctx.emotion = "happy"
    ctx.gesture = "wave"
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "reflect"
    assert ctx.final_text == "你好世界"


@pytest.mark.asyncio
async def test_unknown_emotion_fallback_to_calm():
    """未知 emotion 应兜底为 calm。"""
    node = AfterNode()
    ctx = RunContext(user_input="hi")
    ctx.raw_text = "test"
    ctx.emotion = "unknown_xyz"
    await node.run(ctx, AsyncMock())
    assert ctx.emotion == "calm"


@pytest.mark.asyncio
async def test_emotion_validated():
    """已知 emotion 保持不変。"""
    node = AfterNode()
    ctx = RunContext(user_input="hi")
    ctx.raw_text = "hello"
    ctx.emotion = "happy"
    await node.run(ctx, AsyncMock())
    assert ctx.emotion == "happy"


@pytest.mark.asyncio
async def test_gesture_composite_rule():
    """emotion 对 gesture 的限制规则应生效。"""
    node = AfterNode()
    ctx = RunContext(user_input="hi")
    ctx.raw_text = "sad day"
    ctx.emotion = "sad"
    ctx.gesture = "wave"  # sad 不能配 wave
    await node.run(ctx, AsyncMock())
    assert ctx.gesture is not None
    assert ctx.gesture != "wave"
    assert ctx.gesture in AfterNode.EMOTION_GESTURE_RULES["sad"]


@pytest.mark.asyncio
async def test_unknown_gesture_removed():
    """未知 gesture 应被移除。"""
    node = AfterNode()
    ctx = RunContext(user_input="hi")
    ctx.raw_text = "test"
    ctx.emotion = "calm"
    ctx.gesture = "unknown_gesture_xyz"
    await node.run(ctx, AsyncMock())
    assert ctx.gesture is None


@pytest.mark.asyncio
async def test_marker_cleanup():
    """LLM 留下的标记应被清除。"""
    node = AfterNode()
    ctx = RunContext(user_input="hi")
    ctx.raw_text = "(happy,wave)你好！(sad,sigh)不过..."
    await node.run(ctx, AsyncMock())
    assert ctx.final_text == "你好！不过..."
