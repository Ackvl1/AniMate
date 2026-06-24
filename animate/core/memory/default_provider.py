"""DefaultMemoryProvider — MemoryProvider 的基础 SQLite 实现。"""

from __future__ import annotations

import json
import logging
from typing import Any

from animate.core.memory.provider import MemoryProvider
from animate.core.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class DefaultMemoryProvider(MemoryProvider):
    """基于 MemoryStore (SQLite + FTS5) 的默认长期记忆实现。"""

    def __init__(self, store: MemoryStore | None = None, log_db=None):
        self._store = store or MemoryStore()
        self._log_db = log_db
        self._session_id: str = ""

    @property
    def name(self) -> str:
        return "default"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id

    def on_session_switch(self, new_session_id: str, old_session_id: str) -> None:
        """session rotation 时更新内部 session_id 跟踪。"""
        logger.debug("[memory] session switch: %s → %s", old_session_id, new_session_id)
        self._session_id = new_session_id

    def prefetch(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """每轮对话前检索相关长期事实。

        先用全文 FTS5 搜索，如果没结果则拆成单字/词逐个 LIKE 搜索，
        解决中文整句 FTS5 AND 语义匹配不到短事实的问题。
        """
        # 第一轮：FTS5 直接搜
        results = self._store.search_facts(query, limit=limit)
        if results:
            return results

        # 第二轮：滑动窗口提取 2-3 字符片段逐个 LIKE 搜
        import re as _re
        tokens = []
        for m in _re.finditer(r"[\u4e00-\u9fff]+|[a-zA-Z]{3,}", query):
            s = m.group()
            if _re.match(r"[a-zA-Z]", s):
                tokens.append(s)
            else:
                for size in (3, 2):
                    for i in range(len(s) - size + 1):
                        tokens.append(s[i : i + size])
        seen = set()
        for token in tokens:
            if len(token) < 2:
                continue
            hits = self._store.search_facts(token, limit=limit)
            for h in hits:
                if h["fact_id"] not in seen:
                    seen.add(h["fact_id"])
                    results.append(h)
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break

        return results[:limit]

    def sync_turn(self, user_content: str, assistant_content: str,
                  **kwargs) -> None:
        """每轮对话后轻量 regex 提取（零 API 成本）。"""
        if user_content:
            extracted = self._store.extract_quick_facts(user_content)
            if extracted:
                logger.debug("[memory] extracted %d facts from user message", len(extracted))

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "fact_store",
                "description": (
                    "管理长期记忆。可添加、搜索、查看、更新、删除事实。\n"
                    "action: add(添加) / search(搜索) / list(列表) / update(更新) / remove(删除)"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "search", "list", "update", "remove"],
                            "description": "操作类型",
                        },
                        "content": {
                            "type": "string",
                            "description": "事实内容（add 时需要）",
                        },
                        "query": {
                            "type": "string",
                            "description": "搜索关键字（search 时需要）",
                        },
                        "fact_id": {
                            "type": "integer",
                            "description": "事实 ID（update/remove 时需要）",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["user_pref", "project", "general"],
                            "description": "事实分类",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "fact_feedback",
                "description": (
                    "对已存储的事实给出反馈。helpful=True 表示事实有用，"
                    "helpful=False 表示事实不准确或过时。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fact_id": {
                            "type": "integer",
                            "description": "事实 ID",
                        },
                        "helpful": {
                            "type": "boolean",
                            "description": "true=有用, false=不准确/过时",
                        },
                    },
                    "required": ["fact_id", "helpful"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "fact_store":
            return self._handle_fact_store(args)
        elif tool_name == "fact_feedback":
            return self._handle_fact_feedback(args)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _handle_fact_store(self, args: dict) -> str:
        try:
            action = args["action"]
            if action == "add":
                fid = self._store.add_fact(
                    args["content"],
                    category=args.get("category", "general"),
                )
                if self._log_db:
                    self._log_db.add_fact(
                        fact_text=args["content"],
                        source_trace=self._session_id or "cli",
                    )
                return json.dumps({"fact_id": fid, "status": "added"})
            elif action == "search":
                results = self._store.search_facts(
                    args["query"],
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})
            elif action == "list":
                results = self._store.list_facts(
                    category=args.get("category"),
                    limit=int(args.get("limit", 20)),
                )
                return json.dumps({"facts": results, "count": len(results)})
            elif action == "update":
                updated = self._store.update_fact(
                    int(args["fact_id"]),
                    content=args.get("content"),
                    trust_delta=float(args["trust_delta"]) if "trust_delta" in args else None,
                    category=args.get("category"),
                )
                return json.dumps({"updated": updated})
            elif action == "remove":
                removed = self._store.remove_fact(int(args["fact_id"]))
                return json.dumps({"removed": removed})
            else:
                return json.dumps({"error": f"Unknown action: {action}"})
        except KeyError as e:
            return json.dumps({"error": f"Missing required argument: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _handle_fact_feedback(self, args: dict) -> str:
        try:
            result = self._store.record_feedback(
                int(args["fact_id"]),
                helpful=args["helpful"],
            )
            return json.dumps(result)
        except KeyError as e:
            return json.dumps({"error": f"Missing required argument: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def shutdown(self) -> None:
        self._store.close()
