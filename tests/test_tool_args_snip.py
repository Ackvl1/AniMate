"""Tests for tool_call arguments snip (Workstream D)."""
import pytest
from animate.core.context.manager import ContextManager


class TestToolArgsSnip:
    """tool_call arguments 截断：>2000 chars → snip。"""

    def setup_method(self):
        self.cm = ContextManager(model_limit=1_000_000)

    def test_large_arguments_snipped(self):
        """assistant 消息中 tool_call arguments > 2000 chars → 截断。"""
        large_args = "x" * 3000
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {
                    "name": "execute_python",
                    "arguments": large_args,
                }}
            ]},
        ]
        # 只有一条消息，index 0 在 middle 范围内
        middle = {0}
        self.cm._snip_tool_results(messages, middle)
        args = messages[0]["tool_calls"][0]["function"]["arguments"]
        assert len(args) < 3000
        assert "[参数过长，已省略]" in args

    def test_small_arguments_preserved(self):
        """assistant 消息中 tool_call arguments < 2000 chars → 不截断。"""
        small_args = '{"query": "天气"}'
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {
                    "name": "web_search",
                    "arguments": small_args,
                }}
            ]},
        ]
        middle = {0}
        self.cm._snip_tool_results(messages, middle)
        args = messages[0]["tool_calls"][0]["function"]["arguments"]
        assert args == small_args

    def test_tool_result_still_snipped_at_5000(self):
        """tool 结果按 5000 chars 截断。"""
        large_result = "x" * 6000
        messages = [
            {"role": "tool", "content": large_result},
        ]
        middle = {0}
        self.cm._snip_tool_results(messages, middle)
        assert len(messages[0]["content"]) < 6000
        assert "[工具结果较长，已压缩]" in messages[0]["content"]

    def test_non_tool_messages_ignored(self):
        """普通 user/assistant 消息不受影响。"""
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        middle = {0, 1}
        self.cm._snip_tool_results(messages, middle)
        assert messages[0]["content"] == "你好"
        assert messages[1]["content"] == "你好！"
