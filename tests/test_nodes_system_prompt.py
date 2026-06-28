"""Tests for SystemPromptNode — 人设 + EMOTION_INSTRUCTION + 长期记忆 + 重试反馈"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from animate.core.engine.context import RunContext
from animate.core.engine.node import Node, NodeResult


@pytest.mark.asyncio
async def test_is_node_subclass():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是祥子")
    assert isinstance(node, Node)


@pytest.mark.asyncio
async def test_returns_merge_next_node():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是祥子")
    ctx = RunContext(user_input="你好")
    result = await node.run(ctx, AsyncMock())
    assert result.next_node is None  # direct 边由引擎处理


@pytest.mark.asyncio
async def test_injects_persona():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是丰川祥子，大小姐语气")
    ctx = RunContext(user_input="你好")
    result = await node.run(ctx, AsyncMock())

    system_text = "\n\n".join(result.diff["system_parts"])
    assert "丰川祥子" in system_text
    assert "emotion" in system_text
    assert "gesture" in system_text


@pytest.mark.asyncio
async def test_injects_long_term_facts():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是祥子")
    ctx = RunContext(user_input="你好")
    ctx.extras["memory_facts"] = ["用户喜欢猫", "用户会弹钢琴"]
    result = await node.run(ctx, AsyncMock())

    system_text = "\n\n".join(result.diff["system_parts"])
    assert "用户喜欢猫" in system_text
    assert "用户会弹钢琴" in system_text
    assert "角色记忆" in system_text


@pytest.mark.asyncio
async def test_no_facts_omits_facts_section():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是祥子")
    ctx = RunContext(user_input="你好")
    result = await node.run(ctx, AsyncMock())

    system_text = "\n\n".join(result.diff["system_parts"])
    assert "角色记忆" not in system_text


@pytest.mark.asyncio
async def test_injects_retry_feedback():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是祥子")
    ctx = RunContext(user_input="再来", is_retry=True, feedback="语气不对")
    result = await node.run(ctx, AsyncMock())

    system_text = "\n\n".join(result.diff["system_parts"])
    assert "语气不对" in system_text
    assert "重试指示" in system_text


@pytest.mark.asyncio
async def test_no_retry_no_feedback():
    from animate.core.agent.nodes.system_prompt import SystemPromptNode
    node = SystemPromptNode(persona="你是祥子")
    ctx = RunContext(user_input="你好")
    result = await node.run(ctx, AsyncMock())

    for part in result.diff["system_parts"]:
        assert "重试指示" not in part
        assert "反馈" not in part
