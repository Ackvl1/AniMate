"""LogCollector — 审计事件分派器。

接收 emit 事件和直接调用，将审计数据写入 ChatLogDB。
Node 层无感知，所有 Node 继续 emit()。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anima.core.engine.node import AgentEvent
    from anima.core.log.log_db import ChatLogDB


class LogCollector:
    """审计日志收口：将 emit 事件和组件直接调用映射到 ChatLogDB 对应方法。

    职责：
      - handle(event): 从 emit 事件流中识别审计事件并写库
      - log_compression(...): ContextManager 无 event，直接调用
      - log_fact_change(...): MemoryProvider 写入事实后直接调用
    """

    def __init__(self, log_db: "ChatLogDB"):
        self._db = log_db
        self._tool_start_cache: dict[str, dict] = {}
        self._tool_call_counter: int = 0

    # ── 事件分派入口 ─────────────────────────────────

    def handle(self, event: "AgentEvent") -> None:
        """从 emit 事件流中分派审计事件。"""
        t = event.type
        if t == "tool.start":
            self._on_tool_start(event)
        elif t == "tool.done":
            self._on_tool_done(event)
        elif t == "tool.denied":
            self._on_tool_denied(event)
        elif t == "emotion.update":
            self._on_emotion_update(event)

    # ── 工具审计 ─────────────────────────────────

    def _on_tool_start(self, ev: "AgentEvent") -> None:
        """工具开始执行：记录入参和开始时间。"""
        name = ev.data.get("name", "")
        trace_id = ev.data.get("trace_id", "")
        # 用 trace_id + name 作 key，避免并发同名工具覆盖
        cache_key = f"{trace_id}:{name}"
        self._tool_start_cache[cache_key] = {
            "args": ev.data.get("arguments", {}),
            "start": time.time(),
        }

    def _on_tool_done(self, ev: "AgentEvent") -> None:
        """工具执行完成：写 tool_audit 表。"""
        name = ev.data.get("name", "")
        trace_id = ev.data.get("trace_id", "")
        cache_key = f"{trace_id}:{name}"
        cache = self._tool_start_cache.pop(cache_key, {})
        output = ev.data.get("result", "")
        duration_ms = int((time.time() - cache.get("start", time.time())) * 1000)

        self._db.log_tool_audit(
            trace_id=ev.data.get("trace_id", ""),
            tool_name=name,
            input_args=str(cache.get("args", {})),
            output_summary=str(output)[:200],
            output_length=len(str(output)),
            duration_ms=duration_ms,
            status=ev.data.get("status", "success"),
        )

    def _on_tool_denied(self, ev: "AgentEvent") -> None:
        """工具被用户拒绝：写 audit 但标记 status=denied。"""
        name = ev.data.get("name", "")
        trace_id = ev.data.get("trace_id", "")
        cache_key = f"{trace_id}:{name}"
        cache = self._tool_start_cache.pop(cache_key, {})
        duration_ms = int((time.time() - cache.get("start", time.time())) * 1000)
        self._db.log_tool_audit(
            trace_id=ev.data.get("trace_id", ""),
            tool_name=name,
            input_args=str(cache.get("args", {})),
            output_summary="(user denied)",
            output_length=0,
            duration_ms=duration_ms,
            hitl_status="denied",
            status="denied",
        )

    # ── 情绪审计 ─────────────────────────────────

    def _on_emotion_update(self, ev: "AgentEvent") -> None:
        """情绪变化：写 emotion_logs 表。"""
        self._db.log_emotion(
            trace_id=ev.data.get("trace_id", ""),
            emotion=ev.data.get("emotion", ""),
            gesture=ev.data.get("gesture", ""),
            source="inline",
        )

    # ── 压缩审计（无 event，由 ContextManager 直接调用）──

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
    ) -> None:
        """压缩事件：写 compression_logs 表。"""
        self._db.log_compression(
            trace_id=trace_id,
            compress_count=compress_count,
            success=success,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            head_rounds=head_rounds,
            middle_msgs=middle_msgs,
            tail_rounds=tail_rounds,
            old_session_id=old_session_id,
            new_session_id=new_session_id,
            error_msg=error_msg,
            duration_ms=duration_ms,
        )

    # ── 事实审计（无 event，由 MemoryProvider 直接调用）──

    def log_fact_change(self, fact_text: str, source_trace: str) -> None:
        """事实变更：写 long_term_facts 表。"""
        self._db.add_fact(fact_text=fact_text, source_trace=source_trace)
