"""Tests for DiffHistory persistence (Phase 6.5 — async, 7-field schema)"""
import pytest
import asyncio
from animate.core.engine.diff_history import DiffHistory


class TestDiffHistory:
    """DiffHistory 应该支持 SQLite 持久化（async record, 7 fields）"""

    @pytest.mark.asyncio
    async def test_init_creates_table(self):
        """初始化应该创建 diff_history 表"""
        history = DiffHistory(":memory:")
        rows = history.query(limit=10)
        assert rows == []
        history.close()

    @pytest.mark.asyncio
    async def test_record_and_query(self):
        """async record 应该保存记录，query 应该返回"""
        history = DiffHistory(":memory:")
        await history.record(
            node_name="react", diff={"emotion": "happy"},
            trace_id="abc",
        )
        await history.flush()

        rows = history.query(trace_id="abc")
        assert len(rows) == 1
        assert rows[0]["node_name"] == "react"
        assert rows[0]["diff"] == {"emotion": "happy"}
        assert rows[0]["duration_ms"] == 0
        history.close()

    @pytest.mark.asyncio
    async def test_record_with_inputs_and_duration(self):
        """record 应该保存 inputs 和 duration_ms"""
        history = DiffHistory(":memory:")
        await history.record(
            node_name="after", diff={"final_text": "hello"},
            trace_id="xyz",
            inputs={"raw_text": "hello world"},
            duration_ms=42.5,
        )
        await history.flush()

        rows = history.query(trace_id="xyz")
        assert len(rows) == 1
        assert rows[0]["inputs"] == {"raw_text": "hello world"}
        assert rows[0]["duration_ms"] == 42.5
        history.close()

    @pytest.mark.asyncio
    async def test_buffer_flushes_at_max(self):
        """buffer 满时自动 flush"""
        history = DiffHistory(":memory:", max_buffer=3)
        for i in range(3):
            await history.record(
                node_name=f"node_{i}", diff={"i": i}, trace_id="buf"
            )
        # 第 3 条触发 auto flush
        rows = history.query(trace_id="buf")
        assert len(rows) == 3
        history.close()

    @pytest.mark.asyncio
    async def test_query_by_trace_id(self):
        """query 应该支持按 trace_id 过滤"""
        history = DiffHistory(":memory:")
        await history.record(node_name="react", diff={}, trace_id="abc")
        await history.record(node_name="react", diff={}, trace_id="def")
        await history.flush()

        rows = history.query(trace_id="abc")
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "abc"
        history.close()

    @pytest.mark.asyncio
    async def test_full_chain_ordering(self):
        """一个 trace 的完整 diff 链应该按 id 有序"""
        history = DiffHistory(":memory:")
        nodes = ["memory", "rag_vector", "rag_keyword", "system_prompt",
                 "merge", "react", "after", "reflect"]
        for name in nodes:
            await history.record(node_name=name, diff={}, trace_id="chain1")
        await history.flush()

        rows = history.query(trace_id="chain1")
        assert len(rows) == 8
        assert [r["node_name"] for r in rows] == nodes
        history.close()
