"""ContextManager — token 跟踪 + 压缩决策 + 渐进压缩管道。"""

import logging
from typing import Any

from animate.core.context.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class ContextManager:
    """管理对话上下文的 token 预算和渐进压缩。

    用法:
        cm = ContextManager(model_limit=1_000_000)
        cm.update_from_response({"total_tokens": usage})
        if cm.need_compress():
            cm.compress(messages, ctx)
    """

    def __init__(
        self,
        model_limit: int | None = None,
        threshold: float | None = None,
        compact_reserve: int | None = None,
        head_rounds: int | None = None,
        tail_rounds: int | None = None,
        llm=None,
        session_store=None,
    ):
        # 从 config.yaml 加载默认值
        from animate.core.config import get_compress_config
        cfg = get_compress_config()
        self._model_limit = model_limit if model_limit is not None else cfg["model_limit"]
        self._compact_reserve = compact_reserve if compact_reserve is not None else cfg["compact_reserve"]
        self._effective_window = self._model_limit - self._compact_reserve
        self._threshold = int(self._effective_window * (threshold if threshold is not None else cfg["threshold"]))
        self._head_rounds = head_rounds if head_rounds is not None else cfg["head_rounds"]
        self._tail_rounds = tail_rounds if tail_rounds is not None else cfg["tail_rounds"]
        self._llm = llm
        self._session_store = session_store
        self._accumulated = 0
        self._compact_failures = 0
        self._compact_max_failures = 3
        self._compress_count = 0

    def update_from_response(self, usage: dict) -> None:
        """每轮 API 返回后更新累计 token。"""
        total = usage.get("total_tokens", 0)
        if total:
            self._accumulated += total

    def need_compress(self) -> bool:
        """是否达到压缩阈值。"""
        return self._accumulated > self._threshold

    def compress(self, messages: list[dict], ctx: dict | None = None,
                 session_id: str | None = None) -> str | None:
        """执行渐进压缩管道。返回新 session_id（如果旋转了），否则 None。"""
        if len(messages) < (self._head_rounds + self._tail_rounds) * 2:
            logger.info("compress: 消息轮数过少，跳过")
            return None

        head = self._select_head(messages)
        tail = self._select_tail(messages)
        middle = [i for i in range(len(messages)) if i not in head and i not in tail]

        if len(middle) < 2:
            logger.info("compress: 中间无消息可压")
            return None

        # L1: Snip 工具结果
        self._snip_tool_results(messages, middle)

        # L4: LLM 摘要
        compact_ok = False
        if self._llm:
            compact_ok = self._auto_compact(messages, head, tail, middle, ctx or {})

        if not compact_ok:
            return None  # 摘要失败，不旋转

        self._compress_count += 1

        # 压缩成功，重置累计值
        self._accumulated = 0

        # Session rotation
        if session_id and self._session_store:
            old_sid = session_id
            new_sid = f"{old_sid}_c{self._compress_count}"
            self._session_store.finalize(old_sid)
            self._session_store.init_session(
                new_sid, list(messages), parent_id=old_sid
            )
            logger.info("session rotated: %s → %s", old_sid, new_sid)
            return new_sid

        return None

    def _select_head(self, messages: list[dict]) -> set[int]:
        """保护所有非 x_compressible 的 system prompt + 最早 head_rounds 轮非 system 消息。"""
        protected = {i for i, m in enumerate(messages)
                     if m["role"] == "system" and not m.get("x_compressible")}
        rounds = 0
        for i, m in enumerate(messages):
            if m.get("x_compressible"):
                continue
            if m["role"] == "system":
                continue
            protected.add(i)
            if m["role"] == "assistant":
                rounds += 1
                if rounds >= self._head_rounds:
                    break
        return protected

    def _select_tail(self, messages: list[dict]) -> set[int]:
        """保护最近 tail_rounds 轮 + 最后一条消息（跳过 x_compressible）。"""
        protected = set()
        rounds = 0
        for i in range(len(messages) - 1, -1, -1):
            protected.add(i)
            if messages[i]["role"] == "user" and not messages[i].get("x_compressible"):
                rounds += 1
                if rounds >= self._tail_rounds:
                    break
        return protected

    def _snip_tool_results(self, messages: list[dict], indices: set[int]) -> None:
        """替换大工具结果和超大 tool_call arguments 为占位符。"""
        RESULT_THRESHOLD = 500
        ARGS_THRESHOLD = 2000
        for i in indices:
            m = messages[i]
            # 截断 tool_call arguments
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    args_str = tc.get("function", {}).get("arguments", "")
                    if len(args_str) > ARGS_THRESHOLD:
                        tc["function"]["arguments"] = args_str[:ARGS_THRESHOLD] + "[参数过长，已省略]"
            # 截断 tool result
            elif m.get("role") == "tool" and len(str(m.get("content", ""))) > RESULT_THRESHOLD:
                m["content"] = "[工具结果较长，已压缩]"

    def _auto_compact(
        self,
        messages: list[dict], head: set[int], tail: set[int],
        middle_indices: list[int] | set[int],
        ctx: dict | None = None,
    ) -> bool:
        """LLM 摘要替换中间段落。返回 True 成功，False 失败。"""
        if not middle_indices:
            return False
        middle_msgs = [messages[i] for i in sorted(middle_indices)]

        # 构造摘要 prompt（按 token 预算均分）
        total_budget = 8000  # 约 2K tokens 的摘要输入预算
        per_msg = total_budget // max(len(middle_msgs), 1)

        emotion_log = ctx.get("emotion_log", [])
        emotion_section = ""
        if emotion_log:
            emotion_section = "## 情绪变化记录\n" + "\n".join(
                f"- 第 {e.get('turn', '?')} 轮: {e.get('emotion', '?')}" for e in emotion_log
            )

        prompt = (
            "你正在压缩一段对话历史。请生成结构化摘要：\n\n"
            "## 已解决事项\n（已完成的任务、已回答的问题）\n\n"
            "## 活跃中事项\n（当前仍在进行的事项）\n\n"
            "## 用户偏好与约定\n（用户表达的喜好、习惯、约定）\n\n"
            f"{emotion_section}\n\n"
            "## 关键决策\n（做出的重要选择及理由）\n\n"
            "对话内容：\n"
        )
        for m in middle_msgs:
            role = m.get("role", "unknown")
            content = str(m.get("content", ""))[:per_msg]
            prompt += f"\n{role}: {content}"

        try:
            result = self._llm.chat([{"role": "user", "content": prompt}])
            summary = result.content.strip()
        except Exception as e:
            logger.warning("LLM 摘要失败: %s", e)
            self._compact_failures += 1
            return False

        if not summary:
            return False

        # 替换 middle 区域
        new_messages = [messages[i] for i in sorted(head | tail)]
        insert_pos = min(middle_indices)
        new_messages.insert(
            insert_pos,
            {
                "role": "system",
                "content": f"[对话历史压缩 #{self._compress_count + 1}]\n{summary}",
                "x_compressible": True,
            },
        )
        messages.clear()
        messages.extend(new_messages)
        return True

    def _fail_or_degrade(self) -> bool:
        """检查是否超过最大失败次数。返回 True 表示应报错。"""
        if self._compact_failures >= self._compact_max_failures:
            raise RuntimeError(
                f"压缩连续失败 {self._compact_failures} 次，请检查 API 状态或 /reset"
            )
        return False

    def reset(self) -> None:
        """重置累计值。"""
        self._accumulated = 0
        self._compact_failures = 0
        self._compress_count = 0
