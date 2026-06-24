"""Tests for HITL integration in ReactNode — tool denial flow"""
import pytest
from unittest.mock import AsyncMock

from animate.core.engine.context import RunContext
from animate.core.agent.nodes.react import ReactNode
from animate.core.llm.models import LLMResult, ToolCall
from animate.core.tools.registry import ToolRegistry
from animate.core.tools.base import LocalTool
from animate.core.agent import PermissionManager


class DeniedTool(LocalTool):
    name = "denied_tool"
    description = "会被拒绝的工具"
    is_read_only = False
    is_parallel_safe = False
    is_destructive = True
    def execute(self, **kwargs) -> str:
        return "should not be reached"


class MockStreamLLM:
    def __init__(self):
        self.call_count = 0
    def chat(self, messages, tools=None):
        raise NotImplementedError
    def chat_stream(self, messages, tools=None):
        self.call_count += 1
        return iter([])  # empty stream = no delta, no tool_call


@pytest.mark.asyncio
async def test_tool_denied_with_permission_manager():
    """permission_manager 拒绝工具时：
       1. 不执行工具
       2. 注入"用户取消了操作"到 messages
       3. emit tool.denied 事件
    """
    events = []
    async def emit(type, **data):
        events.append((type, data))

    async def deny_all(name, args):
        return False

    pm = PermissionManager(callback=deny_all)
    llm = MockStreamLLM()
    # 让 _stream_round 直接返回一个包含 tool_call 的结果
    # 用 MagicMock 替代实际的流式调用

    tools = ToolRegistry()
    tools.register_tool(DeniedTool())

    node = ReactNode(llm=llm, tools=tools, permission_manager=pm)

    # 直接测试 _handle_tool_calls 的逻辑
    # 构造一个 LLMResult 包含 tool_call
    result = LLMResult(
        content="要执行工具了",
        tool_calls=[ToolCall(id="c1", name="denied_tool", arguments={})],
    )
    messages = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "执行工具"},
    ]
    ctx = RunContext(user_input="执行工具")

    await node._handle_tool_calls(result, messages, ctx, 1, emit)

    # 1. 不执行工具 — 没有 assistant 消息确认？（其实有，在 append 之后）
    # 验证有 tool 消息但内容是"用户取消了操作"
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1, "应有 tool 消息"
    assert "用户取消了操作" in tool_msgs[0]["content"], "应注入取消消息"

    # 2. 验证 emit 了 tool.denied
    denied_events = [e for e in events if e[0] == "tool.denied"]
    assert len(denied_events) >= 1, "应 emit tool.denied"


@pytest.mark.asyncio
async def test_tool_approved_with_permission_manager():
    """permission_manager 批准时正常执行工具。"""
    events = []
    async def emit(type, **data):
        events.append((type, data))

    async def approve_all(name, args):
        return True

    pm = PermissionManager(callback=approve_all)
    tools = ToolRegistry()
    tools.register_tool(DeniedTool())  # is_read_only=False
    node = ReactNode(llm=MockStreamLLM(), tools=tools, permission_manager=pm)

    result = LLMResult(
        content="执行",
        tool_calls=[ToolCall(id="c1", name="denied_tool", arguments={})],
    )
    messages = [{"role": "system", "content": "助手"}, {"role": "user", "content": "hi"}]
    ctx = RunContext(user_input="hi")

    await node._handle_tool_calls(result, messages, ctx, 1, emit)

    # 验证有 tool 消息且内容不是"用户取消了操作"
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "should not be reached"  # DeniedTool.execute 返回值


@pytest.mark.asyncio
async def test_no_permission_manager_still_works():
    """不设 permission_manager 时正常执行。"""
    events = []
    async def emit(type, **data):
        events.append((type, data))

    tools = ToolRegistry()
    tools.register_tool(DeniedTool())
    node = ReactNode(llm=MockStreamLLM(), tools=tools)  # 没有 permission_manager

    result = LLMResult(
        content="执行",
        tool_calls=[ToolCall(id="c1", name="denied_tool", arguments={})],
    )
    messages = [{"role": "system", "content": "助手"}, {"role": "user", "content": "hi"}]
    ctx = RunContext(user_input="hi")

    await node._handle_tool_calls(result, messages, ctx, 1, emit)

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "should not be reached"
