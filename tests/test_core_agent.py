"""Tests for Agent 门面（集成测试）"""

from animate.core.agent import Agent
from animate.core.engine.context import RunContext
from animate.core.agent.response import AgentResponse
from animate.core.llm.models import LLMResult


class MockLLM:
    def __init__(self, reply="本小姐觉得这个问题很有意思呢"):
        self.reply = reply
        self.all_calls = []

    def chat(self, messages, tools=None):
        self.all_calls.append(messages)
        return LLMResult(content=self.reply)

    def chat_stream(self, messages, tools=None):
        """同步生成器，模拟 LLM 流式输出。"""
        self.all_calls.append(messages)
        # 直接 yield 全部内容作为单个 delta
        yield {"type": "delta", "content": self.reply}
        yield {"type": "done"}


class MockVectorStore:
    def search(self, query_vec):
        return [("祥子出生于丰川家族", 0.85)]


class MockKeywordStore:
    def search(self, query):
        return [("祥子是 Ave Mujica 的键盘手", 0.9)]


class TestAgentCreate:
    def test_create_default(self):
        llm = MockLLM()
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        assert agent is not None
        assert agent.tools is not None

    def test_chat_returns_agent_response(self):
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
        assert resp.emotion in ("", "calm", "pleased", "cold")


class TestAgentChat:
    def test_constructs_and_sends_messages(self):
        llm = MockLLM()
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm,
            persona="你是祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        agent.chat("你是谁")
        assert len(llm.all_calls) >= 1
        main_call = llm.all_calls[0]
        assert any(m["role"] == "user" for m in main_call)

    def test_conversation_history_accumulates(self):
        llm = MockLLM()
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm,
            persona="你是祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        agent.chat("第一轮")
        agent.chat("第二轮")
        # 至少两轮对话都调用了 LLM
        assert len(llm.all_calls) >= 2


class TestAgentReset:
    def test_reset_clears_memory_and_emotion(self):
        llm = MockLLM(reply="test")
        agent = Agent.create_default(
            enable_mcp=False,
            llm=llm,
            persona="你是祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        agent.chat("第一轮")
        agent.reset()
        resp = agent.chat("第二轮")
        assert resp.text is not None
