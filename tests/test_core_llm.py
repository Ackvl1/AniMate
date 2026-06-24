"""Tests for core LLM client"""

from unittest.mock import MagicMock, patch
import pytest
import openai

from animate.core.llm import OpenAICompatibleClient, LLMResult
from animate.core.errors import LLMError


def _make_mock_response(content: str, model="test-model"):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.model = model
    usage = MagicMock()
    usage.model_dump = lambda: {"prompt_tokens": 10, "completion_tokens": 20}
    resp.usage = usage
    return resp


def _make_mock_chunk(content=None, finish_reason=None, usage=None):
    chunk = MagicMock()
    choice = MagicMock()
    choice.index = 0
    choice.finish_reason = finish_reason
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = None
    delta.role = None
    choice.delta = delta
    chunk.choices = [choice] if content is not None or finish_reason else []
    chunk.model = "test-model"
    chunk.usage = usage
    return chunk


@pytest.fixture(autouse=True)
def _mock_openai():
    with patch("openai.OpenAI") as mock:
        instance = MagicMock()
        mock.return_value = instance
        yield instance


class TestInit:
    def test_default_provider(self):
        client = OpenAICompatibleClient()
        assert client._model is not None
        assert client._provider_config is not None

    def test_unknown_provider(self):
        with pytest.raises(LLMError):
            OpenAICompatibleClient(provider="nonexistent")


class TestSyncChat:
    def test_simple_text(self, _mock_openai):
        _mock_openai.chat.completions.create.return_value = _make_mock_response("你好！")
        client = OpenAICompatibleClient(provider="deepseek", model="test-model")
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result.content == "你好！"

    def test_retry_then_succeed(self, _mock_openai):
        resp = MagicMock()
        resp.status_code = 429
        responses = [
            openai.RateLimitError("rate limit", response=resp, body={}),
            _make_mock_response("好了"),
        ]
        _mock_openai.chat.completions.create.side_effect = responses
        client = OpenAICompatibleClient(provider="deepseek", model="test-model", max_retries=2)
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result.content == "好了"

    def test_exhaust_retries(self, _mock_openai):
        _mock_openai.chat.completions.create.side_effect = openai.APIConnectionError(
            message="fail", request=MagicMock()
        )
        client = OpenAICompatibleClient(provider="deepseek", model="test-model", max_retries=2)
        with pytest.raises(LLMError, match="已重试 2 次"):
            client.chat([{"role": "user", "content": "hi"}])


class TestStreamChat:
    def test_simple_stream(self, _mock_openai):
        chunks = [
            _make_mock_chunk(content="你好"),
            _make_mock_chunk(content="！"),
            _make_mock_chunk(finish_reason="stop"),
        ]
        _mock_openai.chat.completions.create.return_value = chunks
        client = OpenAICompatibleClient(provider="deepseek", model="test-model")
        events = list(client.chat_stream([{"role": "user", "content": "hi"}]))
        assert events == [
            {"type": "delta", "content": "你好"},
            {"type": "delta", "content": "！"},
            {"type": "done"},
        ]

    def test_stream_with_usage(self, _mock_openai):
        """流式响应包含 usage chunk。"""
        chunks = [
            _make_mock_chunk(content="hello"),
            _make_mock_chunk(content=" world"),
            _make_mock_chunk(finish_reason="stop"),
            _make_mock_chunk(usage=MagicMock(
                model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            )),
        ]
        _mock_openai.chat.completions.create.return_value = chunks
        client = OpenAICompatibleClient(provider="deepseek", model="test-model")
        events = list(client.chat_stream([{"role": "user", "content": "hi"}]))
        assert events[-1] == {"type": "usage", "total_tokens": 15}
