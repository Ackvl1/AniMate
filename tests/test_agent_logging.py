"""Tests for Agent logging integration — chat_logs + phase_events 自动记录"""

import json
import pytest

from anima.core.log import ChatLogDB
from anima.core.agent import Agent, AgentResponse
from anima.core.llm.models import LLMResult


class MockLLM:
    def __init__(self, reply="默认回复"):
        self.reply = reply
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1
        return LLMResult(content=self.reply)

    def chat_stream(self, messages, tools=None):
        self.call_count += 1
        yield {"type": "delta", "content": self.reply}
        yield {"type": "done"}


class MockVectorStore:
    def search(self, query_vec):
        return []


class MockKeywordStore:
    def search(self, query):
        return []


@pytest.fixture
def agent_with_db():
    """创建 Agent，注入内存 DB。"""
    db = ChatLogDB(db_path=":memory:")
    llm = MockLLM(reply="测试回复")
    agent = Agent(
        llm=llm,
        persona="你是测试助手",
        vector_store=MockVectorStore(),
        keyword_store=MockKeywordStore(),
    )
    agent._log_db = db
    agent._phase_logger = None  # will be lazily created
    return agent, db, llm


class TestAgentChatLogging:
    def test_chat_logs_auto_written(self, agent_with_db):
        """chat() 后 chat_logs 表有记录。"""
        agent, db, _ = agent_with_db
        agent.chat("你好")
        assert db.count() >= 1

    def test_chat_log_has_input_and_response(self, agent_with_db):
        """chat_log 应记录 user_input 和 response_text。"""
        agent, db, _ = agent_with_db
        agent.chat("测试输入")
        logs = db.query(limit=1)
        assert len(logs) >= 1
        assert logs[0]["user_input"] == "测试输入"
        assert len(logs[0]["response_text"]) > 0

    def test_chat_log_has_trace_id(self, agent_with_db):
        """chat_log 应包含 trace_id。"""
        agent, db, _ = agent_with_db
        agent.chat("查询trace")
        logs = db.query(limit=1)
        assert len(logs[0]["trace_id"]) == 8

    def test_phase_events_contain_before_node(self, agent_with_db):
        """phase_events 应包含节点条目。"""
        agent, db, _ = agent_with_db
        agent.chat("测试")
        phases = db.query_phases()
        phase_names = [p["phase_name"] for p in phases]
        # 新架构使用节点名（merge, react, after, reflect 等）
        node_names = {"merge", "react", "after", "reflect"}
        assert node_names.intersection(phase_names), f"未找到节点事件，现有: {phase_names}"

    def test_phase_events_contain_react_node(self, agent_with_db):
        """phase_events 应包含 'react' 条目。"""
        agent, db, _ = agent_with_db
        agent.chat("测试")
        phases = db.query_phases()
        phase_names = [p["phase_name"] for p in phases]
        assert "react" in phase_names

    def test_phase_events_contain_after_node(self, agent_with_db):
        """phase_events 应包含 'after' 条目。"""
        agent, db, _ = agent_with_db
        agent.chat("测试")
        phases = db.query_phases()
        phase_names = [p["phase_name"] for p in phases]
        assert "after" in phase_names

    def test_phase_events_contain_reflect_node(self, agent_with_db):
        """phase_events 应包含 'reflect' 条目。"""
        agent, db, _ = agent_with_db
        agent.chat("测试")
        phases = db.query_phases()
        phase_names = [p["phase_name"] for p in phases]
        assert "reflect" in phase_names

    def test_phase_events_trace_id_linked(self, agent_with_db):
        """phase_events 的 trace_id 应与 chat_log 的 trace_id 一致。"""
        agent, db, _ = agent_with_db
        agent.chat("关联测试")
        logs = db.query(limit=1)
        phases = db.query_phases(trace_id=logs[0]["trace_id"])
        assert len(phases) >= 4  # before + react + after + reflect

    def test_multiple_chats_produce_separate_logs(self, agent_with_db):
        """多次 chat 应产生多条 chat_log 记录。"""
        agent, db, _ = agent_with_db
        agent.chat("第一轮")
        agent.chat("第二轮")
        agent.chat("第三轮")
        assert db.count() == 3

    def test_phase_events_have_duration(self, agent_with_db):
        """phase_event 的 duration_ms 应为正数。"""
        agent, db, _ = agent_with_db
        agent.chat("测试")
        phases = db.query_phases(limit=1)
        assert phases[0]["duration_ms"] >= 0

    def test_chat_log_has_emotion(self, agent_with_db):
        """chat_log 的 emotion 不应为空。"""
        agent, db, _ = agent_with_db
        agent.chat("你好")
        logs = db.query(limit=1)
        assert logs[0]["emotion"] is not None
