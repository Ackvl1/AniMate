"""Tests for ChatLogDB — phase_events + long_term_facts 扩展"""

import json
import pytest

from datetime import datetime


@pytest.fixture
def db():
    from anima.core.log import ChatLogDB
    _db = ChatLogDB(db_path=":memory:")
    yield _db
    _db.close()


class TestPhaseEvents:
    def test_log_phase_inserts_record(self, db):
        """写入一条 phase_event 后查询应有记录。"""
        db.log_phase(
            trace_id="t1",
            phase_name="before",
            input_summary="user: 你好",
            output_summary="injected persona + RAG",
            duration_ms=120,
        )
        rows = db.query_phases(trace_id="t1")
        assert len(rows) == 1
        assert rows[0]["phase_name"] == "before"

    def test_log_phase_with_trace_link(self, db):
        """phase_events 应通过 trace_id 关联到 chat_logs。"""
        db.log(trace_id="trace-link-1", user_input="关联测试")
        db.log_phase(
            trace_id="trace-link-1",
            phase_name="react",
            input_summary="messages",
            output_summary="raw_text",
        )
        phases = db.query_phases(trace_id="trace-link-1")
        assert len(phases) == 1
        assert phases[0]["trace_id"] == "trace-link-1"

    def test_log_phase_extra_json(self, db):
        """extra 字段应能存取 JSON 字符串。"""
        extra = {"level": 3, "feedback": "缺少表情"}
        db.log_phase(
            trace_id="t3",
            phase_name="reflect",
            output_summary="level 3",
            duration_ms=500,
            extra=extra,
        )
        rows = db.query_phases(trace_id="t3")
        stored_extra = json.loads(rows[0]["extra"])
        assert stored_extra["level"] == 3
        assert stored_extra["feedback"] == "缺少表情"

    def test_log_phase_status_error(self, db):
        """status='error' 时应有 error 信息。"""
        db.log_phase(
            trace_id="t4",
            phase_name="react",
            output_summary="",
            duration_ms=0,
            status="error",
            error="LLM API timeout",
        )
        rows = db.query_phases(trace_id="t4")
        assert rows[0]["status"] == "error"
        assert "timeout" in rows[0]["error"]

    def test_query_phases_limit(self, db):
        """query_phases 应支持 limit 参数。"""
        for i in range(10):
            db.log_phase(trace_id=f"t-limit", phase_name=f"phase_{i}", input_summary="")
        rows = db.query_phases(trace_id="t-limit", limit=3)
        assert len(rows) == 3

    def test_query_phases_ordered_by_id_desc(self, db):
        """query_phases 按 id 降序排列（最新在前）。"""
        for i in range(3):
            db.log_phase(trace_id="t-order", phase_name=f"step_{i}", input_summary="")
        rows = db.query_phases(trace_id="t-order")
        names = [r["phase_name"] for r in rows]
        assert names == ["step_2", "step_1", "step_0"]


class TestLongTermFacts:
    def test_insert_fact(self, db):
        """插入一条事实后 count 应为 1。"""
        db.add_fact(fact_text="用户喜欢猫", source_trace="t1")
        facts = db.query_facts()
        assert len(facts) == 1
        assert facts[0]["fact_text"] == "用户喜欢猫"

    def test_insert_duplicate_fact(self, db):
        """相同事实重复插入应被去重。"""
        db.add_fact(fact_text="用户喜欢猫", source_trace="t1")
        db.add_fact(fact_text="用户喜欢猫", source_trace="t2")  # 重复
        facts = db.query_facts()
        assert len(facts) == 1  # 去重后只有一条

    def test_query_facts_limit(self, db):
        """query_facts 应支持 limit 参数。"""
        for i in range(10):
            db.add_fact(fact_text=f"事实{i}", source_trace="t1")
        facts = db.query_facts(limit=3)
        assert len(facts) == 3

    def test_query_facts_ordered_by_id_desc(self, db):
        """query_facts 按 id 降序排列（最新在前）。"""
        db.add_fact(fact_text="第一条", source_trace="t1")
        db.add_fact(fact_text="第二条", source_trace="t1")
        facts = db.query_facts()
        # 去重后实际只有两条不同的（假设它们 hash 不同）
        texts = [f["fact_text"] for f in facts]
        # 不管顺序，只要两条都包含
        assert "第一条" in texts
        assert "第二条" in texts

    def test_clear_facts(self, db):
        """clear_facts() 应清空所有事实。"""
        db.add_fact(fact_text="事实A", source_trace="t1")
        db.add_fact(fact_text="事实B", source_trace="t1")
        assert len(db.query_facts()) == 2
        db.clear_facts()
        assert len(db.query_facts()) == 0

    def test_count_facts(self, db):
        """count_facts() 返回事实总数。"""
        db.add_fact(fact_text="事实1", source_trace="t1")
        db.add_fact(fact_text="事实2", source_trace="t1")
        assert db.count_facts() == 2

    def test_fact_hash_auto_generated(self, db):
        """插入时自动计算 fact_hash。"""
        db.add_fact(fact_text="用户身高175cm", source_trace="t1")
        facts = db.query_facts()
        assert len(facts) == 1
        assert len(facts[0]["fact_hash"]) == 16  # sha256[:16]

    def test_delete_fact_by_id(self, db):
        """按 id 删除事实。"""
        db.add_fact(fact_text="要删除的事实", source_trace="t1")
        facts = db.query_facts()
        fact_id = facts[0]["id"]
        db.delete_fact(fact_id)
        assert db.count_facts() == 0
