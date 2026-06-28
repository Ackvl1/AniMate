"""DiffHistory — 节点 diff 持久化（SQLite，独立文件，WAL mode）

独立 SQLite 文件，与 ChatLogDB 解耦：
- 用途：trace 回放 / debug 状态轨迹
- 生命周期：30 天 retention（与 chat_log.db 的 rotation 独立）
- 并发：WAL mode + 单连接 + asyncio.Lock 串行化写入
"""
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class DiffHistory:
    """持久化节点 diff 记录。

    7 字段 schema：trace_id, node_name, diff_json, inputs_json, events_json, duration_ms, created_at
    """

    def __init__(self, db_path: str | Path = "", retention_days: int = 30,
                 max_buffer: int = 100):
        if not db_path:
            from anima.core.paths import trace_dir
            db_path = str(trace_dir() / "diff_history.db")
        self._db_path = str(db_path)
        self._retention_days = retention_days
        self._max_buffer = max_buffer
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS diff_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                diff_json TEXT NOT NULL,
                inputs_json TEXT,
                events_json TEXT,
                duration_ms REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_diff_trace ON diff_history(trace_id);
            CREATE INDEX IF NOT EXISTS idx_diff_ts ON diff_history(created_at);
        """)
        self._conn.commit()

    async def record(self, node_name: str, diff: dict, trace_id: str,
                     inputs: dict | None = None, events: list | None = None,
                     duration_ms: float = 0) -> None:
        """异步记录一条 diff（进 buffer，达到 max_buffer 自动 flush）"""
        async with self._lock:
            self._buffer.append({
                "trace_id": trace_id,
                "node_name": node_name,
                "diff": diff,
                "inputs": inputs or {},
                "events": events or [],
                "duration_ms": duration_ms,
            })
            if len(self._buffer) >= self._max_buffer:
                await self._flush()

    async def _flush(self) -> None:
        """批量写入数据库"""
        if not self._buffer:
            return
        rows = [(
            r["trace_id"], r["node_name"],
            json.dumps(r["diff"], ensure_ascii=False),
            json.dumps(r["inputs"], ensure_ascii=False) if r["inputs"] else None,
            json.dumps(r["events"], ensure_ascii=False) if r["events"] else None,
            r["duration_ms"],
        ) for r in self._buffer]
        self._conn.executemany(
            "INSERT INTO diff_history (trace_id, node_name, diff_json, "
            "inputs_json, events_json, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            rows
        )
        self._conn.commit()
        self._buffer.clear()

    async def flush(self) -> None:
        """引擎结束时调用"""
        async with self._lock:
            await self._flush()

    def query(self, trace_id: str | None = None, limit: int = 50) -> list[dict]:
        """同步查询（replay 工具用，不争锁）"""
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM diff_history WHERE trace_id = ? "
                "ORDER BY id LIMIT ?", (trace_id, limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM diff_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{
            "trace_id": r["trace_id"],
            "node_name": r["node_name"],
            "diff": json.loads(r["diff_json"]),
            "inputs": json.loads(r["inputs_json"]) if r["inputs_json"] else None,
            "events": json.loads(r["events_json"]) if r["events_json"] else None,
            "duration_ms": r["duration_ms"],
            "created_at": r["created_at"],
        } for r in rows]

    def cleanup(self) -> int:
        """删除超过 retention_days 的记录"""
        cutoff = time.time() - self._retention_days * 86400
        cursor = self._conn.execute(
            "DELETE FROM diff_history WHERE "
            "strftime('%s', created_at) < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
