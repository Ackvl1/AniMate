"""Tests for B10/B11/B12 fixes — retry dedup, feedback dedup, async compress."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from animate.core.engine.context import RunContext


# ══════════════════════════════════════════════════════════════
# B10: user_input 不重复追加
# ══════════════════════════════════════════════════════════════


class TestB10NoDuplicateUserInput:
    """MergeNode 不应重复追加 user_input。"""

    @pytest.mark.asyncio
    async def test_merge_does_not_duplicate_when_user_at_end(self):
        """agent.py 已注入 user_input 时，MergeNode 不再追加。"""
        from animate.core.agent.nodes.merge import MergeNode
        node = MergeNode()
        ctx = RunContext(user_input="你好")
        ctx.messages = [
            {"role": "system", "content": "旧系统提示"},
            {"role": "user", "content": "你好"},  # agent.py 已注入
        ]
        ctx.extras["rag_vector_chunks"] = []
        ctx.extras["rag_keyword_chunks"] = []
        ctx.extras["system_parts"] = ["你是祥子"]

        await node.run(ctx, AsyncMock())

        # user 只出现一次
        user_msgs = [m for m in ctx.messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_merge_adds_user_when_none_present(self):
        """极端回退：ctx.messages 没有 user 时，MergeNode 补入。"""
        from animate.core.agent.nodes.merge import MergeNode
        node = MergeNode()
        ctx = RunContext(user_input="你好")
        ctx.messages = []  # 空，无 user
        ctx.extras["rag_vector_chunks"] = []
        ctx.extras["rag_keyword_chunks"] = []
        ctx.extras["system_parts"] = ["你是祥子"]

        await node.run(ctx, AsyncMock())

        user_msgs = [m for m in ctx.messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_retry_path_no_duplicate(self):
        """模拟 'before' retry 路径：agent.py 注入 + merge 不重复。"""
        from animate.core.agent.nodes.merge import MergeNode
        node = MergeNode()
        ctx = RunContext(user_input="你好")
        # retry 时 ctx.messages 包含历史 + user_input（来自 agent.py）
        ctx.messages = [
            {"role": "system", "content": "角色人设"},
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
            {"role": "user", "content": "你好"},  # agent.py 注入
        ]
        ctx.extras["rag_vector_chunks"] = []
        ctx.extras["rag_keyword_chunks"] = []
        ctx.extras["system_parts"] = ["你是祥子"]

        await node.run(ctx, AsyncMock())

        # user 只出现两次（之前的问题 + 你好），不应有第三个
        user_msgs = [m for m in ctx.messages if m["role"] == "user"]
        assert len(user_msgs) == 2
        assert user_msgs[1]["content"] == "你好"


# ══════════════════════════════════════════════════════════════
# B11: retry feedback 不双重注入
# ══════════════════════════════════════════════════════════════


class TestB11NoDoubleFeedback:
    """ReactNode 不应在 SystemPromptNode 已注入 feedback 时重复注入。"""

    @pytest.mark.asyncio
    async def test_react_skips_feedback_when_marker_set(self):
        """level 4 路径：SystemPromptNode 已设标记，ReactNode 跳过。"""
        from animate.core.agent.nodes.react import ReactNode

        fake_llm = MagicMock()
        fake_tools = MagicMock()
        fake_tools.names = []
        node = ReactNode(fake_llm, fake_tools)

        ctx = RunContext(user_input="你好")
        ctx.messages = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "你好"},
        ]
        ctx.is_retry = True
        ctx.feedback = "语气不够温柔"
        ctx.extras["retry_feedback_injected"] = True  # SystemPromptNode 已设标记

        # 模拟 LLM 返回纯文本（无 tool calls）
        from animate.core.llm.models import LLMResult
        fake_llm.chat_stream_async = AsyncMock()
        fake_llm.chat_stream = MagicMock(return_value=iter([
            {"type": "delta", "content": "你好呀～"},
            {"type": "done"},
        ]))
        fake_llm.chat.return_value = LLMResult(content="你好呀～", tool_calls=None)

        with patch.object(node, '_stream_round', new_callable=AsyncMock) as mock_stream:
            mock_stream.return_value = LLMResult(content="你好呀～", tool_calls=None)
            await node.run(ctx, AsyncMock())

        # messages 中不应有单独的 feedback system 消息
        feedback_msgs = [m for m in ctx.messages
                         if m.get("role") == "system"
                         and "重试指示" in m.get("content", "")]
        assert len(feedback_msgs) == 0

    @pytest.mark.asyncio
    async def test_react_injects_feedback_when_no_marker(self):
        """level 2-3 路径：SystemPromptNode 没跑，ReactNode 注入 feedback。"""
        from animate.core.agent.nodes.react import ReactNode
        from animate.core.llm.models import LLMResult

        fake_llm = MagicMock()
        fake_tools = MagicMock()
        fake_tools.names = []
        node = ReactNode(fake_llm, fake_tools)

        ctx = RunContext(user_input="你好")
        ctx.messages = [
            {"role": "system", "content": "人设"},
            {"role": "user", "content": "你好"},
        ]
        ctx.is_retry = True
        ctx.feedback = "语气不够温柔"
        # ctx.extras 中没有 retry_feedback_injected 标记

        with patch.object(node, '_stream_round', new_callable=AsyncMock) as mock_stream:
            mock_stream.return_value = LLMResult(content="你好呀～", tool_calls=None)
            await node.run(ctx, AsyncMock())

        # messages 末尾应有 feedback system 消息
        feedback_msgs = [m for m in ctx.messages
                         if m.get("role") == "system"
                         and "重试指示" in m.get("content", "")]
        assert len(feedback_msgs) == 1
        assert "语气不够温柔" in feedback_msgs[0]["content"]


# ══════════════════════════════════════════════════════════════
# B11 补充：reflect.py 路由时清标记
# ══════════════════════════════════════════════════════════════


class TestB11MarkerClearing:
    """ReflectNode 在 level 2-3 retry 时清除残留标记。"""

    @pytest.mark.asyncio
    async def test_reflect_clears_marker_on_react_routing(self):
        """level 2-3 retry 时标记被清除。"""
        from animate.core.agent.nodes.reflect import ReflectNode

        fake_llm = MagicMock()
        node = ReflectNode(fake_llm)

        ctx = RunContext(user_input="你好")
        ctx.final_text = "测试回复"
        ctx.llm_call_count = 0
        ctx.is_retry = False
        # 模拟残留标记（来自之前的 level 4 retry）
        ctx.extras["retry_feedback_injected"] = True

        # LLM 返回 level 2（需重生成）
        from animate.core.llm.models import LLMResult
        fake_llm.chat.return_value = LLMResult(
            content="<analysis>测试</analysis>\n<summary>{\"level\": 2, \"feedback\": \"改进\"}</summary>",
            tool_calls=None
        )

        result = await node.run(ctx, AsyncMock())

        assert result.next_node == "react"
        assert ctx.extras.get("retry_feedback_injected") is None  # 标记已清除

    @pytest.mark.asyncio
    async def test_reflect_preserves_marker_on_before_routing(self):
        """level 4 retry 路由 'before' 时，标记不被清除（由 SystemPromptNode 负责）。"""
        from animate.core.agent.nodes.reflect import ReflectNode

        fake_llm = MagicMock()
        node = ReflectNode(fake_llm)

        ctx = RunContext(user_input="你好")
        ctx.final_text = "测试回复"
        ctx.llm_call_count = 0
        ctx.is_retry = False
        ctx.extras["retry_feedback_injected"] = True  # 已有标记

        from animate.core.llm.models import LLMResult
        fake_llm.chat.return_value = LLMResult(
            content="<analysis>测试</analysis>\n<summary>{\"level\": 4, \"feedback\": \"需要重检索\"}</summary>",
            tool_calls=None
        )

        result = await node.run(ctx, AsyncMock())

        assert result.next_node == "before"
        # level 4 路由不主动清标记（SystemPromptNode 会在重跑时重新设标记）
        # 此处保持 True，不影响正确性——SystemPromptNode 会再次设标记
        assert ctx.extras.get("retry_feedback_injected") is True


# ══════════════════════════════════════════════════════════════
# B12: chat_async 存在且可用
# ══════════════════════════════════════════════════════════════


class TestB12ChatAsync:
    """LLM client 具备 chat_async 方法，compress_async 可用。"""

    def test_client_has_chat_async(self):
        """OpenAICompatibleClient 定义了 chat_async 方法。"""
        from animate.core.llm.client import OpenAICompatibleClient
        assert hasattr(OpenAICompatibleClient, "chat_async")
        assert asyncio.iscoroutinefunction(OpenAICompatibleClient.chat_async)

    def test_context_manager_has_compress_async(self):
        """ContextManager 定义了 compress_async 方法。"""
        from animate.core.context.manager import ContextManager
        cm = ContextManager(model_limit=100_000)
        assert hasattr(cm, "compress_async")
        assert asyncio.iscoroutinefunction(cm.compress_async)

    @pytest.mark.asyncio
    async def test_compress_async_calls_chat_async(self):
        """compress_async 的 LLM 摘要使用 chat_async 而非同步 chat。"""
        from animate.core.context.manager import ContextManager
        from animate.core.llm.models import LLMResult

        fake_llm = MagicMock()
        fake_llm.chat_async = AsyncMock(return_value=LLMResult(content="摘要内容", tool_calls=None))

        cm = ContextManager(
            model_limit=100_000,
            head_rounds=2,
            tail_rounds=2,
            llm=fake_llm,
        )

        messages = [
            {"role": "user", "content": "消息1"},
            {"role": "assistant", "content": "回复1"},
            {"role": "user", "content": "消息2"},
            {"role": "assistant", "content": "回复2"},
            {"role": "user", "content": "消息3"},
            {"role": "assistant", "content": "回复3"},
            {"role": "user", "content": "消息4"},
            {"role": "assistant", "content": "回复4"},
            {"role": "user", "content": "消息5"},
            {"role": "assistant", "content": "回复5"},
            {"role": "user", "content": "消息6"},
            {"role": "assistant", "content": "回复6"},
            {"role": "user", "content": "消息7"},
            {"role": "assistant", "content": "回复7"},
            {"role": "user", "content": "消息8"},
            {"role": "assistant", "content": "回复8"},
        ]

        # 手动触发压缩（超过阈值）
        cm._accumulated = 200_000
        result = await cm.compress_async(messages)

        # 应调用 chat_async 而非同步 chat
        fake_llm.chat_async.assert_called_once()
        fake_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_compress_async_returns_none_when_too_few_messages(self):
        """消息过少时 compress_async 返回 None。"""
        from animate.core.context.manager import ContextManager

        cm = ContextManager(model_limit=100_000, head_rounds=2, tail_rounds=2)
        messages = [{"role": "user", "content": "hi"}]
        result = await cm.compress_async(messages)
        assert result is None


# ══════════════════════════════════════════════════════════════
# B7 补充：stream_options 不再传 None
# ══════════════════════════════════════════════════════════════


class TestB7StreamOptions:
    """非流式调用不传 stream_options。"""

    def test_sync_chat_kwargs_no_stream_options(self):
        """chat() 构建的 kwargs 不含 stream_options。"""
        from animate.core.llm.client import OpenAICompatibleClient

        cfg = MagicMock()
        cfg.default_model = "test"
        cfg.default_temperature = 0.7
        cfg.default_max_tokens = 4096
        cfg.api_key = "fake"
        cfg.base_url = "http://fake"
        cfg.extra_headers = None

        client = OpenAICompatibleClient(provider="deepseek")
        client._provider_config = cfg
        client._model = "test"

        kwargs = client._build_kwargs(
            [{"role": "user", "content": "hi"}], tools=None, stream=False
        )
        assert "stream_options" not in kwargs

    def test_stream_chat_kwargs_has_stream_options(self):
        """chat_stream() 构建的 kwargs 包含 stream_options。"""
        from animate.core.llm.client import OpenAICompatibleClient

        cfg = MagicMock()
        cfg.default_model = "test"
        cfg.default_temperature = 0.7
        cfg.default_max_tokens = 4096
        cfg.api_key = "fake"
        cfg.base_url = "http://fake"
        cfg.extra_headers = None

        client = OpenAICompatibleClient(provider="deepseek")
        client._provider_config = cfg
        client._model = "test"

        kwargs = client._build_kwargs(
            [{"role": "user", "content": "hi"}], tools=None, stream=True
        )
        assert kwargs.get("stream_options") == {"include_usage": True}
