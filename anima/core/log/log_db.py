"""ChatLogDB — 聊天日志 + 阶段事件 + 长期记忆 SQLite 数据库。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def _hash_fact(text: str) -> str:
    """生成事实文本的 16 字符 hash 用作唯一键。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ChatLogDB:
    """轻量 SQLite 日志库，记录每次 chat 调用、阶段事件和长期记忆。"""

    def __init__(self, db_path: str | Path = "",
                 max_db_size_mb: float = 50.0,
                 max_age_days: int = 30):
        if not db_path:
            from anima.core.paths import logs_dir

            logs_dir().mkdir(parents=True, exist_ok=True)
            db_path = str(logs_dir() / "chat_log.db")
        self._db_path = str(db_path)
        self._rotate_if_needed(max_db_size_mb, max_age_days)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _rotate_if_needed(self, max_db_size_mb: float, max_age_days: int) -> None:
        """检查 DB 文件是否需要轮转（归档旧文件）。"""
        if not os.path.exists(self._db_path):
            return
        # 按大小检查
        size_mb = os.path.getsize(self._db_path) / (1024 * 1024)
        if size_mb >= max_db_size_mb:
            self._archive_db("size")
            return
        # 按时间检查（最早记录的年龄）
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                "SELECT MIN(created_at) FROM chat_logs"
            ).fetchone()
            conn.close()
            if row and row[0]:
                from datetime import datetime
                try:
                    oldest = datetime.fromisoformat(row[0])
                    age_days = (datetime.now() - oldest).days
                    if age_days >= max_age_days:
                        self._archive_db("age")
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass

    def _archive_db(self, reason: str) -> None:
        """归档当前 DB 文件（重命名）。"""
        import shutil
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = f"{self._db_path}.{reason}_{ts}.bak"
        try:
            shutil.copy2(self._db_path, archive_path)
            # 清空原文件（删除后重建）
            os.unlink(self._db_path)
        except Exception:
            pass  # 归档失败不影响主流程

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                user_input TEXT DEFAULT '',
                response_text TEXT DEFAULT '',
                emotion TEXT DEFAULT '',
                gesture TEXT DEFAULT '',
                llm_call_count INTEGER DEFAULT 0,
                total_duration_ms INTEGER DEFAULT 0,
                tool_calls TEXT DEFAULT '[]',
                engine_crashed INTEGER DEFAULT 0,
                node_failures TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS phase_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                phase_name TEXT NOT NULL,
                input_summary TEXT DEFAULT '',
                output_summary TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ok',
                error TEXT DEFAULT '',
                extra TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS long_term_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_hash TEXT UNIQUE NOT NULL,
                fact_text TEXT NOT NULL,
                source_trace TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_phase_trace ON phase_events(trace_id);
            CREATE INDEX IF NOT EXISTS idx_fact_hash ON long_term_facts(fact_hash);

            CREATE TABLE IF NOT EXISTS tool_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                input_args TEXT DEFAULT '{}',
                output_summary TEXT DEFAULT '',
                output_length INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                hitl_status TEXT DEFAULT 'auto',
                status TEXT DEFAULT 'success',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS compression_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                compress_count INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                before_tokens INTEGER DEFAULT 0,
                after_tokens INTEGER DEFAULT 0,
                head_rounds INTEGER DEFAULT 0,
                middle_msgs INTEGER DEFAULT 0,
                tail_rounds INTEGER DEFAULT 0,
                old_session_id TEXT DEFAULT '',
                new_session_id TEXT DEFAULT '',
                error_msg TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS emotion_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                sequence INTEGER DEFAULT 0,
                emotion TEXT DEFAULT '',
                gesture TEXT DEFAULT '',
                source TEXT DEFAULT 'inline',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_toolaudit_trace ON tool_audit(trace_id);
            CREATE INDEX IF NOT EXISTS idx_compression_trace ON compression_logs(trace_id);
            CREATE INDEX IF NOT EXISTS idx_emotion_trace ON emotion_logs(trace_id);
        """)
        self._conn.commit()

        # 向后兼容：给已存在的 chat_logs 表加新列
        for col, default in [
            ("engine_crashed", "0"),
            ("node_failures", "'[]'"),
        ]:
            try:
                self._conn.execute(
                    f"ALTER TABLE chat_logs ADD COLUMN {col} DEFAULT {default}"
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # 列已存在

    # ── Chat Logs ──────────────────────────────────────

    def log(
        self,
        trace_id: str,
        user_input: str = "",
        response_text: str = "",
        emotion: str = "",
        gesture: str = "",
        llm_call_count: int = 0,
        total_duration_ms: int = 0,
        tool_calls: list[dict] | None = None,
        engine_crashed: int = 0,
        node_failures: str = "[]",
    ) -> int:
        """写入一条聊天日志。返回插入的 id。"""
        cur = self._conn.execute(
            """INSERT INTO chat_logs
               (trace_id, user_input, response_text, emotion, gesture,
                llm_call_count, total_duration_ms, tool_calls,
                engine_crashed, node_failures)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_id,
                user_input,
                response_text,
                emotion,
                gesture,
                llm_call_count,
                total_duration_ms,
                json.dumps(tool_calls or [], ensure_ascii=False),
                engine_crashed,
                node_failures,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def query(self, limit: int = 50, trace_id: str | None = None) -> list[dict[str, Any]]:
        """查询聊天日志。"""
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM chat_logs WHERE trace_id = ? ORDER BY id DESC LIMIT ?",
                (trace_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM chat_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        """返回聊天日志总数。"""
        return self._conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0]

    def clear(self) -> None:
        """清空所有聊天日志。"""
        self._conn.execute("DELETE FROM chat_logs")
        self._conn.commit()

    # ── Phase Events ───────────────────────────────────

    def log_phase(
        self,
        trace_id: str,
        phase_name: str,
        input_summary: str = "",
        output_summary: str = "",
        duration_ms: int = 0,
        status: str = "ok",
        error: str = "",
        extra: dict | None = None,
    ) -> int:
        """写入一条阶段事件日志。返回插入的 id。"""
        cur = self._conn.execute(
            """INSERT INTO phase_events
               (trace_id, phase_name, input_summary, output_summary,
                duration_ms, status, error, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_id,
                phase_name,
                input_summary,
                output_summary,
                duration_ms,
                status,
                error,
                json.dumps(extra or {}, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def query_phases(
        self, trace_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """查询阶段事件日志。"""
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM phase_events WHERE trace_id = ? ORDER BY id DESC LIMIT ?",
                (trace_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM phase_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_phases(self) -> int:
        """返回阶段事件总数。"""
        return self._conn.execute("SELECT COUNT(*) FROM phase_events").fetchone()[0]

    def clear_phases(self) -> None:
        """清空所有阶段事件。"""
        self._conn.execute("DELETE FROM phase_events")
        self._conn.commit()

    # ── Long-term Facts ────────────────────────────────

    def add_fact(self, fact_text: str, source_trace: str) -> int:
        """插入一条长期记忆事实。自动去重（相同事实只保留一条）。返回 id。"""
        fh = _hash_fact(fact_text)
        try:
            cur = self._conn.execute(
                """INSERT INTO long_term_facts (fact_hash, fact_text, source_trace)
                   VALUES (?, ?, ?)""",
                (fh, fact_text, source_trace),
            )
            self._conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # 重复事实，更新 updated_at 和 source_trace
            self._conn.execute(
                """UPDATE long_term_facts
                   SET source_trace = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE fact_hash = ?""",
                (source_trace, fh),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM long_term_facts WHERE fact_hash = ?", (fh,)
            ).fetchone()
            return row["id"] if row else -1

    def query_facts(self, limit: int = 50) -> list[dict[str, Any]]:
        """查询长期记忆事实。按 id 降序（最新在前）。"""
        rows = self._conn.execute(
            "SELECT * FROM long_term_facts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def query_facts_by_text(self, keyword: str) -> list[dict[str, Any]]:
        """按关键词模糊查询事实。"""
        rows = self._conn.execute(
            "SELECT * FROM long_term_facts WHERE fact_text LIKE ? ORDER BY id DESC",
            (f"%{keyword}%",),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_facts(self) -> int:
        """返回事实总数。"""
        return self._conn.execute("SELECT COUNT(*) FROM long_term_facts").fetchone()[0]

    def clear_facts(self) -> None:
        """清空所有长期记忆事实。"""
        self._conn.execute("DELETE FROM long_term_facts")
        self._conn.commit()

    def delete_fact(self, fact_id: int) -> None:
        """按 id 删除一条事实。"""
        self._conn.execute("DELETE FROM long_term_facts WHERE id = ?", (fact_id,))
        self._conn.commit()

    # ── Tool Audit ────────────────────────────────────

    def log_tool_audit(
        self,
        trace_id: str,
        tool_name: str,
        input_args: str = "{}",
        output_summary: str = "",
        output_length: int = 0,
        duration_ms: int = 0,
        hitl_status: str = "auto",
        status: str = "success",
    ) -> int:
        """写入工具审计记录。"""
        cur = self._conn.execute(
            """INSERT INTO tool_audit
               (trace_id, tool_name, input_args, output_summary,
                output_length, duration_ms, hitl_status, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, tool_name, input_args, output_summary,
             output_length, duration_ms, hitl_status, status),
        )
        self._conn.commit()
        return cur.lastrowid

    def query_tool_audit(self, trace_id: str | None = None,
                         limit: int = 50) -> list[dict[str, Any]]:
        """查询工具审计记录。"""
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM tool_audit WHERE trace_id = ? ORDER BY id DESC LIMIT ?",
                (trace_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tool_audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Compression Logs ──────────────────────────────

    def log_compression(
        self,
        trace_id: str,
        compress_count: int = 0,
        success: bool = True,
        before_tokens: int = 0,
        after_tokens: int = 0,
        head_rounds: int = 0,
        middle_msgs: int = 0,
        tail_rounds: int = 0,
        old_session_id: str = "",
        new_session_id: str = "",
        error_msg: str = "",
        duration_ms: int = 0,
    ) -> int:
        """写入压缩记录。"""
        cur = self._conn.execute(
            """INSERT INTO compression_logs
               (trace_id, compress_count, success, before_tokens, after_tokens,
                head_rounds, middle_msgs, tail_rounds, old_session_id,
                new_session_id, error_msg, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, compress_count, int(success), before_tokens, after_tokens,
             head_rounds, middle_msgs, tail_rounds, old_session_id,
             new_session_id, error_msg, duration_ms),
        )
        self._conn.commit()
        return cur.lastrowid

    def query_compression(self, trace_id: str | None = None,
                          limit: int = 50) -> list[dict[str, Any]]:
        """查询压缩记录。"""
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM compression_logs WHERE trace_id = ? ORDER BY id DESC LIMIT ?",
                (trace_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM compression_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Emotion Logs ──────────────────────────────────

    def log_emotion(
        self,
        trace_id: str,
        sequence: int = 0,
        emotion: str = "",
        gesture: str = "",
        source: str = "inline",
    ) -> int:
        """写入情绪变化记录。"""
        cur = self._conn.execute(
            """INSERT INTO emotion_logs
               (trace_id, sequence, emotion, gesture, source)
               VALUES (?, ?, ?, ?, ?)""",
            (trace_id, sequence, emotion, gesture, source),
        )
        self._conn.commit()
        return cur.lastrowid

    def query_emotions(self, trace_id: str | None = None,
                       limit: int = 50) -> list[dict[str, Any]]:
        """查询情绪变化日志。"""
        if trace_id:
            rows = self._conn.execute(
                "SELECT * FROM emotion_logs WHERE trace_id = ? ORDER BY sequence LIMIT ?",
                (trace_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM emotion_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 生命周期 ──────────────────────────────────────

    def close(self):
        self._conn.close()
