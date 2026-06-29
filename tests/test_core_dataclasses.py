"""Tests for core data classes (RunContext, AgentResponse, ReflectionSignal)"""
from anima.core.engine.context import RunContext
from anima.core.agent.response import AgentResponse, ReflectionSignal


class TestRunContext:
    def test_default_values(self):
        ctx = RunContext(user_input="你好")
        assert ctx.user_input == "你好"
        assert ctx.messages == []
        assert ctx.emotion == ""
        assert ctx.gesture is None
        assert ctx.raw_text == ""
        assert ctx.final_text == ""

    def test_custom_values(self):
        ctx = RunContext(
            user_input="test",
            messages=[{"role": "system", "content": "你是一个助手"}],
            emotion="happy",
            gesture="wave",
            raw_text="raw",
            final_text="final",
        )
        assert ctx.user_input == "test"
        assert len(ctx.messages) == 1
        assert ctx.messages[0]["content"] == "你是一个助手"
        assert ctx.emotion == "happy"
        assert ctx.gesture == "wave"

    def test_extras_available(self):
        ctx = RunContext(user_input="hi")
        ctx.extras["key"] = "val"
        assert ctx.extras["key"] == "val"

    def test_trace_id_generated(self):
        ctx = RunContext(user_input="hi")
        assert len(ctx.trace_id) == 12


class TestAgentResponse:
    def test_default_values(self):
        resp = AgentResponse(text="你好")
        assert resp.text == "你好"
        assert resp.emotion == ""
        assert resp.gesture is None

    def test_full_response(self):
        resp = AgentResponse(text="你好呀", emotion="happy", gesture="wave")
        assert resp.text == "你好呀"
        assert resp.emotion == "happy"
        assert resp.gesture == "wave"


class TestReflectionSignal:
    def test_default_level_0(self):
        signal = ReflectionSignal(feedback="")
        assert signal.level == 0
        assert signal.feedback == ""

    def test_high_level(self):
        signal = ReflectionSignal(level=3, feedback="回答不完整")
        assert signal.level == 3
        assert signal.feedback == "回答不完整"
