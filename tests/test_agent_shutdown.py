"""Tests for Agent.shutdown() resource cleanup (Workstream A)."""
import pytest
from unittest.mock import MagicMock, patch
from anima.core.agent import Agent


def _make_agent():
    llm = MagicMock()
    llm.chat.return_value = MagicMock(content="摘要")
    return Agent(
        llm=llm, persona="测试",
        vector_store=MagicMock(), keyword_store=MagicMock(),
    )


class TestAgentShutdown:
    """Agent.shutdown() 关闭所有 DB 连接。"""

    def test_shutdown_closes_session_store(self):
        """shutdown 关闭 session_store。"""
        agent = _make_agent()
        agent._session_store = MagicMock()
        agent.shutdown()
        agent._session_store.close.assert_called_once()

    def test_shutdown_closes_memory_provider(self):
        """shutdown 关闭 memory_provider。"""
        agent = _make_agent()
        agent._memory_provider = MagicMock()
        agent.shutdown()
        agent._memory_provider.shutdown.assert_called_once()

    def test_shutdown_closes_phase_logger_db(self):
        """shutdown 关闭 phase_logger 的 DB。"""
        agent = _make_agent()
        agent._phase_logger = MagicMock()
        agent._phase_logger._db = MagicMock()
        agent.shutdown()
        agent._phase_logger._db.close.assert_called_once()

    def test_shutdown_stops_mcp_clients(self):
        """shutdown 停止所有 MCP 客户端。"""
        agent = _make_agent()
        client1 = MagicMock()
        client2 = MagicMock()
        agent._mcp_clients = [client1, client2]
        agent.shutdown()
        client1.stop.assert_called_once()
        client2.stop.assert_called_once()
        assert len(agent._mcp_clients) == 0

    def test_shutdown_handles_none_resources(self):
        """shutdown 不报错当资源为 None。"""
        agent = _make_agent()
        agent._session_store = None
        agent._memory_provider = None
        agent._phase_logger = None
        agent.shutdown()  # 不应报错
