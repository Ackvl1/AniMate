"""Tests for TokenCounter — 增量 token 计数器。"""

import pytest
from animate.core.context.token_counter import TokenCounter


class TestTokenCounter:
    """RED: 所有测试应先失败，因为 TokenCounter 还不存在。"""

    def test_empty_after_init(self):
        """初始化后 total 应为 0。"""
        counter = TokenCounter()
        assert counter.total == 0

    def test_add_single_message(self):
        """添加一条消息后 total 应为正数。"""
        counter = TokenCounter()
        counter.add_message({"role": "user", "content": "你好"})
        assert counter.total > 0

    def test_add_multiple_increments(self):
        """多次添加 total 递增。"""
        counter = TokenCounter()
        counter.add_message({"role": "user", "content": "你好"})
        first = counter.total
        counter.add_message({"role": "assistant", "content": "你好，我是祥子"})
        assert counter.total > first

    def test_rebuild_matches_full_estimate(self):
        """rebuild 后的值与全量估算一致。"""
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")

        counter = TokenCounter()
        counter.add_message({"role": "user", "content": "你好"})
        counter.add_message({"role": "assistant", "content": "我是祥子"})

        rebuilt = TokenCounter()
        rebuilt.rebuild([
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "我是祥子"},
        ])
        assert counter.total == rebuilt.total

    def test_remove_messages_decreases(self):
        """remove_messages 后 total 减少。"""
        counter = TokenCounter()
        counter.add_message({"role": "user", "content": "A" * 100})
        before = counter.total
        counter.remove_messages(1)
        assert counter.total < before

    def test_remove_all_returns_zero(self):
        """移除所有消息后 total 应为 0。"""
        counter = TokenCounter()
        counter.add_message({"role": "user", "content": "测试"})
        counter.remove_messages(1)
        assert counter.total == 0

    def test_add_message_with_tool_content(self):
        """工具结果消息也被正确计数。"""
        counter = TokenCounter()
        counter.add_message({"role": "tool", "content": "搜索结果：" + "A" * 1000})
        assert counter.total > 0

    def test_add_message_multimodal_content(self):
        """多模态 content（list 格式）也被正确计数。"""
        counter = TokenCounter()
        counter.add_message({
            "role": "user",
            "content": [
                {"type": "text", "text": "描述一下这张图"},
                {"type": "image_url", "image_url": {"url": "data:image/..."}},
            ],
        })
        assert counter.total > 0

    def test_add_system_message(self):
        """system 消息也被计数。"""
        counter = TokenCounter()
        counter.add_message({"role": "system", "content": "你是助手"})
        assert counter.total > 0

    def test_empty_content_counts_zero(self):
        """空 content 消息计 0。"""
        counter = TokenCounter()
        counter.add_message({"role": "user", "content": ""})
        assert counter.total == 0

    def test_none_content_counts_zero(self):
        """content=None 的消息计 0。"""
        counter = TokenCounter()
        counter.add_message({"role": "user"})
        assert counter.total == 0
