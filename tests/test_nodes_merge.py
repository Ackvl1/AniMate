"""Tests for MergeNode — 去重合并 + 组装 system prompt + memory + user input"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from anima.core.engine.context import RunContext
from anima.core.engine.node import Node, NodeResult


@pytest.mark.asyncio
async def test_is_node_subclass():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    assert isinstance(node, Node)


@pytest.mark.asyncio
async def test_returns_react_next_node():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="你好")
    ctx.extras["rag_vector_chunks"] = []
    ctx.extras["rag_keyword_chunks"] = []
    ctx.extras["system_parts"] = ["你是祥子", "指令"]
    result = await node.run(ctx, AsyncMock())
    assert result.next_node is None  # direct 边由引擎处理


@pytest.mark.asyncio
async def test_merges_vector_and_keyword_chunks():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="你好")
    ctx.extras["rag_vector_chunks"] = ["v1", "v2"]
    ctx.extras["rag_keyword_chunks"] = ["k1", "k2"]
    ctx.extras["system_parts"] = ["你是祥子", "指令"]
    result = await node.run(ctx, AsyncMock())

    system_text = result.diff["messages"][0]["content"]
    assert "v1" in system_text
    assert "v2" in system_text
    assert "k1" in system_text
    assert "k2" in system_text


@pytest.mark.asyncio
async def test_dedups_chunks():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="你好")
    ctx.extras["rag_vector_chunks"] = ["same", "unique_vec"]
    ctx.extras["rag_keyword_chunks"] = ["same", "unique_kw"]
    ctx.extras["system_parts"] = ["你是祥子", "指令"]
    result = await node.run(ctx, AsyncMock())

    system_text = result.diff["messages"][0]["content"]
    assert system_text.count("same") == 1  # 去重
    assert "unique_vec" in system_text
    assert "unique_kw" in system_text


@pytest.mark.asyncio
async def test_no_chunks_omits_rag_section():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="你好")
    ctx.extras["rag_vector_chunks"] = []
    ctx.extras["rag_keyword_chunks"] = []
    ctx.extras["system_parts"] = ["你是祥子", "指令"]
    result = await node.run(ctx, AsyncMock())

    system_text = result.diff["messages"][0]["content"]
    assert "相关知识" not in system_text
    assert "你是祥子" in system_text


@pytest.mark.asyncio
async def test_injects_memory_history():
    """MergeNode 不丢失已有的历史消息（新架构：Agent 在 engine.run 前已注入历史 + user_input）。"""
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="你好")
    # 新架构：Agent 在 engine.run 前已把历史 + user_input 注入 ctx.messages
    ctx.messages = [
        {"role": "user", "content": "上轮问题"},
        {"role": "assistant", "content": "上轮回答"},
        {"role": "user", "content": "你好"},  # agent.py 注入
    ]
    ctx.extras["rag_vector_chunks"] = []
    ctx.extras["rag_keyword_chunks"] = []
    ctx.extras["system_parts"] = ["你是祥子"]
    result = await node.run(ctx, AsyncMock())

    roles = [m["role"] for m in result.diff["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_injects_user_input():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="今天天气真好")
    ctx.extras["rag_vector_chunks"] = []
    ctx.extras["rag_keyword_chunks"] = []
    ctx.extras["system_parts"] = ["你是祥子"]
    result = await node.run(ctx, AsyncMock())

    assert result.diff["messages"][-1]["role"] == "user"
    assert result.diff["messages"][-1]["content"] == "今天天气真好"


@pytest.mark.asyncio
async def test_emits_node_start():
    from anima.core.agent.nodes.merge import MergeNode
    node = MergeNode()
    ctx = RunContext(user_input="你好")
    ctx.extras["rag_vector_chunks"] = []
    ctx.extras["rag_keyword_chunks"] = []
    ctx.extras["system_parts"] = ["你是祥子"]
    emit = AsyncMock()
    await node.run(ctx, emit)
    # MergeNode emit node.start + node.done
    assert emit.await_count >= 2
    call_names = [c.args[0] if c.args else "" for c in emit.await_args_list]
    assert "node.start" in call_names or any("node.start" == c[0][0] for c in emit.call_args_list)
