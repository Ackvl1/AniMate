"""Tests for ReflectNode returning diff (Phase 6.2)"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from anima.core.engine.context import RunContext
from anima.core.agent.nodes.reflect import ReflectNode


class TestReflectNodeDiff:
    """ReflectNode 应该返回 diff 而不是写 ctx"""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _make_node(self, level=0, feedback="good"):
        llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = f"<summary>{{\"level\": {level}, \"feedback\": \"{feedback}\"}}</summary>"
        mock_result.total_tokens = 100
        llm.chat.return_value = mock_result
        return ReflectNode(llm)

    def test_returns_diff_with_retry_fields(self):
        """level>=2 时返回 diff.is_retry=True"""
        node = self._make_node(level=3, feedback="needs work")
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.diff is not None
        assert result.diff["is_retry"] is True
        assert result.diff["feedback"] == "needs work"

    def test_does_not_write_ctx_directly(self):
        """不应该直接写 ctx"""
        node = self._make_node(level=3, feedback="bad")
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"

        self._run(node.run(ctx, AsyncMock()))

        assert ctx.is_retry is False
        assert ctx.feedback == ""

    def test_returns_next_node_react_for_level_2(self):
        """level=2 时 next_node=react"""
        node = self._make_node(level=2, feedback="reformat")
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.next_node == "react"

    def test_returns_next_node_before_for_level_4(self):
        """level=4 时 next_node=before"""
        node = self._make_node(level=4, feedback="rerag")
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.next_node == "before"

    def test_returns_next_node_none_for_level_0(self):
        """level=0 时 next_node=None"""
        node = self._make_node(level=0, feedback="")
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.next_node is None

    def test_increments_llm_call_count_in_diff(self):
        """llm_call_count 应该在 diff 中递增"""
        node = self._make_node(level=0)
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"
        ctx.llm_call_count = 5

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.diff["llm_call_count"] == 6

    def test_accumulates_usage_in_diff(self):
        """accumulated_usage 应该在 diff 中累加"""
        node = self._make_node(level=0)
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"
        ctx.accumulated_usage = 500

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.diff["accumulated_usage"] == 600

    def test_empty_text_returns_no_diff(self):
        """空 final_text 返回无 diff"""
        node = self._make_node()
        ctx = RunContext(user_input="hi")
        ctx.final_text = ""

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.diff is None

    def test_skip_returns_no_diff(self):
        """达到重试上限时跳过"""
        node = self._make_node(level=0)
        ctx = RunContext(user_input="hi")
        ctx.final_text = "hello"
        ctx.llm_call_count = 20  # >= MAX_LLM_CALL_LIMIT

        result = self._run(node.run(ctx, AsyncMock()))

        assert result.diff is None
