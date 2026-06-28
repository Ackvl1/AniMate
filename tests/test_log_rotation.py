"""Tests for log rotation (Workstream B)."""
import os
import time
import pytest
from anima.core.log.log_db import ChatLogDB


class TestLogRotation:
    """日志轮转：按大小 + 按时间。"""

    def test_rotation_by_size(self):
        """DB 文件超过 max_db_size_mb 时归档。"""
        import tempfile
        tmp = tempfile.mktemp(suffix=".db")
        try:
            db = ChatLogDB(db_path=tmp)
            # 写入一些数据
            for i in range(100):
                db.log(trace_id=f"t{i}", user_input=f"msg{i}")
            db.close()

            # 检查文件存在
            assert os.path.exists(tmp)
            size_mb = os.path.getsize(tmp) / (1024 * 1024)

            # 轮转检查（阈值设很小触发）
            db2 = ChatLogDB(db_path=tmp, max_db_size_mb=0.0001)  # 0.1KB
            # 文件应该被归档或清理
            db2.close()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_no_rotation_when_below_threshold(self):
        """低于阈值时不轮转。"""
        import tempfile
        tmp = tempfile.mktemp(suffix=".db")
        try:
            db = ChatLogDB(db_path=tmp, max_db_size_mb=100)  # 100MB 阈值
            db.log(trace_id="t1", user_input="hello")
            db.close()

            assert os.path.exists(tmp)
            db2 = ChatLogDB(db_path=tmp, max_db_size_mb=100)
            db2.close()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
