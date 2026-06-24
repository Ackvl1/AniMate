"""Tests for Agent.compact() and Agent.resume() (Workstream A)."""
import pytest
from unittest.mock import MagicMock
from animate.core.agent import Agent


def _make_agent(llm=None):
    llm = llm or MagicMock()
    llm.chat.return_value = MagicMock(content="摘要内容")
    return Agent(
        llm=llm,
        persona="测试角色",
        vector_store=MagicMock(),
        keyword_store=MagicMock(),
    )


class TestAgentCompact:
    """Agent.compact() 手动触发压缩。"""

    def test_compact_force_compress(self):
        """compact 是强制压缩，不再检查 need_compress。"""
        agent = _make_agent()
        result = agent.compact()
        # 即使 _accumulated=0，也不返回 skip
        assert result["status"] != "skip"

    def test_compact_with_enough_messages(self):
        """消息足够时 → 触发压缩。"""
        agent = _make_agent()
        # 填充 50 轮消息
        for i in range(50):
            agent._messages.append({"role": "user", "content": f"消息{i}" * 100})
            agent._messages.append({"role": "assistant", "content": f"回复{i}" * 100})
        result = agent.compact()
        # 可能成功也可能失败（取决于 LLM mock），但不会是 skip
        assert result["status"] in ("ok", "error")


class TestAgentResume:
    """Agent.resume() 恢复旧 session。"""

    def test_resume_valid_session(self):
        """有效 session → messages 恢复。"""
        agent = _make_agent()
        # 创建一个 session 并存入消息
        test_messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        agent._session_store = MagicMock()
        agent._session_store.load.return_value = test_messages
        ok = agent.resume("test_session")
        assert ok is True
        assert agent._messages == test_messages

    def test_resume_invalid_session(self):
        """无效 session → False。"""
        agent = _make_agent()
        agent._session_store = MagicMock()
        agent._session_store.load.return_value = []
        ok = agent.resume("nonexistent")
        assert ok is False

    def test_resume_no_session_store(self):
        """无 session_store → False。"""
        agent = _make_agent()
        agent._session_store = None
        ok = agent.resume("anything")
        assert ok is False
