"""Tests for LogCollector — 审计日志分派器。"""

from unittest.mock import MagicMock, patch

import pytest

from animate.core.engine.node import AgentEvent
from animate.core.log.collector import LogCollector
from animate.core.log.log_db import ChatLogDB


@pytest.fixture
def db(tmp_path):
    """临时 SQLite 数据库。"""
    path = tmp_path / "test_audit.db"
    db = ChatLogDB(db_path=str(path))
    yield db
    db.close()


@pytest.fixture
def collector(db):
    return LogCollector(db)


# ── 事件到表的映射 ─────────────────────────


class TestEventRouting:
    """验证 emit 事件正确分派到对应 log 方法。"""

    def test_tool_done_writes_tool_audit(self, collector, db):
        """tool.done 事件 → tool_audit 表有记录。"""
        collector.handle(AgentEvent(
            type="tool.start",
            trace_id="t1",
            name="web_search",
            arguments={"q": "test"},
        ))
        collector.handle(AgentEvent(
            type="tool.done",
            trace_id="t1",
            name="web_search",
            result="搜索结果...",
            status="success",
        ))
        rows = db.query_tool_audit(trace_id="t1")
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "web_search"
        assert rows[0]["status"] == "success"

    def test_tool_denied_writes_audit(self, collector, db):
        """tool.denied 事件 → tool_audit status=denied。"""
        collector.handle(AgentEvent(
            type="tool.start",
            trace_id="t1",
            name="write_file",
            arguments={"path": "/test"},
        ))
        collector.handle(AgentEvent(
            type="tool.denied",
            trace_id="t1",
            name="write_file",
        ))
        rows = db.query_tool_audit(trace_id="t1")
        assert len(rows) == 1
        assert rows[0]["status"] == "denied"
        assert rows[0]["hitl_status"] == "denied"

    def test_emotion_update_writes_emotion_logs(self, collector, db):
        """emotion.update 事件 → emotion_logs 表有记录。"""
        collector.handle(AgentEvent(
            type="emotion.update",
            trace_id="t1",
            emotion="happy",
            gesture="wave",
        ))
        rows = db.query_emotions(trace_id="t1")
        assert len(rows) == 1
        assert rows[0]["emotion"] == "happy"
        assert rows[0]["gesture"] == "wave"

    def test_unrelated_event_ignored(self, collector, db):
        """与审计无关的事件不影响统计。"""
        collector.handle(AgentEvent(type="text_token", text="hello"))
        assert db.count() == 0  # chat_logs 无变化
        assert len(db.query_tool_audit()) == 0

    def test_tool_done_without_start_no_crash(self, collector):
        """只有 tool.done 没有 tool.start 不崩溃。"""
        collector.handle(AgentEvent(
            type="tool.done",
            trace_id="t1",
            name="unknown_tool",
            result="ok",
            status="success",
        ))
        # 不抛异常即可


class TestDirectApi:
    """直接调用的日志方法。"""

    def test_log_compression(self, collector, db):
        """压缩成功写压缩记录。"""
        collector.log_compression(
            trace_id="t1",
            compress_count=1,
            success=True,
            head_rounds=5,
            tail_rounds=10,
        )
        rows = db.query_compression(trace_id="t1")
        assert len(rows) == 1
        assert rows[0]["success"] == 1

    def test_log_fact_change(self, collector, db):
        """事实变更写审计记录。"""
        collector.log_fact_change(fact_text="用户喜欢猫", source_trace="t1")
        rows = db.query_facts()
        assert len(rows) == 1
        assert rows[0]["fact_text"] == "用户喜欢猫"

    def test_log_fact_change_dedup(self, collector, db):
        """相同事实不重复插入。"""
        collector.log_fact_change(fact_text="用户喜欢猫", source_trace="t1")
        collector.log_fact_change(fact_text="用户喜欢猫", source_trace="t2")
        assert db.count_facts() == 1
