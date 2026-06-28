"""DefaultMemoryProvider — MemoryProvider 的基础 SQLite 实现。"""

from __future__ import annotations

import json
import logging
from typing import Any

import re as _re
from animate.core.memory.provider import MemoryProvider
from animate.core.memory.store import MemoryStore

logger = logging.getLogger(__name__)


# ── Session End 提取 ──────────────────────────────────────────

EXTRACT_PROMPT_TEMPLATE = (
    "你是一个事实提取器。从以下对话中提取关于用户的稳定事实和偏好。\n"
    "规则：\n"
    "- 只提取关于用户（user）的客观事实，不提取角色（assistant）的表演性台词\n"
    "- 事实用第三人称客观陈述（如\"用户喜欢音乐\"而非\"我觉得用户喜欢音乐\"）\n"
    "- 忽略寒暄、命令、无信息量的消息\n"
    "- 如果没有可提取的事实，返回空列表\n"
    "{domain_hint}\n"
    "返回 JSON 格式：\n"
    '{{"facts": [{{"content": "事实内容", "category": "user_pref|project|general"}}]}}\n'
    "对话：\n"
    "{conversation}\n"
)

_DOMAIN_KEYWORDS = {
    "saki": "关注领域：音乐、乐队、钢琴、人际关系、情感偏好、生活习惯",
}


def _build_domain_hint(persona_name=None):
    if not persona_name:
        return ""
    hint = _DOMAIN_KEYWORDS.get(persona_name)
    return f"\n特别关注：{hint}" if hint else ""


class DefaultMemoryProvider(MemoryProvider):
    """基于 MemoryStore (SQLite + FTS5) 的默认长期记忆实现。"""

    def __init__(self, store: MemoryStore | None = None, log_db=None,
                 persona_name: str | None = None):
        self._store = store or MemoryStore()
        self._log_db = log_db
        self._session_id: str = ""
        self._persona_name = persona_name

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

    def on_session_end(self, messages: list[dict], llm=None) -> None:
        """会话结束时 LLM 深度提取长期事实。同步调用，异常不阻断 reset。"""
        if llm is None:
            return
        # 1. 过滤：user 消息 < 4 条 → 跳过
        user_count = sum(1 for m in messages if m.get("role") == "user")
        if user_count < 4:
            logger.debug("[memory] on_session_end: only %d user msgs, skip", user_count)
            return
        # 2. 格式化完整对话
        conversation = self._format_conversation(messages)
        # 3. 构建 prompt（角色领域关键词注入）
        domain_hint = _build_domain_hint(getattr(self, "_persona_name", None))
        prompt = EXTRACT_PROMPT_TEMPLATE.format(
            domain_hint=domain_hint,
            conversation=conversation,
        )
        try:
            # 4. LLM 提取（同步）
            result = llm.chat([
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请提取上述对话中的事实。"},
            ])
            raw = result.content.strip()
            # 5. 解析 JSON
            json_str = raw.removeprefix("```json").removesuffix("```").strip()
            data = json.loads(json_str)
            facts = data.get("facts", [])
            # 6. 逐条归一化 + 入库
            extracted_count = 0
            for f in facts:
                content = self._normalize_fact(f.get("content", ""))
                if not content or len(content) < 2:
                    continue
                category = f.get("category", "general")
                if category not in ("user_pref", "project", "general"):
                    category = "general"
                # 7. 双写：状态层 + 审计层
                fid = self._store.add_fact(content, category=category, trust_score=0.7)
                if self._log_db:
                    self._log_db.add_fact(
                        fact_text=content,
                        source_trace="session_end",
                    )
                extracted_count += 1
                logger.info("[memory] on_session_end extracted: %s (fid=%d)", content[:50], fid)
            logger.info("[memory] on_session_end: extracted %d facts from %d msgs",
                        extracted_count, len(messages))
        except Exception as e:
            logger.warning("[memory] on_session_end LLM extraction failed: %s", e)

    @staticmethod
    def _format_conversation(messages: list[dict]) -> str:
        """格式化完整对话为 LLM 可读文本。"""
        lines = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("user", "assistant") and content.strip():
                label = "用户" if role == "user" else "角色"
                text = content[:2000]
                lines.append(f"{label}: {text}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_fact(text: str) -> str:
        """文本归一化：全/半角统一 + 常见缩写展开 + 去尾标点。"""
        # 全角数字→半角
        for fw, hw in zip("０１２３４５６７８９", "0123456789"):
            text = text.replace(fw, hw)
        # 常见缩写展开
        for abbr, full in {"SC2": "星际争霸2", "SCII": "星际争霸2", "BD": "邦邦梦想"}.items():
            text = _re.sub(rf"\b{abbr}\b", full, text)
        # 去首尾空白和尾部标点
        return text.strip().rstrip("。，！？.!?;；").strip()
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
