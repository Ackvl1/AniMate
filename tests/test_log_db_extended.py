"""Tests for ChatLogDB new tables + chat_logs extensions (Workstream B)."""
import pytest
from animate.core.log.log_db import ChatLogDB


class TestToolAudit:
    """tool_audit 表 CRUD。"""

    def setup_method(self):
        self.db = ChatLogDB(db_path=":memory:")

    def test_log_tool_audit(self):
        """写入工具审计记录。"""
        row_id = self.db.log_tool_audit(
            trace_id="t1", tool_name="web_search",
            input_args='{"query":"天气"}', output_summary="3 results",
            output_length=500, duration_ms=120, hitl_status="auto", status="success",
        )
        assert row_id > 0

    def test_query_tool_audit_by_trace(self):
        """按 trace_id 查询工具审计。"""
        self.db.log_tool_audit(trace_id="t1", tool_name="web_search", input_args="{}")
        self.db.log_tool_audit(trace_id="t1", tool_name="calculator", input_args="{}")
        self.db.log_tool_audit(trace_id="t2", tool_name="web_search", input_args="{}")
        rows = self.db.query_tool_audit(trace_id="t1")
        assert len(rows) == 2

    def test_query_tool_audit_recent(self):
        """查询最近 N 条。"""
        for i in range(5):
            self.db.log_tool_audit(trace_id="t1", tool_name=f"tool_{i}", input_args="{}")
        rows = self.db.query_tool_audit(limit=3)
        assert len(rows) == 3


class TestCompressionLogs:
    """compression_logs 表 CRUD。"""

    def setup_method(self):
        self.db = ChatLogDB(db_path=":memory:")

    def test_log_compression(self):
        """写入压缩记录。"""
        row_id = self.db.log_compression(
            trace_id="t1", compress_count=1, success=True,
            before_tokens=50000, after_tokens=20000,
            head_rounds=5, middle_msgs=30, tail_rounds=10,
            old_session_id="abc", new_session_id="abc_c1",
        )
        assert row_id > 0

    def test_log_compression_failure(self):
        """写入失败的压缩记录。"""
        row_id = self.db.log_compression(
            trace_id="t1", compress_count=1, success=False,
            error_msg="LLM timeout",
        )
        assert row_id > 0

    def test_query_compression(self):
        """查询压缩记录。"""
        self.db.log_compression(trace_id="t1", compress_count=1, success=True)
        self.db.log_compression(trace_id="t2", compress_count=1, success=False)
        rows = self.db.query_compression(trace_id="t1")
        assert len(rows) == 1


class TestEmotionLogs:
    """emotion_logs 表 CRUD。"""

    def setup_method(self):
        self.db = ChatLogDB(db_path=":memory:")

    def test_log_emotion(self):
        """写入情绪变化记录。"""
        row_id = self.db.log_emotion(
            trace_id="t1", sequence=0, emotion="happy", gesture="wave", source="inline",
        )
        assert row_id > 0

    def test_query_emotion_by_trace(self):
        """按 trace_id 查询情绪日志。"""
        self.db.log_emotion(trace_id="t1", sequence=0, emotion="happy")
        self.db.log_emotion(trace_id="t1", sequence=1, emotion="sad")
        self.db.log_emotion(trace_id="t2", sequence=0, emotion="calm")
        rows = self.db.query_emotions(trace_id="t1")
        assert len(rows) == 2
        assert rows[0]["emotion"] == "happy"
        assert rows[1]["emotion"] == "sad"


class TestChatLogsExtended:
    """chat_logs 新增列。"""

    def setup_method(self):
        self.db = ChatLogDB(db_path=":memory:")

    def test_engine_crashed_field(self):
        """engine_crashed 字段可写入。"""
        row_id = self.db.log(
            trace_id="t1", user_input="test",
            engine_crashed=1, node_failures='["react"]',
        )
        rows = self.db.query(trace_id="t1")
        assert rows[0]["engine_crashed"] == 1
