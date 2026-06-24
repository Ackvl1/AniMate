"""Tests for ReactNode (新引擎接口) — LLM 调用 + tool_calls 循环 + 事件发射"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from animate.core.engine.context import RunContext
from animate.core.engine.node import Node, NodeResult
from animate.core.agent.nodes.react import ReactNode
from animate.core.llm.models import LLMResult, ToolCall
from animate.core.tools.registry import ToolRegistry


class MockStreamLLM:
    """模拟 LLM，用 chat_stream 产生预配置的流式事件。"""
    def __init__(self):
        self.stream_events = []  # list of list[dict]
        self.call_count = 0

    def chat(self, messages, tools=None):
        raise NotImplementedError("应该用 chat_stream")

    def chat_stream(self, messages, tools=None):
        events = self.stream_events[self.call_count] if self.call_count < len(self.stream_events) else [{"type": "done"}]
        self.call_count += 1
        for e in events:
            yield e


@pytest.mark.asyncio
async def test_is_node_subclass():
    node = ReactNode(llm=MagicMock(), tools=ToolRegistry())
    assert isinstance(node, Node)


@pytest.mark.asyncio
async def test_direct_reply_returns_after():
    """LLM 直接回复时 next_node='after'。"""
    llm = MockStreamLLM()
    llm.stream_events = [
        [{"type": "delta", "content": "本小姐知道了"}, {"type": "done"}],
    ]
    node = ReactNode(llm=llm, tools=ToolRegistry())
    ctx = RunContext(user_input="你好")
    ctx.messages = [{"role": "system", "content": "你是祥子"}, {"role": "user", "content": "你好"}]
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "after"
    assert ctx.raw_text == "本小姐知道了"


@pytest.mark.asyncio
async def test_tool_call_then_reply():
    """先调工具后回复。"""
    llm = MockStreamLLM()
    llm.stream_events = [
        [{"type": "tool_call", "index": 0, "id": "c1", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
        [{"type": "delta", "content": "现在是12:00"}, {"type": "done"}],
    ]
    tools = ToolRegistry()
    tools.register("get_time", "获取当前时间", handler=lambda: "12:00")
    node = ReactNode(llm=llm, tools=tools)
    ctx = RunContext(user_input="几点了")
    ctx.messages = [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "几点了"}]
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "after"
    assert ctx.raw_text == "现在是12:00"
    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_emits_text_token_events():
    """ReactNode 发射 text_token（inline marker 方案，纯文本流式）。"""
    llm = MockStreamLLM()
    llm.stream_events = [
        [{"type": "delta", "content": "本"}, {"type": "delta", "content": "小"}, {"type": "delta", "content": "姐"}, {"type": "done"}],
    ]
    events = []

    async def emit(type, **data):
        events.append((type, data))

    node = ReactNode(llm=llm, tools=ToolRegistry())
    ctx = RunContext(user_input="hi")
    ctx.messages = [{"role": "system", "content": "角色"}, {"role": "user", "content": "hi"}]
    await node.run(ctx, emit)

    text_tokens = [e for e in events if e[0] == "text_token"]
    assert len(text_tokens) > 0, "ReactNode 应发射 text_token（inline marker 方案）"
    combined = "".join(e[1].get("text", "") for e in text_tokens)
    assert combined == "本小姐"


@pytest.mark.asyncio
async def test_emits_tool_events():
    """工具调用应发射 tool.start 和 tool.done 事件。"""
    llm = MockStreamLLM()
    llm.stream_events = [
        [{"type": "tool_call", "index": 0, "id": "c1", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
        [{"type": "delta", "content": "done"}, {"type": "done"}],
    ]
    events = []

    async def emit(type, **data):
        events.append((type, data))

    tools = ToolRegistry()
    tools.register("get_time", "时间", handler=lambda: "12:00")
    node = ReactNode(llm=llm, tools=tools)
    ctx = RunContext(user_input="几点了")
    ctx.messages = [{"role": "system", "content": "助手"}, {"role": "user", "content": "几点了"}]
    await node.run(ctx, emit)

    starts = [e for e in events if e[0] == "tool.start"]
    dones = [e for e in events if e[0] == "tool.done"]
    assert len(starts) == 1
    assert len(dones) == 1


@pytest.mark.asyncio
async def test_max_rounds_limit():
    """工具调用超出上限后强制返回。"""
    llm = MockStreamLLM()
    # 一直返回 tool_calls
    llm.stream_events = [
        [{"type": "tool_call", "index": 0, "id": f"c{i}", "name": "loop", "arguments": "{}"}, {"type": "done"}]
        for i in range(15)
    ]
    tools = ToolRegistry()
    tools.register("loop", "循环", handler=lambda: "done")
    node = ReactNode(llm=llm, tools=tools)
    ctx = RunContext(user_input="loop")
    ctx.messages = [{"role": "system", "content": "助手"}, {"role": "user", "content": "loop"}]
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "after"
