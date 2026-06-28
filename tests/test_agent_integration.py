"""集成测试 — Agent 全链路（含工具调用 + 重试 + 错误兜底）"""

from anima.core.agent import Agent
from anima.core.agent.response import AgentResponse
from anima.core.llm.models import LLMResult, ToolCall
from anima.core.tools.registry import ToolRegistry
from anima.core.tools.function.time_tool import TimeTool


class MockVectorStore:
    def search(self, query_vec):
        return [("祥子出生于丰川家族", 0.85)]


class MockKeywordStore:
    def search(self, query):
        return [("祥子是 Ave Mujica 的键盘手", 0.9)]


class MockLLM:
    """支持 chat_stream 的 Mock LLM。"""

    def __init__(self):
        self.responses: list[LLMResult] = []
        self.call_count = 0
        self.all_messages = []
        self._tool_call_rounds = []

    def chat(self, messages, tools=None):
        self.all_messages.append(messages)
        resp = self.responses[self.call_count] if self.call_count < len(self.responses) else LLMResult(content="默认回复")
        self.call_count += 1
        return resp

    def chat_stream(self, messages, tools=None):
        """同步生成器，模拟 LLM 流式输出。"""
        self.all_messages.append(messages)
        resp_idx = self.call_count
        self.call_count += 1

        if resp_idx < len(self.responses):
            resp = self.responses[resp_idx]
        else:
            resp = LLMResult(content="默认回复")

        # 如果有 tool_calls，先发 tool_call 事件
        if resp.tool_calls:
            for i, tc in enumerate(resp.tool_calls):
                yield {
                    "type": "tool_call",
                    "index": i,
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments) if tc.arguments else "{}",
                }
        elif resp.content:
            # 纯文本回复，逐 token 发送
            yield {"type": "delta", "content": resp.content}

        yield {"type": "done"}


import json


class TestAgentIntegration:
    def test_chat_returns_agent_response(self):
        """最基本的集成：chat() 返回 AgentResponse"""
        llm = MockLLM()
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        resp = agent.chat("你好")
        assert isinstance(resp, AgentResponse)
        assert resp.text is not None
        assert resp.emotion is not None

    def test_chat_with_tool_calls(self):
        """Agent 通过工具调用获取信息"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content="", tool_calls=[ToolCall(id="c1", name="get_time", arguments={"format": "time"})]),
            LLMResult(content='[{"text": "现在是12:00", "emotion": "calm"}]'),
        ]
        tools = ToolRegistry()
        tools.register("get_time", "获取时间", handler=lambda format: "12:00")

        agent = Agent(
            llm=llm, persona="你是助手",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
            tools=tools,
        )

        resp = agent.chat("几点了")
        assert "12:00" in resp.text
        assert resp.emotion == "calm"

    def test_memory_accumulates_across_turns(self):
        """多轮对话历史累积"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content="第一轮回复"),
            LLMResult(content="第二轮回复"),
        ]
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm, persona="你是祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )

        agent.chat("第一轮")
        agent.chat("第二轮")

        messages = agent._messages
        assert len(messages) >= 2  # user + assistant 至少各一

    def test_reset_clears_memory_and_emotion(self):
        """reset 后对话记忆和情绪重置"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content="好"),
            LLMResult(content="新对话"),
        ]
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm, persona="你是祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )

        agent.chat("第一轮")
        agent.reset()
        assert len(agent._messages) == 0

    def test_error_does_not_crash(self):
        """Agent chat 抛异常时返回兜底回复"""
        class CrashingLLM:
            def chat(self, messages, tools=None):
                raise RuntimeError("LLM 炸了")

            def chat_stream(self, messages, tools=None):
                raise RuntimeError("LLM 炸了")
                yield  # never reached, makes this a generator

        agent = Agent.create_default(
            enable_mcp=False,
            llm=CrashingLLM(), persona="你是祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        resp = agent.chat("你好")
        assert resp.text is not None
        assert "抱歉" in resp.text or "问题" in resp.text

    def test_time_tool_concrete(self):
        """具体的 TimeTool 可以注册和执行"""
        tools = ToolRegistry()
        tool = TimeTool()
        tools.register_tool(tool)
        assert "get_time" in tools.names
        result = tools.execute("get_time", {"format": "time"})
        # 返回时间格式 HH:MM:SS
        assert len(result) == 8
        assert ":" in result
