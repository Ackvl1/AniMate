"""Phase 6.2 — ReactNode Return-Diff 专项测试（方案 A）"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────

async def _noop_async_emit(type, **data):
    """No-op async emit for tests."""
    pass


def _make_ctx(user_input="你好", messages=None):
    """构造最小 RunContext 用于测试。"""
    from animate.core.engine.context import RunContext
    ctx = RunContext(user_input=user_input)
    if messages:
        ctx.messages = list(messages)
    else:
        ctx.messages = [{"role": "user", "content": user_input}]
    return ctx


def _make_react_node(llm=None, tools=None, permission_manager=None):
    """构造 ReactNode 实例。"""
    from animate.core.agent.nodes.react import ReactNode
    if llm is None:
        llm = MagicMock()
    if tools is None:
        tools = MagicMock()
        tools.names = []
        tools.list_schemas.return_value = []
    return ReactNode(llm, tools, permission_manager=permission_manager)


# ── 红测①：ReactNode 返回 6 字段 diff ──────────────────────────

class TestReactReturnsSixFieldDiff:
    """ReactNode run() 结束后返回的 diff 含全部 6 字段。"""

    @pytest.mark.asyncio
    async def test_diff_has_six_fields(self):
        """diff 包含 messages, raw_text, emotion, gesture, llm_call_count, accumulated_usage。"""
        from animate.core.engine.node import NodeResult

        llm = MagicMock()
        # mock chat_stream 返回一个简单文本（无 tool_call）
        async def mock_stream(messages, tools=None):
            yield {"type": "delta", "content": "你好"}
            yield {"type": "done"}

        llm.chat_stream = mock_stream
        llm.chat_stream_async = mock_stream

        tools = MagicMock()
        tools.names = []
        tools.list_schemas.return_value = []

        node = _make_react_node(llm=llm, tools=tools)
        ctx = _make_ctx()
        events = []

        async def emit(type, **data):
            events.append((type, data))

        result = await node.run(ctx, _noop_async_emit)
        assert isinstance(result, NodeResult)
        assert result.diff is not None
        expected_keys = {"messages", "raw_text", "emotion", "gesture",
                         "llm_call_count", "accumulated_usage"}
        assert set(result.diff.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_diff_messages_is_list(self):
        """diff.messages 是完整消息列表。"""
        llm = MagicMock()
        async def mock_stream(messages, tools=None):
            yield {"type": "delta", "content": "测试"}
            yield {"type": "done"}

        llm.chat_stream = mock_stream
        llm.chat_stream_async = mock_stream

        tools = MagicMock()
        tools.names = []
        tools.list_schemas.return_value = []

        node = _make_react_node(llm=llm, tools=tools)
        ctx = _make_ctx()
        result = await node.run(ctx, _noop_async_emit)

        assert isinstance(result.diff["messages"], list)
        assert len(result.diff["messages"]) > 0

    @pytest.mark.asyncio
    async def test_diff_raw_text_matches_stream(self):
        """diff.raw_text 是流式累积的纯文本。"""
        llm = MagicMock()
        async def mock_stream(messages, tools=None):
            yield {"type": "delta", "content": "你"}
            yield {"type": "delta", "content": "好"}
            yield {"type": "done"}

        llm.chat_stream = mock_stream
        llm.chat_stream_async = mock_stream

        tools = MagicMock()
        tools.names = []
        tools.list_schemas.return_value = []

        node = _make_react_node(llm=llm, tools=tools)
        ctx = _make_ctx()
        result = await node.run(ctx, _noop_async_emit)

        assert "你好" in result.diff["raw_text"]


# ── 红测②：ReactNode 不带 next_node ────────────────────────────

class TestReactNoNextNode:
    """ReactNode 返回的 NodeResult.next_node 为 None（direct 边由引擎处理）。"""

    @pytest.mark.asyncio
    async def test_next_node_is_none(self):
        llm = MagicMock()
        async def mock_stream(messages, tools=None):
            yield {"type": "delta", "content": "ok"}
            yield {"type": "done"}

        llm.chat_stream = mock_stream
        llm.chat_stream_async = mock_stream

        tools = MagicMock()
        tools.names = []
        tools.list_schemas.return_value = []

        node = _make_react_node(llm=llm, tools=tools)
        ctx = _make_ctx()
        result = await node.run(ctx, _noop_async_emit)

        assert result.next_node is None

    @pytest.mark.asyncio
    async def test_next_node_none_on_max_rounds(self):
        """达到最大轮数时 next_node 也为 None。"""
        llm = MagicMock()
        round_count = 0

        async def mock_stream(messages, tools=None):
            nonlocal round_count
            round_count += 1
            # 每轮都返回 tool_call，触发下一轮
            yield {"type": "tool_call", "index": 0, "id": "c1", "name": "test", "arguments": "{}"}
            yield {"type": "done"}

        llm.chat_stream = mock_stream
        llm.chat_stream_async = mock_stream

        tools = MagicMock()
        tools.names = ["test"]
        tools.list_schemas.return_value = [{"type": "function", "function": {"name": "test"}}]
        tools.find.return_value = MagicMock(is_read_only=True, is_parallel_safe=True)
        tools.execute.return_value = "result"

        node = _make_react_node(llm=llm, tools=tools)
        node.MAX_ROUNDS = 2  # 限制轮数
        ctx = _make_ctx()
        result = await node.run(ctx, _noop_async_emit)

        assert result.next_node is None
