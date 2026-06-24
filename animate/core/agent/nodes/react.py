"""ReactNode — LLM 调用 + ReAct 工具循环 + inline marker 流式输出

使用 TextMarkerStreamer 将 LLM 流中的 (emotion,gesture) 标记实时解析为
emotion.update 事件，纯文本部分逐字发射为 text_token 事件。

StreamingToolExecutor: 流式过程中检测到只读工具的 tool_call 时，
立即在后台执行，与 LLM 后续文本流失并行，减少用户等待时间。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from animate.core.engine.node import Node, NodeResult
from animate.core.llm.models import LLMResult, ToolCall
from animate.core.log import setup_logger
from animate.core.agent.nodes.marker_streamer import TextMarkerStreamer

if TYPE_CHECKING:
    from animate.core.engine.context import RunContext

logger = setup_logger(__name__)


class ReactNode(Node):
    """LLM 调用 + 工具调用循环。

    每轮：
      1. 调 LLM（流式）
      2. 有 tool_calls → 执行 → 继续
      3. 无 tool_calls → 结束
    """

    MAX_ROUNDS = 10

    def __init__(self, llm, tools, permission_manager=None):
        self._llm = llm
        self._tools = tools
        self._permission_manager = permission_manager

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="react")
        messages = list(ctx.messages)

        # Retry feedback injection
        if ctx.is_retry and ctx.feedback:
            feedback_msg = (
                "【重试指示】上轮回复需要改进：{feedback}\n"
                "请先说一句符合角色性格的过渡语自然衔接，\n"
                "然后输出修正后的回答。".format(feedback=ctx.feedback)
            )
            messages.append({"role": "system", "content": feedback_msg})
            logger.info("[%s] react retry: injected feedback: %s",
                        ctx.trace_id, ctx.feedback[:60])
        tool_schemas = None
        if self._tools and self._tools.names:
            tool_schemas = self._tools.list_schemas()

        for round_num in range(1, self.MAX_ROUNDS + 1):
            pre_fetch_tasks: dict[int, asyncio.Task[str]] = {}

            result = await self._stream_round(
                messages, tool_schemas, ctx, round_num, emit,
                pre_fetch_tasks=pre_fetch_tasks,
            )

            if not result:
                continue

            if result.tool_calls:
                await self._handle_tool_calls(
                    result, messages, ctx, round_num, emit,
                    pre_fetch_tasks=pre_fetch_tasks,
                )
                continue

            # LLM 直接回复
            ctx.messages = messages
            preview = result.content[:60].replace("\n", "\\n")
            logger.info("[%s] react round %d done: %d chars [%s]",
                        ctx.trace_id, round_num, len(result.content), preview)
            await emit("node.done", name="react", rounds=round_num, tool_calls=0)
            return NodeResult(next_node="after")

        ctx.raw_text = "（已达最大工具调用轮数）"
        ctx.messages = messages
        logger.warning("[%s] react exceeded max rounds", ctx.trace_id)
        await emit("node.done", name="react", rounds=round_num, tool_calls=-1)
        return NodeResult(next_node="after")

    # ── 流式调用 ─────────────────────────────────────

    async def _stream_round(self, messages, tool_schemas, ctx, round_num, emit,
                             pre_fetch_tasks: dict[int, asyncio.Task[str]] | None = None):
        """流式调用 LLM。

        流失过程中如果检测到只读+可并行的 tool_call，立即在后台执行
        （StreamingToolExecutor 模式），与后续流失文本并行。
        """
        full_content = ""
        pending_calls: dict[int, dict[str, Any]] = {}
        text_parts = []

        async def tracking_emit(type, **data):
            nonlocal text_parts
            if type == "emotion.update":
                ctx.emotion = data.get("emotion", ctx.emotion)
                ctx.gesture = data.get("gesture", ctx.gesture)
            elif type == "text_token":
                text_parts.append(data.get("text", ""))
            await emit(type, **data)

        streamer = TextMarkerStreamer()
        ctx.llm_call_count += 1

        # 统一的事件处理闭包（捕获 full_content / pending_calls 等局部变量）
        async def handle_event(event: dict) -> None:
            nonlocal full_content
            if event["type"] == "delta":
                if "content" in event:
                    full_content += event["content"]
                    await streamer.feed(event["content"], tracking_emit)
            elif event["type"] == "usage":
                total = event.get("total_tokens", 0)
                if total:
                    ctx.accumulated_usage += total
            elif event["type"] == "tool_call":
                idx = event["index"]
                if idx not in pending_calls:
                    pending_calls[idx] = {"id": "", "name": "", "arguments": ""}
                pc = pending_calls[idx]
                if event.get("id"):
                    pc["id"] = event["id"]
                if event.get("name"):
                    pc["name"] = event["name"]
                if event.get("arguments"):
                    pc["arguments"] += event["arguments"]
            elif event["type"] == "done":
                self._pre_fetch_on_stream_end(pending_calls, pre_fetch_tasks, ctx, round_num)
                await streamer.flush(tracking_emit)

        # 分派流式迭代器
        if hasattr(self._llm, "chat_stream_async"):
            stream_iter = self._llm.chat_stream_async(messages, tools=tool_schemas)
            async for event in stream_iter:
                await handle_event(event)
        else:
            stream_iter = self._llm.chat_stream(messages, tools=tool_schemas)
            for event in stream_iter:
                await handle_event(event)

        tool_calls = self._build_tool_calls(pending_calls, ctx)
        ctx.raw_text = "".join(text_parts)
        return LLMResult(content=full_content, tool_calls=tool_calls or None)

    def _pre_fetch_on_stream_end(self, pending_calls, pre_fetch_tasks, ctx, round_num):
        """流失结束时，对只读+可并行的工具发起后台预执行。"""
        if pre_fetch_tasks is None or self._tools is None:
            return
        for idx, pc in pending_calls.items():
            try:
                name = pc.get("name", "")
                tool = self._tools.find(name)
                if tool is None or not (tool.is_read_only and tool.is_parallel_safe):
                    continue
                args = json.loads(pc["arguments"]) if pc.get("arguments") else {}
                logger.info("[%s] pre-fetch tool: %s (while streaming)", ctx.trace_id, name)
                task = asyncio.create_task(self._execute_tool_async(name, args))
                pre_fetch_tasks[idx] = task
            except Exception:
                pass  # 预执行失败不影响主流程

    async def _execute_tool_async(self, name: str, args: dict) -> str:
        """在后台线程中同步执行工具。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._tools.execute, name, args)

    @staticmethod
    def _build_tool_calls(pending_calls: dict, ctx) -> list[ToolCall] | None:
        if not pending_calls:
            return None
        result = []
        for idx in sorted(pending_calls.keys()):
            pc = pending_calls[idx]
            try:
                args = json.loads(pc["arguments"]) if pc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            result.append(ToolCall(
                id=pc["id"] or f"call_{ctx.trace_id}_{idx}",
                name=pc["name"] or "unknown",
                arguments=args,
            ))
        return result

    # ── 工具执行（含 StreamingToolExecutor 集成）──────

    async def _handle_tool_calls(self, result, messages, ctx, round_num, emit,
                                  pre_fetch_tasks: dict[int, asyncio.Task[str]] | None = None):
        """执行工具调用，优先使用流失过程中预执行的结果。"""
        for idx, tc in enumerate(result.tool_calls):
            thought = (result.content or "")[:80].replace("\n", "\\n")
            if thought:
                logger.info("[%s] react round %d: thought=[%s]",
                            ctx.trace_id, round_num, thought)
            logger.info("[%s] react round %d: tool_call %s",
                        ctx.trace_id, round_num, tc.name)
            await emit("tool.start", name=tc.name, arguments=tc.arguments)

            messages.append(tc.to_assistant_message(content=result.content))

            # 优先取流失中预执行的结果，否则同步执行
            if pre_fetch_tasks and idx in pre_fetch_tasks:
                logger.info("[%s] using pre-fetched result for %s", ctx.trace_id, tc.name)
                output = await pre_fetch_tasks[idx]
            else:
                # HITL 权限检查：非只读工具首次需要用户确认
                if self._permission_manager is not None:
                    tool = self._tools.find(tc.name)
                    if tool is None or not await self._permission_manager.check(tc.name, tool, tc.arguments):
                        if tool is None:
                            output = f"错误：未找到工具 '{tc.name}'"
                        else:
                            logger.info("[%s] user denied %s", ctx.trace_id, tc.name)
                            output = "（用户取消了操作）"
                            await emit("tool.denied", name=tc.name)
                            messages.append(tc.to_tool_message(result=output))
                            continue  # 跳过这个工具的执行，继续下一个
                output = self._tools.execute(tc.name, tc.arguments)

            messages.append(tc.to_tool_message(result=output))

            # System Re-Reminder
            reminder = (
                "<system-reminder>你仍然在扮演当前角色。"
                "保持角色设定、语气和性格，不要因为工具调用而偏离角色。</system-reminder>"
            )
            messages.append({"role": "system", "content": reminder})

            preview = output[:50].replace("\n", "\\n")
            logger.info("[%s] tool %s -> %d chars: %s",
                        ctx.trace_id, tc.name, len(output), preview)

            status = "error" if "失败" in output or "错误" in output else "success"
            await emit("tool.done", name=tc.name, status=status)
