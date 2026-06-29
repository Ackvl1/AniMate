"""SessionStore — session 生命周期管理 (初始化、冻结、轮换、跨 session 检索)。"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_LOCAL_TZ = timezone(timedelta(hours=8))  # UTC+8，与 config.yaml timezone 对齐

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    parent_id   TEXT DEFAULT '',
    messages    TEXT NOT NULL DEFAULT '[]',
    active      INTEGER DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    frozen_at   TIMESTAMP NULL
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts USING fts5(
    session_id,
    role,
    content,
    tokenize='trigram'
);
"""

_MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    msg_index   INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
"""


def _utc_to_local(utc_str: str | None) -> str:
    """SQLite CURRENT_TIMESTAMP (UTC) → 本地时间字符串。"""
    if not utc_str:
        return ""
    try:
        utc_dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return utc_dt.astimezone(_LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return utc_str[:19] if utc_str else ""


class SessionStore:
    """管理 session 的生命周期：创建、冻结、轮换、跨 session 检索。"""

    def __init__(self, db_path: str | Path = ":memory:"):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_MESSAGES_SCHEMA)
        self._conn.executescript(_FTS_SCHEMA)
        self._conn.commit()

    def init_session(
        self, session_id: str, messages: list[dict], parent_id: str = ""
    ) -> None:
        """创建或覆盖一个 session，存储消息列表。"""
        self._conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, parent_id, messages, active)
               VALUES (?, ?, ?, 1)""",
            (session_id, parent_id, json.dumps(messages, ensure_ascii=False)),
        )
        # 同步写入 session_messages 表（FTS5 索引来源）
        self._sync_messages(session_id, messages)
        self._conn.commit()

    def _sync_messages(self, session_id: str, messages: list[dict]) -> None:
        """同步消息到 session_messages 和 FTS5 索引。"""
        # 删除旧消息
        self._conn.execute(
            "DELETE FROM session_messages WHERE session_id = ?", (session_id,)
        )
        # 同步删除 FTS5 中的旧消息
        self._conn.execute(
            "DELETE FROM session_messages_fts WHERE session_id = ?", (session_id,)
        )
        # 插入新消息
        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            content = msg.get("content", "")
            self._conn.execute(
                """INSERT INTO session_messages
                   (session_id, role, content, msg_index)
                   VALUES (?, ?, ?, ?)""",
                (session_id, role, content, i),
            )
            # 同步写入 FTS5
            self._conn.execute(
                """INSERT INTO session_messages_fts
                   (session_id, role, content)
                   VALUES (?, ?, ?)""",
                (session_id, role, content),
            )

    def load(self, session_id: str) -> list[dict]:
        """加载 session 的消息列表。不存在返回空列表。"""
        row = self._conn.execute(
            "SELECT messages FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return []
        return json.loads(row["messages"])

    def finalize(self, session_id: str) -> None:
        """冻结一个 session（标记为非活跃）。"""
        self._conn.execute(
            """UPDATE sessions
               SET active = 0, frozen_at = CURRENT_TIMESTAMP
               WHERE session_id = ? AND active = 1""",
            (session_id,),
        )
        self._conn.commit()

    def is_active(self, session_id: str) -> bool:
        """检查 session 是否活跃。"""
        row = self._conn.execute(
            "SELECT active FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return bool(row["active"]) if row else False

    def count(self) -> int:
        """返回 session 总数。"""
        return self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def list_sessions(self, active_only: bool = False) -> list[dict[str, Any]]:
        """列出所有 session。active_only=True 则仅活跃 session。时间戳已转换为本地时间。"""
        if active_only:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        sessions = [dict(r) for r in rows]
        for s in sessions:
            s["created_at"] = _utc_to_local(s.get("created_at"))
            frozen = s.get("frozen_at")
            if frozen:
                s["frozen_at"] = _utc_to_local(frozen)
        return sessions

    def save_messages(self, session_id: str, messages: list[dict]) -> None:
        """每轮对话后持久化消息列表到指定 session。"""
        self._conn.execute(
            "UPDATE sessions SET messages = ? WHERE session_id = ?",
            (json.dumps(messages, ensure_ascii=False), session_id),
        )
        # 同步 FTS5 索引
        self._sync_messages(session_id, messages)
        self._conn.commit()

    def ancestor_chain(self, session_id: str, max_depth: int = 50) -> list[str]:
        """从当前 session 沿 parent_id 向上遍历，返回祖先链（含自身）。"""
        chain = []
        visited = set()
        current = session_id
        while current and len(chain) < max_depth:
            if current in visited:
                break  # 环检测
            visited.add(current)
            row = self._conn.execute(
                "SELECT session_id, parent_id FROM sessions WHERE session_id = ?",
                (current,),
            ).fetchone()
            if row is None:
                break
            chain.append(row["session_id"])
            current = row["parent_id"] if row["parent_id"] else ""
        return chain

    def search_ancestors(self, session_id: str, query: str,
                          limit: int = 5, context_window: int = 1) -> list[dict[str, Any]]:
        """在当前 session 和所有祖先 session 中搜索消息。
        
        FTS5 trigram 全文索引 + BM25 相关性排序。
        空 query 时进入 Browse 模式，返回最近 session 列表。
        """
        if not query or not query.strip():
            return self._browse_sessions(limit=limit)
        
        chain = self.ancestor_chain(session_id)
        if not chain:
            return []

        # FTS5 trigram 搜索 + BM25 排序
        placeholders = ",".join("?" * len(chain))
        sql = f"""
            SELECT sm.session_id, sm.role, sm.content, sm.msg_index,
                   rank
            FROM session_messages_fts fts
            JOIN session_messages sm ON fts.rowid = sm.id
            WHERE session_messages_fts MATCH ? AND sm.session_id IN ({placeholders})
            ORDER BY rank
            LIMIT ?
        """
        params = [query] + chain + [limit * 3]  # 多取一些用于去重
        rows = self._conn.execute(sql, params).fetchall()
        
        # 去重（同一消息可能多次匹配）+ 取上下文
        seen = set()
        results = []
        for row in rows:
            key = (row["session_id"], row["msg_index"])
            if key in seen:
                continue
            
            # 获取上下文消息
            context_msgs = self._get_context(
                row["session_id"], row["msg_index"], context_window
            )
            for msg in context_msgs:
                msg_key = (msg["session_id"], msg["msg_index"])
                if msg_key not in seen:
                    seen.add(msg_key)
                    results.append({
                        "session_id": msg["session_id"],
                        "role": msg["role"],
                        "content": msg["content"],
                        "msg_index": msg["msg_index"],
                    })
            
            if len(results) >= limit:
                break
        
        return results[:limit]

    def _get_context(self, session_id: str, msg_index: int, window: int) -> list[dict]:
        """获取消息的上下文窗口。"""
        sql = """
            SELECT session_id, role, content, msg_index
            FROM session_messages
            WHERE session_id = ? AND msg_index BETWEEN ? AND ?
            ORDER BY msg_index
        """
        params = (session_id, max(0, msg_index - window), msg_index + window)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def _browse_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Browse 模式：返回最近 session 列表。"""
        sql = """
            SELECT s.session_id, s.created_at,
                   (SELECT content FROM session_messages 
                    WHERE session_id = s.session_id AND msg_index = 0 
                    LIMIT 1) as preview
            FROM sessions s
            ORDER BY s.created_at DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, (limit,)).fetchall()
        results = []
        for row in rows:
            results.append({
                "session_id": row["session_id"],
                "created_at": _utc_to_local(row["created_at"]),
                "preview": row["preview"] or "",
            })
        return results

    def close(self) -> None:
        self._conn.close()
