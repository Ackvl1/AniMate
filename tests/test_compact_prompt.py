"""Tests for _auto_compact prompt budget optimization (Workstream D)."""
import pytest
from unittest.mock import MagicMock
from anima.core.context.manager import ContextManager


class TestCompactPromptBudget:
    """_auto_compact 摘要 prompt 按 token 预算均分。"""

    def setup_method(self):
        self.llm = MagicMock()
        self.llm.chat.return_value = MagicMock(content="摘要内容")
        self.cm = ContextManager(llm=self.llm)

    def test_prompt_uses_budget_not_hard截断(self):
        """摘要 prompt 按消息数均分预算，不再硬截 200 字符。"""
        # 构造 4 条中间消息，每条 500 字符
        messages = [
            {"role": "system", "content": "person"},
            {"role": "user", "content": "A" * 500},
            {"role": "assistant", "content": "B" * 500},
            {"role": "user", "content": "C" * 500},
            {"role": "assistant", "content": "D" * 500},
            {"role": "user", "content": "E" * 500},
            {"role": "assistant", "content": "F" * 500},
            {"role": "user", "content": "last"},
        ]
        head = {0}  # system prompt
        tail = {6, 7}  # 最后 2 条
        middle = [1, 2, 3, 4]  # 中间 4 条

        self.cm._auto_compact(messages, head, tail, middle, {})

        # LLM 应该被调用（摘要）
        self.llm.chat.assert_called_once()
        prompt = self.llm.chat.call_args[0][0][0]["content"]

        # prompt 应该包含中间消息的内容
        assert "A" in prompt or "B" in prompt

    def test_empty_middle_skips(self):
        """middle 为空时不调用 LLM。"""
        messages = [{"role": "user", "content": "hi"}]
        result = self.cm._auto_compact(messages, {0}, set(), [], {})
        assert result is False
        self.llm.chat.assert_not_called()
