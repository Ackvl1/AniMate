"""测试 CLI `/log` 命令。"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from animate.core.log import ChatLogDB


def _make_log_db() -> ChatLogDB:
    """创建一个内存 SQLite ChatLogDB 用于测试。"""
    db = ChatLogDB(":memory:")
    return db


def _insert_sample_chat(db: ChatLogDB, trace_id: str = "trace-001") -> int:
    """插入一条示例 chat 记录。"""
    return db.log(
        trace_id=trace_id,
        user_input="你好",
        response_text="你好！我是 Saki",
        emotion="happy",
        gesture="wave",
        llm_call_count=3,
        total_duration_ms=1500,
        tool_calls=[{"name": "search", "arguments": {"q": "test"}}],
    )


def _insert_sample_phases(db: ChatLogDB, trace_id: str = "trace-001"):
    """插入几条示例阶段事件。"""
    db.log_phase(trace_id, "before", duration_ms=100, status="ok")
    db.log_phase(trace_id, "react", duration_ms=500, status="ok")
    db.log_phase(trace_id, "after", duration_ms=200, status="ok")


def _insert_sample_facts(db: ChatLogDB, trace_id: str = "trace-001"):
    """插入几条示例长期记忆。"""
    db.add_fact("用户喜欢简洁回复", trace_id)
    db.add_fact("用户偏好命令行操作", trace_id)


class TestLogChat:
    """测试 /log chat 子命令。"""

    def test_log_chat_no_data(self, capsys):
        """无数据时应该友好提示。"""
        db = _make_log_db()
        from cli import handle_log_command

        handle_log_command(["chat"], db)
        captured = capsys.readouterr()
        assert "暂无" in captured.out or "没有" in captured.out

    def test_log_chat_with_data(self, capsys):
        """有数据时应该显示记录。"""
        db = _make_log_db()
        _insert_sample_chat(db)
        from cli import handle_log_command

        handle_log_command(["chat"], db)
        captured = capsys.readouterr()
        assert "你好" in captured.out
        assert "happy" in captured.out
        assert "1.5s" in captured.out or "1500" in captured.out

    def test_log_chat_limit(self, capsys):
        """应该支持自定义 limit。"""
        db = _make_log_db()
        for i in range(5):
            db.log(f"trace-{i}", user_input=f"msg{i}")
        from cli import handle_log_command

        handle_log_command(["chat", "3"], db)
        captured = capsys.readouterr()
        # 只显示 3 条
        lines = [l for l in captured.out.split("\n") if l.strip()]
        assert len(lines) < 10  # 不会太多行


class TestLogPhase:
    """测试 /log phase 子命令。"""

    def test_log_phase_no_trace(self, capsys):
        """不带 trace_id 时应该提示用法。"""
        db = _make_log_db()
        from cli import handle_log_command

        handle_log_command(["phase"], db)
        captured = capsys.readouterr()
        assert "trace_id" in captured.out or "用法" in captured.out

    def test_log_phase_with_data(self, capsys):
        """有数据时应该显示阶段信息。"""
        db = _make_log_db()
        _insert_sample_phases(db, "trace-001")
        from cli import handle_log_command

        handle_log_command(["phase", "trace-001"], db)
        captured = capsys.readouterr()
        assert "before" in captured.out
        assert "react" in captured.out
        assert "after" in captured.out
        assert "100" in captured.out or "500" in captured.out

    def test_log_phase_nonexistent(self, capsys):
        """不存在的 trace_id 应该友好提示。"""
        db = _make_log_db()
        from cli import handle_log_command

        handle_log_command(["phase", "no-such-trace"], db)
        captured = capsys.readouterr()
        assert "暂无" in captured.out or "没有" in captured.out or "未找到" in captured.out


class TestLogFacts:
    """测试 /log facts 子命令。"""

    def test_log_facts_no_data(self, capsys):
        """无数据时应该友好提示。"""
        db = _make_log_db()
        from cli import handle_log_command

        handle_log_command(["facts"], db)
        captured = capsys.readouterr()
        assert "暂无" in captured.out or "没有" in captured.out

    def test_log_facts_with_data(self, capsys):
        """有数据时应该显示事实。"""
        db = _make_log_db()
        _insert_sample_facts(db)
        from cli import handle_log_command

        handle_log_command(["facts"], db)
        captured = capsys.readouterr()
        assert "简洁回复" in captured.out
        assert "命令行" in captured.out


class TestLogClear:
    """测试 /log clear 子命令。"""

    def test_log_clear(self, capsys):
        """清除后数据为空。"""
        db = _make_log_db()
        _insert_sample_chat(db)
        _insert_sample_facts(db)
        from cli import handle_log_command

        handle_log_command(["clear"], db)
        captured = capsys.readouterr()
        assert "已清空" in captured.out

        # 验证确实清了
        assert db.count() == 0
        assert db.count_phases() == 0
        assert db.count_facts() == 0


class TestLogInvalid:
    """测试无效子命令。"""

    def test_invalid_subcommand(self, capsys):
        """未识别的子命令应该提示。"""
        db = _make_log_db()
        from cli import handle_log_command

        handle_log_command(["invalid_sub"], db)
        captured = capsys.readouterr()
        assert "未知" in captured.out or "用法" in captured.out or "help" in captured.out.lower()


class TestHelp:
    """测试 /help 包含 /log。"""

    def test_help_mentions_log(self, capsys):
        """/help 应该列出 /log 命令。"""
        from cli import handle_command

        agent = MagicMock()
        llm = MagicMock()
        debug = [False, False]
        db = _make_log_db()

        result = handle_command("/help", agent, llm, debug, log_db=db)
        captured = capsys.readouterr()
        assert result is True
        assert "/log" in captured.out
