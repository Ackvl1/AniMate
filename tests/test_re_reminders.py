"""Tests for System Re-Reminders — 多轮 tool call 后角色保持 (RED - should fail first)"""
import pytest
from unittest.mock import AsyncMock

from animate.core.engine.context import RunContext
from animate.core.agent.nodes.react import ReactNode
from animate.core.llm.models import LLMResult, ToolCall
from animate.core.tools.registry import ToolRegistry


class MockStreamLLM:
    def __init__(self):
        self.stream_events = []
        self.call_count = 0

    def chat(self, messages, tools=None):
        raise NotImplementedError

    def chat_stream(self, messages, tools=None):
        events = self.stream_events[self.call_count] if self.call_count < len(self.stream_events) else [{"type": "done"}]
        self.call_count += 1
        for e in events:
            yield e


class TestReReminders:
    @pytest.mark.asyncio
    async def test_tool_call_appends_reminder(self):
        """工具调用后应追加 system-reminder 提醒消息"""
        llm = MockStreamLLM()
        llm.stream_events = [
            [{"type": "tool_call", "index": 0, "id": "c1", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
            [{"type": "delta", "content": "现在是12点"}, {"type": "done"}],
        ]
        tools = ToolRegistry()
        tools.register("get_time", "获取时间", handler=lambda: "12:00")
        node = ReactNode(llm=llm, tools=tools)
        ctx = RunContext(user_input="几点了")
        ctx.messages = [
            {"role": "system", "content": "你是丰川祥子"},
            {"role": "user", "content": "几点了"},
        ]
        # 执行 node.run（内部会走 _handle_tool_calls）
        result = await node.run(ctx, AsyncMock())

        # 验证 messages 中包含了 system-reminder
        reminders = [m for m in result.diff["messages"] if "system-reminder" in str(m.get("content", ""))]
        assert len(reminders) >= 1, f"工具调用后 messages 应包含 system-reminder"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_each_add_reminder(self):
        """多次工具调用每次都应追加 reminder"""
        llm = MockStreamLLM()
        # 3 轮 tool_call + 1 轮回复
        llm.stream_events = [
            [{"type": "tool_call", "index": 0, "id": "c1", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
            [{"type": "tool_call", "index": 0, "id": "c2", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
            [{"type": "tool_call", "index": 0, "id": "c3", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
            [{"type": "delta", "content": "done"}, {"type": "done"}],
        ]
        tools = ToolRegistry()
        tools.register("get_time", "时间", handler=lambda: "12:00")
        node = ReactNode(llm=llm, tools=tools)
        ctx = RunContext(user_input="多轮")
        ctx.messages = [
            {"role": "system", "content": "你是角色"},
            {"role": "user", "content": "多轮"},
        ]
        result = await node.run(ctx, AsyncMock())

        reminders = [m for m in result.diff["messages"] if "system-reminder" in str(m.get("content", ""))]
        assert len(reminders) >= 3, f"3轮工具调用应有至少3个reminder, 实际{len(reminders)}"

    @pytest.mark.asyncio
    async def test_no_tool_call_no_reminder(self):
        """直接回复不应追加 reminder"""
        llm = MockStreamLLM()
        llm.stream_events = [
            [{"type": "delta", "content": "直接回复"}, {"type": "done"}],
        ]
        node = ReactNode(llm=llm, tools=ToolRegistry())
        ctx = RunContext(user_input="hi")
        ctx.messages = [
            {"role": "system", "content": "你是角色"},
            {"role": "user", "content": "hi"},
        ]
        result = await node.run(ctx, AsyncMock())

        reminders = [m for m in result.diff["messages"] if "system-reminder" in str(m.get("content", ""))]
        assert len(reminders) == 0, "直接回复不应有 reminder"

    @pytest.mark.asyncio
    async def test_reminder_content_dynamic(self):
        """reminder 内容应包含角色设定指示"""
        llm = MockStreamLLM()
        llm.stream_events = [
            [{"type": "tool_call", "index": 0, "id": "c1", "name": "get_time", "arguments": "{}"}, {"type": "done"}],
            [{"type": "delta", "content": "回复"}, {"type": "done"}],
        ]
        tools = ToolRegistry()
        tools.register("get_time", "时间", handler=lambda: "12:00")
        node = ReactNode(llm=llm, tools=tools)
        ctx = RunContext(user_input="hi")
        ctx.messages = [
            {"role": "system", "content": "你是角色A"},
            {"role": "user", "content": "hi"},
        ]
        result = await node.run(ctx, AsyncMock())

        reminders = [m["content"] for m in result.diff["messages"] if m.get("role") == "system" and "system-reminder" in m.get("content", "")]
        assert len(reminders) >= 1
        reminder = reminders[0]
        assert "角色" in reminder or "扮演" in reminder, f"reminder 应包含角色指示: {reminder}"
        assert "保持" in reminder or "扮演" in reminder or "角色设定" in reminder, \
            f"reminder 应包含保持角色设定语义: {reminder}"
