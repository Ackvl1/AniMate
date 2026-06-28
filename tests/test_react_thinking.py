"""Tests for ReAct thinking — 保留 LLM 思考过程的真正多轮 ReAct（图引擎版）"""

import json
import pytest

from animate.core.engine.context import RunContext
from animate.core.agent.nodes.react import ReactNode
from animate.core.llm.models import LLMResult, ToolCall
from animate.core.tools.registry import ToolRegistry


class MockLLM:
    def __init__(self):
        self.responses: list[LLMResult] = []
        self.call_count = 0
        self.all_messages = []

    def chat_stream(self, messages, tools=None):
        self.all_messages.append(messages)
        resp_idx = self.call_count
        self.call_count += 1

        if resp_idx < len(self.responses):
            resp = self.responses[resp_idx]
        else:
            resp = LLMResult(content="默认")

        if resp.tool_calls:
            for i, tc in enumerate(resp.tool_calls):
                yield {
                    "type": "tool_call",
                    "index": i,
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments) if tc.arguments else "{}",
                }
            if resp.content:
                yield {"type": "delta", "content": resp.content}
        elif resp.content:
            yield {"type": "delta", "content": resp.content}

        yield {"type": "done"}


class TestReActThinking:
    @pytest.mark.asyncio
    async def test_thinking_preserved_with_tool_calls(self):
        """tool_call 时 LLM 的 content（思考）被保留在 assistant 消息里"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content="让我看看东京的天气...", tool_calls=[ToolCall(id="c1", name="weather", arguments={"city": "Tokyo"})]),
            LLMResult(content="东京现在 25°C"),
        ]
        tools = ToolRegistry()
        tools.register("weather", "查询天气", handler=lambda city: "25°C")

        node = ReactNode(llm=llm, tools=tools)
        ctx = RunContext(user_input="东京天气怎么样")
        ctx.messages = [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "东京天气怎么样"}]

        async def noop_emit(*args, **kwargs):
            pass

        result = await node.run(ctx, noop_emit)

        # 检查 messages 中 assistant 消息是否保留了 thinking
        assistant_msgs = [m for m in result.diff["messages"] if m["role"] == "assistant"]
        tool_msgs = [m for m in result.diff["messages"] if m["role"] == "tool"]

        # assistant 消息的 content 应该保留思考过程
        assert any("东京的天气" in (m.get("content") or "") for m in assistant_msgs)
        # tool 消息也应该存在
        assert len(tool_msgs) == 1

    def test_thinking_text_preserved_in_assistant_message(self):
        """ToolCall.to_assistant_message(content) 保留 content"""
        tc = ToolCall(id="c1", name="weather", arguments={"city": "Tokyo"})
        msg = tc.to_assistant_message(content="让我看看东京的天气")
        assert msg["content"] == "让我看看东京的天气"
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["function"]["name"] == "weather"

    def test_thinking_default_empty(self):
        """不传 content 时默认为空字符串"""
        tc = ToolCall(id="c1", name="weather", arguments={})
        msg = tc.to_assistant_message()
        assert msg["content"] == ""

    def test_system_prompt_has_thinking_hint(self):
        """SystemPromptNode 的 system prompt 应该提示 LLM 输出自然思考"""
        from animate.core.agent.nodes.system_prompt import SystemPromptNode
        prompt = SystemPromptNode.EMOTION_INSTRUCTION
        hint_found = "思考" in prompt or "think" in prompt.lower()
        assert hint_found
