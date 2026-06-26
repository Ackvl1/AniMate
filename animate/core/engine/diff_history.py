"""DiffHistory — 节点 diff 持久化（SQLite）"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class DiffHistory:
    """持久化节点 diff 记录"""
    
    def __init__(self, db_path: str = "diff_history.db", retention_days: int = 30):
        self.db_path = db_path
        self.retention_days = retention_days
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
    
    def _init_db(self):
        """创建表结构"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS diff_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                node TEXT NOT NULL,
                diff TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_diff_history_trace_id ON diff_history(trace_id);
            CREATE INDEX IF NOT EXISTS idx_diff_history_ts ON diff_history(ts);
        """)
        self.conn.commit()
    
    def save_records(self, records: list[dict]) -> None:
        """保存 diff 记录"""
        if not records:
            return
        
        for record in records:
            trace_id = record.get("trace_id", "")
            node = record.get("node", "")
            diff = json.dumps(record.get("diff", {}), ensure_ascii=False)
            ts = record.get("ts", time.time())
            
            self.conn.execute(
                "INSERT INTO diff_history (trace_id, node, diff, ts) VALUES (?, ?, ?, ?)",
                (trace_id, node, diff, ts)
            )
        self.conn.commit()
    
    def query(
        self,
        trace_id: str | None = None,
        since: float | None = None,
        before: float | None = None,
    ) -> list[dict]:
        """查询 diff 记录"""
        sql = "SELECT * FROM diff_history WHERE 1=1"
        params: list[Any] = []
        
        if trace_id:
            sql += " AND trace_id = ?"
            params.append(trace_id)
        
        if since is not None:
            sql += " AND ts >= ?"
            params.append(since)
        
        if before is not None:
            sql += " AND ts <= ?"
            params.append(before)
        
        sql += " ORDER BY ts"
        
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "trace_id": row["trace_id"],
                "node": row["node"],
                "diff": json.loads(row["diff"]),
                "ts": row["ts"],
            }
            for row in rows
        ]
    
    def cleanup(self) -> int:
        """删除超过 retention_days 的记录，返回删除数量"""
        cutoff = time.time() - self.retention_days * 86400
        cursor = self.conn.execute("DELETE FROM diff_history WHERE ts < ?", (cutoff,))
        self.conn.commit()
        return cursor.rowcount
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
