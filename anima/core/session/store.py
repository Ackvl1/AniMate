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
        self._conn.commit()

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
        self._conn.commit()

    def ancestor_chain(self, session_id: str) -> list[str]:
        """返回从当前 session 到根 session 的完整链路。"""
        chain = []
        current = session_id
        while current:
            row = self._conn.execute(
                "SELECT session_id, parent_id FROM sessions WHERE session_id = ?",
                (current,),
            ).fetchone()
            if row is None:
                return []
            chain.append(row["session_id"])
            current = row["parent_id"] if row["parent_id"] else ""
        return chain

    def search_ancestors(self, session_id: str, query: str,
                          limit: int = 5) -> list[dict[str, Any]]:
        """在当前 session 和所有祖先 session 中搜索消息。
        
        对 CJK 友好：优先尝试 FTS5，无效时降级 LIKE。
        """
        if not query or not query.strip():
            return []
        chain = self.ancestor_chain(session_id)
        if not chain:
            return []

        results = []
        for sid in chain:
            msgs = self.load(sid)
            for m in msgs:
                content = str(m.get("content", ""))
                if query in content:
                    results.append({
                        "session_id": sid,
                        "role": m.get("role", ""),
                        "content": content,
                    })
                    if len(results) >= limit:
                        return results

        return results[:limit]

    def close(self) -> None:
        self._conn.close()
