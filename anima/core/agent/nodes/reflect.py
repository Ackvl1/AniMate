"""ReflectNode — LLM 质量评估 + 重试决策（适配新引擎接口）"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from anima.core.engine.node import Node, NodeResult
from anima.core.log import setup_logger

if TYPE_CHECKING:
    from anima.core.engine.context import RunContext

logger = setup_logger(__name__)


class ReflectNode(Node):
    """质量评估节点：评估 LLM 回复质量，决定是否重跑。

    新引擎接口:
      async run(ctx, emit) -> NodeResult
        - NodeResult.next_node=None     → 通过，本轮结束
        - NodeResult.next_node="react"  → 重生成 (level 2-3)
        - NodeResult.next_node="before" → 重检索 (level 4)
    """

    EVALUATE_PROMPT = (
        "请评估以下回复的质量。检查：\n"
        "1. 语气是否符合角色人设\n"
        "2. 内容是否与用户问题相关\n\n"
        "先在 <analysis> 中逐维分析（角色一致性、内容相关性、语气适当性），\n"
        "然后在 <summary> 中返回 JSON: {\"level\": 0-4, \"feedback\": \"改进建议\"}\n"
        "level 0=完美, 1=小问题, 2=需重格式化, 3=需重生成, 4=需重新检索上下文"
    )

    MAX_LLM_CALL_LIMIT = 20

    reads = {"final_text", "user_input", "llm_call_count", "accumulated_usage"}
    writes = {"is_retry", "feedback", "retry_feedback_injected", "accumulated_usage", "llm_call_count"}

    def __init__(self, llm, max_retry_calls: int | None = None):
        self._llm = llm
        self._max_retry_calls = max_retry_calls if max_retry_calls is not None else self.MAX_LLM_CALL_LIMIT

    async def run(self, ctx: RunContext, emit) -> NodeResult:
        await emit("node.start", name="reflect")
        if not ctx.final_text:
            await emit("node.done", name="reflect", level=-1, feedback="")
            return NodeResult()

        if ctx.llm_call_count >= self._max_retry_calls:
            logger.info("[%s] skip reflect: llm_call_count=%d >= %d",
                        ctx.trace_id, ctx.llm_call_count, self._max_retry_calls)
            await emit("node.done", name="reflect", level=-1, feedback="skipped")
            return NodeResult()

        # Phase 6: 读取 ctx 值到局部变量
        llm_call_count = ctx.llm_call_count
        accumulated_usage = ctx.accumulated_usage

        try:
            eval_messages = [
                {"role": "system", "content": self.EVALUATE_PROMPT},
                {"role": "user", "content": f"用户问题：{ctx.user_input}\n\n当前回复：{ctx.final_text}"},
            ]
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._llm.chat, eval_messages)
            llm_call_count += 1
            if result.total_tokens:
                accumulated_usage += result.total_tokens

            raw = result.content.strip()
            # 提取 analysis（如果有的话）
            analysis = ""
            analysis_start = raw.find("<analysis>")
            analysis_end = raw.find("</analysis>")
            if analysis_start != -1 and analysis_end != -1:
                analysis = raw[analysis_start + len("<analysis>"):analysis_end].strip()

            # 从 <summary> 标签中提取 JSON（scratchpad 模式）
            summary_start = raw.find("<summary>")
            summary_end = raw.find("</summary>")
            if summary_start != -1 and summary_end != -1:
                json_str = raw[summary_start + len("<summary>"):summary_end].strip()
            else:
                # 回退：整个输出作为 JSON（兼容旧格式）
                json_str = raw
            json_str = json_str.removeprefix("```json").removeprefix("```JSON").removeprefix("```python").removeprefix("```").removesuffix("```").strip()
            data = json.loads(json_str)
            level = int(data.get("level", 0))
            feedback = data.get("feedback", "")

            logger.info("[%s] reflect: level=%d feedback=[%s] analysis=[%s]",
                        ctx.trace_id, level, feedback[:60], analysis[:60])
            await emit("reflect.result", level=level, feedback=feedback, analysis=analysis)
            await emit("node.done", name="reflect", level=level, feedback=feedback[:80])

            if level >= 4:
                return NodeResult(
                    next_node="before",
                    diff={"feedback": feedback, "is_retry": True,
                          "llm_call_count": llm_call_count, "accumulated_usage": accumulated_usage},
                )

            if level >= 2:
                return NodeResult(
                    next_node="react",
                    diff={"feedback": feedback, "is_retry": True,
                          "retry_feedback_injected": None,
                          "llm_call_count": llm_call_count, "accumulated_usage": accumulated_usage},
                )

            return NodeResult(
                diff={"llm_call_count": llm_call_count, "accumulated_usage": accumulated_usage},
            )

        except Exception as e:
            logger.warning("[%s] reflect failed: %s", ctx.trace_id, e)
            await emit("node.done", name="reflect", level=-1, feedback="error")
            return NodeResult(
                diff={"llm_call_count": llm_call_count, "accumulated_usage": accumulated_usage},
            )
