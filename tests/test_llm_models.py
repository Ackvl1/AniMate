"""Tests for LLMResult and ToolCall dataclasses"""

import json
from animate.core.llm.models import LLMResult, ToolCall


class TestToolCall:
    def test_create_tool_call(self):
        tc = ToolCall(id="call_123", name="search", arguments={"q": "祥子"})
        assert tc.id == "call_123"
        assert tc.name == "search"
        assert tc.arguments == {"q": "祥子"}

    def test_to_assistant_message(self):
        tc = ToolCall(id="call_123", name="search", arguments={"q": "祥子"})
        msg = tc.to_assistant_message()
        assert msg["role"] == "assistant"
        assert msg["content"] == ""
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["id"] == "call_123"
        assert msg["tool_calls"][0]["function"]["name"] == "search"

    def test_to_tool_message(self):
        tc = ToolCall(id="call_123", name="search", arguments={"q": "祥子"})
        msg = tc.to_tool_message(result="祥子出生于丰川家族")
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_123"
        assert msg["content"] == "祥子出生于丰川家族"

    def test_from_openai_none(self):
        assert ToolCall.from_openai(None) is None

    def test_from_openai_single(self):
        class MockFunc:
            name = "search"
            arguments = '{"q":"祥子"}'

        class MockChoice:
            id = "call_1"
            type = "function"
            function = MockFunc()

        result = ToolCall.from_openai([MockChoice()])
        assert result is not None
        assert len(result) == 1
        assert result[0].id == "call_1"
        assert result[0].name == "search"
        assert result[0].arguments == {"q": "祥子"}


class TestLLMResult:
    def test_text_only(self):
        result = LLMResult(content="本小姐很好")
        assert result.content == "本小姐很好"
        assert result.tool_calls is None

    def test_with_tool_calls(self):
        tc = ToolCall(id="call_1", name="search", arguments={"q": "祥子"})
        result = LLMResult(content="", tool_calls=[tc])
        assert result.content == ""
        assert len(result.tool_calls) == 1

    def test_has_tool_calls_true(self):
        tc = ToolCall(id="call_1", name="search", arguments={})
        result = LLMResult(content="", tool_calls=[tc])
        assert result.has_tool_calls is True

    def test_has_tool_calls_false(self):
        result = LLMResult(content="你好")
        assert result.has_tool_calls is False

    def test_has_tool_calls_empty_list(self):
        result = LLMResult(content="你好", tool_calls=[])
        assert result.has_tool_calls is False
