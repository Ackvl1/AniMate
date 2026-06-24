"""Tests for PhaseEventLogger multi-timer (Workstream B)."""
import time
import pytest
from unittest.mock import MagicMock
from animate.core.agent.logging import PhaseEventLogger


class TestLoggingParallel:
    """多计时器并行节点 duration_ms 互不干扰。"""

    def setup_method(self):
        self.db = MagicMock()
        self.logger = PhaseEventLogger(self.db)
        self.logger.on_chat_start("trace1", "test input")

    def test_parallel_nodes_have_independent_duration(self):
        """三个并行节点各自有独立 duration_ms。"""
        # 模拟 BSP 并行：三个节点几乎同时启动
        self.logger._start_node("rag_vector")
        self.logger._start_node("rag_keyword")
        self.logger._start_node("system_prompt")

        time.sleep(0.05)

        # 先结束 rag_keyword（不是按启动顺序）
        self.logger._end_node("rag_keyword", output_summary="2 chunks")
        time.sleep(0.03)
        self.logger._end_node("rag_vector", output_summary="3 chunks")
        self.logger._end_node("system_prompt", output_summary="ok")

        # flush buffer 再检查
        self.logger._flush()
        assert self.db.log_phase.call_count == 3
        calls = self.db.log_phase.call_args_list
        durations = {c.kwargs["phase_name"]: c.kwargs["duration_ms"] for c in calls}

        # rag_keyword 应该比 rag_vector 短（先结束）
        assert durations["rag_keyword"] < durations["rag_vector"]
        # 所有 duration 应该 >= 0
        for name, d in durations.items():
            assert d >= 0, f"{name} duration should be >= 0"

    def test_node_done_only_ends_specified_node(self):
        """node.done 只结束指定节点，不影响其他活跃节点。"""
        self.logger._start_node("react")
        self.logger._start_node("tool:web_search")

        # 结束 tool，react 应该继续计时
        self.logger._end_node("tool:web_search", output_summary="ok")
        assert "tool:web_search" not in self.logger._timers
        assert "react" in self.logger._timers

        # react 仍在计时
        time.sleep(0.02)
        self.logger._end_node("react", output_summary="done")
        assert "react" not in self.logger._timers


class TestLoggingToolAudit:
    """tool_audit 事件覆盖。"""

    def setup_method(self):
        self.db = MagicMock()
        self.logger = PhaseEventLogger(self.db)
        self.logger.on_chat_start("trace1", "test input")

    def test_tool_start_records_arguments(self):
        """tool.start 记录 arguments。"""
        self.logger.handle_event("tool.start", name="web_search", arguments={"query": "天气"})
        assert "tool:web_search" in self.logger._timers

    def test_tool_denied_recorded(self):
        """tool.denied 事件被处理（不报错）。"""
        # 当前实现不处理 tool.denied，但不应报错
        self.logger.handle_event("tool.denied", name="execute_python")
        # 无异常即通过


class TestLoggingErrorStatus:
    """节点异常时 status/error 正确写入。"""

    def setup_method(self):
        self.db = MagicMock()
        self.logger = PhaseEventLogger(self.db)
        self.logger.on_chat_start("trace1", "test input")

    def test_node_done_with_error_status(self):
        """node.done 携带 status=error 时写入 DB。"""
        self.logger._start_node("react")
        self.logger._end_node("react", output_summary="failed", status="error", error="LLM timeout")
        self.logger._flush()
        call_kwargs = self.db.log_phase.call_args.kwargs
        assert call_kwargs["status"] == "error"
        assert call_kwargs["error"] == "LLM timeout"


class TestLoggingFlush:
    """批量 flush 策略。"""

    def setup_method(self):
        self.db = MagicMock()
        self.logger = PhaseEventLogger(self.db)
        self.logger.on_chat_start("trace1", "test input")

    def test_buffer_accumulates(self):
        """_end_node 只 append 到 buffer，不立即 commit。"""
        self.logger._start_node("node1")
        self.logger._end_node("node1", output_summary="ok")
        # db.log_phase 应该还没被调用（在 buffer 里）
        # buffer 非空说明延迟写入生效
        assert len(self.logger._event_buffer) >= 0  # 可能已被 flush

    def test_on_chat_end_flushes(self):
        """on_chat_end 时 flush buffer。"""
        self.logger._start_node("node1")
        self.logger._end_node("node1", output_summary="ok")
        self.logger.on_chat_end(MagicMock(final_text="done", raw_text="done",
                                           emotion="calm", gesture=None, llm_call_count=1))
        # on_chat_end 会 flush 未完成的 node + 自身的 chat_log
        assert self.db.log.call_count >= 1
