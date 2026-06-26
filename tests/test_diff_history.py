"""Tests for DiffHistory persistence (Phase 6)"""
import pytest
import asyncio
import time
from pathlib import Path
from animate.core.engine.diff_history import DiffHistory


class TestDiffHistory:
    """DiffHistory 应该支持 SQLite 持久化"""
    
    def test_init_creates_table(self):
        """初始化应该创建 diff_history 表"""
        history = DiffHistory(":memory:")
        assert history.db_path == ":memory:"
    
    def test_save_records(self):
        """save_records 应该保存记录"""
        history = DiffHistory(":memory:")
        
        records = [
            {"trace_id": "abc", "node": "react", "diff": {"emotion": "happy"}},
            {"trace_id": "abc", "node": "after", "diff": {"final_text": "hello"}},
        ]
        
        history.save_records(records)
        
        # 查询验证
        rows = history.query(trace_id="abc")
        assert len(rows) == 2
    
    def test_query_by_trace_id(self):
        """query 应该支持按 trace_id 过滤"""
        history = DiffHistory(":memory:")
        
        history.save_records([
            {"trace_id": "abc", "node": "react", "diff": {"emotion": "happy"}},
            {"trace_id": "def", "node": "react", "diff": {"emotion": "sad"}},
        ])
        
        rows = history.query(trace_id="abc")
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "abc"
    
    def test_query_by_time_range(self):
        """query 应该支持时间范围过滤"""
        history = DiffHistory(":memory:")
        
        now = time.time()
        history.save_records([
            {"trace_id": "a", "node": "react", "diff": {}, "ts": now - 100},
            {"trace_id": "b", "node": "react", "diff": {}, "ts": now},
            {"trace_id": "c", "node": "react", "diff": {}, "ts": now + 100},
        ])
        
        # 只返回时间范围内的
        rows = history.query(since=now - 50, before=now + 50)
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "b"
    
    def test_cleanup_removes_old(self):
        """cleanup 应该删除超过 retention_days 的记录"""
        history = DiffHistory(":memory:", retention_days=1)
        
        old_time = time.time() - 2 * 86400  # 2 天前
        history.save_records([
            {"trace_id": "old", "node": "react", "diff": {}, "ts": old_time},
            {"trace_id": "new", "node": "react", "diff": {}, "ts": time.time()},
        ])
        
        deleted = history.cleanup()
        assert deleted == 1
        
        rows = history.query()
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "new"
    
    def test_save_empty_records(self):
        """save_records 应该跳过空列表"""
        history = DiffHistory(":memory:")
        history.save_records([])
        rows = history.query()
        assert len(rows) == 0
    
    def test_persistence_across_instances(self):
        """记录应该持久化到文件"""
        import tempfile
        import os
        
        db_path = os.path.join(tempfile.gettempdir(), "test_diff_history.db")
        try:
            # 清理旧文件
            if os.path.exists(db_path):
                os.remove(db_path)
            
            # 写入并关闭
            h1 = DiffHistory(db_path)
            h1.save_records([{"trace_id": "test", "node": "react", "diff": {}}])
            h1.close()
            
            # 重新打开读取并关闭
            h2 = DiffHistory(db_path)
            rows = h2.query(trace_id="test")
            h2.close()
            assert len(rows) == 1
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)
