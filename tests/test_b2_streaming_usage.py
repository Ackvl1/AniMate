"""Tests for B2 fix — streaming token fallback via tiktoken."""

from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

from animate.core.engine.context import RunContext
from animate.core.llm.models import LLMResult


def _make_llm_mock(stream_events):
    """创建一个只有 chat_stream 的 LLM mock（无 chat_stream_async 干扰）。"""
    m = MagicMock(spec=[])  # 空 spec → 不自动响应任何 attribute
    # 手动添加需要的属性
    m.chat_stream = MagicMock(return_value=iter(stream_events))
    return m


class TestB2StreamingTokenFallback:
    """验证 DeepSeek 不返回 usage 时，tiktoken 后备计数生效。"""

    @pytest.mark.asyncio
    async def test_accumulates_usage_when_stream_provides_usage(self):
        """OpenAI 风格：流式有 usage 块 → 直接累加，不调 tiktoken。"""
        from animate.core.agent.nodes.react import ReactNode

        fake_llm = _make_llm_mock([
            {"type": "delta", "content": "hello"},
            {"type": "usage", "total_tokens": 50},
            {"type": "done"},
        ])
        fake_tools = MagicMock(spec=["names"])
        fake_tools.names = []

        node = ReactNode(fake_llm, fake_tools)
        ctx = RunContext(user_input="hi")
        ctx.messages = [{"role": "user", "content": "hi"}]

        with patch.object(node, '_build_tool_calls', return_value=None):
            with patch("animate.core.agent.nodes.react.estimate_tokens",
                       return_value=0) as mock_est:
                result = await node._stream_round(
                    list(ctx.messages), None, ctx, 1, AsyncMock()
                )

        assert ctx.accumulated_usage == 50  # 从 usage 事件累加
        mock_est.assert_not_called()  # 后备未触发

    @pytest.mark.asyncio
    async def test_falls_back_to_tiktoken_when_no_usage(self):
        """DeepSeek 风格：流式无 usage 块 → 调 estimate_tokens 后备。"""
        from animate.core.agent.nodes.react import ReactNode

        fake_llm = _make_llm_mock([
            {"type": "delta", "content": "hello"},
            {"type": "done"},
        ])
        fake_tools = MagicMock(spec=["names"])
        fake_tools.names = []

        node = ReactNode(fake_llm, fake_tools)
        ctx = RunContext(user_input="hi")
        ctx.messages = [{"role": "user", "content": "hi"}]
        ctx.accumulated_usage = 0

        with patch.object(node, '_build_tool_calls', return_value=None):
            with patch("animate.core.agent.nodes.react.estimate_tokens",
                       return_value=42) as mock_est:
                result = await node._stream_round(
                    list(ctx.messages), None, ctx, 1, AsyncMock()
                )

        mock_est.assert_called_once()
        assert ctx.accumulated_usage == 42  # 后备估值累加

    @pytest.mark.asyncio
    async def test_estimate_tokens_returns_reasonable_value(self):
        """estimate_tokens 返回合理的估算值。"""
        from animate.core.memory.conversation import estimate_tokens
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        tokens = estimate_tokens(msgs)
        assert tokens > 0
        assert tokens < 100

    @pytest.mark.asyncio
    async def test_only_fallback_once_per_round(self):
        """每个 stream_round 只后备一次，不重复累加。"""
        from animate.core.agent.nodes.react import ReactNode

        fake_llm = _make_llm_mock([
            {"type": "delta", "content": "hello"},
            {"type": "done"},
        ])
        fake_tools = MagicMock(spec=["names"])
        fake_tools.names = []

        node = ReactNode(fake_llm, fake_tools)
        ctx = RunContext(user_input="hi")
        ctx.messages = [{"role": "user", "content": "hi"}]
        ctx.accumulated_usage = 10  # 已有来自 ReflectNode 的累计

        with patch.object(node, '_build_tool_calls', return_value=None):
            with patch("animate.core.agent.nodes.react.estimate_tokens",
                       return_value=42) as mock_est:
                result = await node._stream_round(
                    list(ctx.messages), None, ctx, 1, AsyncMock()
                )

        mock_est.assert_called_once()
        assert ctx.accumulated_usage == 52  # 10 + 42
