"""MemoryStore — SQLite + FTS5 事实存储，含信任评分和反馈。"""

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

_trust_clamp = lambda v: max(0.0, min(1.0, float(v)))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL UNIQUE,
    category        TEXT DEFAULT 'general',
    trust_score     REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    helpful_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(content, category, content=facts, content_rowid=fact_id);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, category)
        VALUES (new.fact_id, new.content, new.category);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, category)
        VALUES ('delete', old.fact_id, old.content, old.category);
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, category)
        VALUES ('delete', old.fact_id, old.content, old.category);
    INSERT INTO facts_fts(rowid, content, category)
        VALUES (new.fact_id, new.content, new.category);
END;
"""


class MemoryStore:
    """SQLite + FTS5 事实存储，支持全文检索、信任评分、反馈训练。"""

    def __init__(self, db_path: str | Path = ":memory:", default_trust: float = 0.3):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._default_trust = _trust_clamp(default_trust)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── 基本 CRUD ──────────────────────────────────────

    def add_fact(self, content: str, category: str = "general",
                 trust_score: float | None = None) -> int:
        """插入事实或返回已有 id（自动去重）。trust_score 不传时用默认值。"""
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
        ts = _trust_clamp(trust_score) if trust_score is not None else self._default_trust
        try:
            cur = self._conn.execute(
                "INSERT INTO facts (content, category, trust_score) VALUES (?, ?, ?)",
                (content, category, ts),
            )
            self._conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # 冲突合并：信任分取 max(已有, 新传入)
            if trust_score is not None:
                self._conn.execute(
                    "UPDATE facts SET trust_score = MAX(trust_score, ?) WHERE content = ?",
                    (ts, content),
                )
                self._conn.commit()
            row = self._conn.execute(
                "SELECT fact_id FROM facts WHERE content = ?", (content,)
            ).fetchone()
            return row["fact_id"]

    def search_facts(self, query: str, category: str | None = None,
                     limit: int = 10) -> list[dict[str, Any]]:
        """FTS5 全文检索 + LIKE 回退。命中后 retrieval_count++。"""
        if not query or not query.strip():
            return []

        # FTS5 MATCH first（带 boost）
        try:
            rows = self._conn.execute(
                """SELECT f.*, MAX(0.05, f.trust_score
                               - (julianday("now") - julianday(f.created_at)) * 0.01
                               + MIN(f.retrieval_count * 0.02, 0.2)) AS effective_score
                   FROM facts f
                   JOIN facts_fts ft ON ft.rowid = f.fact_id
                   WHERE facts_fts MATCH ?
                   ORDER BY effective_score DESC
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            if rows:
                results = [dict(r) for r in rows]
                self._increment_retrieval([r["fact_id"] for r in results])
                return results
        except sqlite3.OperationalError:
            pass

        # LIKE fallback（带 boost）
        rows = self._conn.execute(
            """SELECT *, MAX(0.05, trust_score
                          - (julianday("now") - julianday(created_at)) * 0.01
                          + MIN(retrieval_count * 0.02, 0.2)) AS effective_score
               FROM facts WHERE content LIKE ?
               ORDER BY effective_score DESC LIMIT ?""",
            (f"%{query}%", limit),
        ).fetchall()
        results = [dict(r) for r in rows]
        if results:
            self._increment_retrieval([r["fact_id"] for r in results])
        return results

    def _increment_retrieval(self, fact_ids: list[int]) -> None:
        """批量递增检索计数。"""
        if not fact_ids:
            return
        placeholders = ",".join("?" * len(fact_ids))
        self._conn.execute(
            f"UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id IN ({placeholders})",
            fact_ids,
        )
        self._conn.commit()

    def list_facts(self, category: str | None = None,
                   limit: int = 50) -> list[dict[str, Any]]:
        """列表查询，按信任评分降序。"""
        if category:
            rows = self._conn.execute(
                "SELECT * FROM facts WHERE category = ? ORDER BY trust_score DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM facts ORDER BY trust_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_fact(self, fact_id: int, content: str | None = None,
                    trust_delta: float | None = None,
                    category: str | None = None) -> bool:
        """更新事实部分字段。"""
        row = self._conn.execute(
            "SELECT fact_id, trust_score FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if not row:
            return False

        assignments = ["updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = []

        if content is not None:
            assignments.append("content = ?")
            params.append(content.strip())
        if trust_delta is not None:
            new_trust = _trust_clamp(row["trust_score"] + float(trust_delta))
            assignments.append("trust_score = ?")
            params.append(new_trust)
        if category is not None:
            assignments.append("category = ?")
            params.append(category)

        params.append(fact_id)
        self._conn.execute(
            f"UPDATE facts SET {', '.join(assignments)} WHERE fact_id = ?",
            params,
        )
        self._conn.commit()
        return True

    def remove_fact(self, fact_id: int) -> bool:
        """删除事实。"""
        cur = self._conn.execute(
            "DELETE FROM facts WHERE fact_id = ?", (fact_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    # ── 信任评分 ─────────────────────────────────────

    def record_feedback(self, fact_id: int, helpful: bool) -> dict[str, Any]:
        """记录反馈并调整信任评分。"""
        row = self._conn.execute(
            "SELECT fact_id, trust_score, helpful_count FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"fact_id {fact_id} not found")

        old_trust = row["trust_score"]
        delta = 0.05 if helpful else -0.10
        new_trust = _trust_clamp(old_trust + delta)
        helpful_inc = 1 if helpful else 0

        self._conn.execute(
            """UPDATE facts
               SET trust_score = ?, helpful_count = helpful_count + ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE fact_id = ?""",
            (new_trust, helpful_inc, fact_id),
        )
        self._conn.commit()

        return {
            "fact_id": fact_id,
            "old_trust": old_trust,
            "new_trust": new_trust,
            "helpful_count": row["helpful_count"] + helpful_inc,
        }

    # ── 轻量正则提取 ──────────────────────────────────

    # 疑问/无意义片段过滤
    _NOISE_PATTERN = re.compile(
        r'[？?！!]$'                        # 句末疑问/感叹
        r'|^[吗呢啥什么怎么哪儿谁哪为何干嘛]+$'  # 纯疑问词
        r'|^[的了呢啊吧吗嘛]+$'              # 纯语气词
        r'|^[、：；""''（）【】《》…—.,!?:;(){}-]+$'  # 纯标点/符号
    )

    @classmethod
    def _is_valid_fact(cls, text: str) -> bool:
        """过滤低质量事实片段：太短、疑问词、纯标点。"""
        if len(text) < 2:
            return False
        if cls._NOISE_PATTERN.search(text):
            return False
        # 去掉标点后至少有一个有效字符
        stripped = re.sub(r'[\s，。！？、：；""''（）【】《》…—.,!?:;(){}-]', '', text)
        return len(stripped) >= 1

    def extract_quick_facts(self, message: str) -> list[int]:
        """从用户消息中通过正则快速提取事实（零 API 成本，15 pattern）。"""
        patterns = [
            # 1-5: 偏好（保留）
            (re.compile(r"我(?:们)?(?:喜欢|偏好|需要|想(?:要|用))(.+)"), "user_pref"),
            (re.compile(r"我(?:们)?(?:的?)(?:favorite|首选|默认)\s*(?:是)?(.+)"), "user_pref"),
            (re.compile(r"I\s+(?:prefer|like|love|use|want|need)\s+(.+)", re.I), "user_pref"),
            (re.compile(r"my\s+(?:favorite|preferred|default)\s+\w+\s+is\s+(.+)", re.I), "user_pref"),
            (re.compile(r"记住(.+)"), "user_pref"),
            # 6: 住址
            (re.compile(r"我住在(.+)"), "user_pref"),
            # 7: 工作
            (re.compile(r"我在(.+)(?:工作|上班|公司)"), "project"),
            # 8: 职业（捕获完整职业名）
            (re.compile(r"我是(.+(?:工程师|设计师|程序员|医生|老师|学生))"), "user_pref"),
            # 9: 拥有（捕获完整事实）
            (re.compile(r"我有(.+)"), "user_pref"),
            # 10: 计划
            (re.compile(r"我(?:打算|计划|准备|想要)(.+)"), "user_pref"),
            # 11: 习惯
            (re.compile(r"我(?:每天|经常|偶尔)(.+)"), "user_pref"),
            # 12: 关系
            (re.compile(r"我(?:妈妈|爸爸|朋友|同事|老板)(.+)"), "general"),
            # 13: 负偏好
            (re.compile(r"我不(?:太|怎么)?(?:喜欢|想|要)(.+)"), "user_pref"),
            # 14: 位置（避开常见动词）
            (re.compile(r"我(?:在|去)([^，。,\.]{2,15})"), "user_pref"),
            # 15: 状态
            (re.compile(r"我(?:最近|刚刚|已经)(.+)"), "general"),
        ]
        extracted = []
        for pat, cat in patterns:
            m = pat.search(message)
            if m:
                text = m.group(1).strip() if m.lastindex else message[:200]
                if self._is_valid_fact(text):
                    fid = self.add_fact(text, category=cat)
                    extracted.append(fid)
        return extracted

    def close(self) -> None:
        self._conn.close()
