"""PhaseEventLogger — 将 Agent 事件流转为结构化日志。

通过拦截 AgentEvent 流，自动写入：
  - phase_events 表（每个 Node 的耗时/状态/产出）
  - chat_logs 表 （每次 chat 的汇总）

支持 BSP 并行节点的多计时器 + 延迟批量写入。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from animate.core.log import ChatLogDB
    from animate.core.engine.context import RunContext

_FLUSH_THRESHOLD = 20  # buffer 超过此条数时自动 flush


class PhaseEventLogger:
    """记录 chat 和 node 事件到 ChatLogDB。

    多计时器设计：BSP 并行节点可同时有多个活跃计时器，互不干扰。
    延迟写入：事件先缓冲到 _event_buffer，on_chat_end 时批量 flush。
    """

    def __init__(self, db: ChatLogDB):
        self._db = db
        self._trace_id = ""
        self._user_input = ""
        self._start_ts = 0.0
        self._timers: dict[str, float] = {}     # 多个并存
        self._tool_calls: list[dict] = []
        self._event_buffer: list[dict] = []      # 延迟写入缓冲区

    # ── 外部接口 ──────────────────────────────────────

    def on_chat_start(self, trace_id: str, user_input: str) -> None:
        """chat 开始。"""
        self._trace_id = trace_id
        self._user_input = user_input
        self._start_ts = time.monotonic()
        self._tool_calls.clear()
        self._timers.clear()
        self._event_buffer.clear()

    def on_chat_end(self, ctx: RunContext) -> None:
        """chat 结束。flush 缓冲 + 写 chat_log 汇总。"""
        # flush 所有未完成 node
        for pname in list(self._timers.keys()):
            self._end_node(pname, output_summary="(interrupted)")
        # flush 剩余 buffer
        self._flush()
        # 写 chat_log
        duration = int((time.monotonic() - self._start_ts) * 1000)
        self._db.log(
            trace_id=self._trace_id,
            user_input=self._user_input,
            response_text=ctx.final_text or ctx.raw_text or "",
            emotion=ctx.emotion or "",
            gesture=ctx.gesture or "",
            llm_call_count=ctx.llm_call_count,
            total_duration_ms=duration,
            tool_calls=self._tool_calls or None,
        )

    # ── AgentEvent 处理器 ─────────────────────────────

    def handle_event(self, type: str, **data) -> None:
        """处理 AgentEvent，决定是否写 phase_event。"""
        if type == "node.start":
            self._start_node(data.get("name", ""))
        elif type == "node.done":
            name = data.get("name", "")
            if name == "reflect":
                pass  # reflect.result 已处理，跳过 node.done 避免双写
            else:
                extra = {k: v for k, v in data.items() if k != "name"}
                self._end_node(name,
                    output_summary=self._summarize_node(name, extra),
                    extra=extra)
        elif type == "text_token":
            pass  # 逐 token 事件不单独记录
        elif type == "tool.start":
            self._start_node(f"tool:{data.get('name', 'unknown')}")
        elif type == "tool.done":
            name = data.get("name", "unknown")
            status = data.get("status", "success")
            self._tool_calls.append({"name": name, "status": status})
            self._end_node(f"tool:{name}", output_summary=status)
        elif type == "reflect.result":
            level = data.get("level", 0)
            feedback = data.get("feedback", "")
            analysis = data.get("analysis", "")
            self._end_node("reflect",
                output_summary=f"level={level}",
                status="ok",
                extra={"level": level, "feedback": feedback, "analysis": analysis})
        elif type == "tool.denied":
            name = data.get("name", "unknown")
            self._tool_calls.append({"name": name, "status": "denied"})

    @staticmethod
    def _summarize_node(name: str, extra: dict) -> str:
        """从 node.done extra 数据生成可读摘要。"""
        if name == "rag_vector":
            return f"{extra.get('chunks', 0)} chunks"
        if name == "rag_keyword":
            return f"{extra.get('chunks', 0)} chunks"
        if name == "system_prompt":
            parts = []
            if extra.get("has_facts"):
                parts.append("facts")
            if extra.get("has_retry"):
                parts.append("retry")
            return "+".join(parts) if parts else "ok"
        if name == "merge":
            return f"{extra.get('total_chunks', 0)} chunks, {extra.get('history_turns', 0)} turns"
        if name == "react":
            tool_calls = extra.get("tool_calls", 0)
            return f"rounds={extra.get('rounds', 0)} tools={tool_calls}" if tool_calls else f"rounds={extra.get('rounds', 0)}"
        if name == "after":
            return f"emotion={extra.get('emotion', '')}"
        if name == "reflect":
            return f"level={extra.get('level', '')}"
        if name == "memory":
            return f"count={extra.get('count', 0)}"
        return str(extra)

    # ── Node 开始/结束 ────────────────────────────────

    def _start_node(self, name: str) -> None:
        """启动节点计时。允许多个节点同时计时（BSP 并行）。"""
        self._timers[name] = time.monotonic()

    def _end_node(self, name: str, output_summary: str = "",
                  status: str = "ok", error: str = "",
                  extra: dict | None = None) -> None:
        """结束指定节点的计时。写入 event_buffer（非立即 commit）。"""
        start = self._timers.pop(name, None)
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0
        self._event_buffer.append({
            "trace_id": self._trace_id,
            "phase_name": name,
            "input_summary": "",
            "output_summary": output_summary or "",
            "duration_ms": duration_ms,
            "status": status,
            "error": error,
            "extra": extra,
        })
        if len(self._event_buffer) >= _FLUSH_THRESHOLD:
            self._flush()

    def _flush(self) -> None:
        """批量写入 + 单次 commit。"""
        if not self._event_buffer:
            return
        try:
            for entry in self._event_buffer:
                self._db.log_phase(**entry)
        except Exception:
            pass  # 日志不影响主流程
        self._event_buffer.clear()

    # ── 手动接口（向后兼容）────────────────────────────

    def node_start(self, name: str) -> None:
        """手动启动一个 node 计时。"""
        self._start_node(name)

    def node_end(self, name: str, output_summary: str = "",
                 status: str = "ok", error: str = "",
                 extra: dict | None = None) -> None:
        """手动结束一个 node。"""
        self._end_node(name, output_summary, status, error, extra)
