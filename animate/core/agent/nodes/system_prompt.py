"""SystemPromptNode — 人设 + EMOTION_INSTRUCTION + 长期记忆 + 重试反馈"""

from __future__ import annotations

from typing import TYPE_CHECKING

from animate.core.engine.node import Node, NodeResult
from animate.core.log import setup_logger
from animate.core.constants import EMOTION_INSTRUCTION_TEXT

if TYPE_CHECKING:
    from animate.core.engine.context import RunContext

logger = setup_logger(__name__)


class SystemPromptNode(Node):
    """组装 system_parts（不含 RAG 结果）。与 RAGVectorNode / RAGKeywordNode 并行。"""

    EMOTION_INSTRUCTION = EMOTION_INSTRUCTION_TEXT

    def __init__(self, persona: str):
        self._persona = persona

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="system_prompt")
        system_parts = [self._persona, self.EMOTION_INSTRUCTION]

        # 长期记忆注入
        long_term_facts = ctx.extras.get("memory_facts", [])
        if long_term_facts:
            # 兼容 list[str] 和 list[dict]（dict 时取 content 字段）
            texts = [f.get("content", f) if isinstance(f, dict) else str(f)
                     for f in long_term_facts[:10]]
            facts_str = "\n".join(f"- {t}" for t in texts if t)
            system_parts.append(f"## 角色记忆（跨会话）\n{facts_str}")

        # 重试反馈注入
        if ctx.is_retry and ctx.feedback:
            system_parts.append(
                "【重试指示】上轮回复需要改进：{feedback}\n"
                "请先说一句符合角色性格的过渡语自然衔接，\n"
                "然后输出修正后的回答。".format(feedback=ctx.feedback)
            )

        logger.info("[%s] system_prompt: facts=%d, retry=%s",
                    ctx.trace_id, len(long_term_facts), ctx.is_retry)
        await emit("node.done", name="system_prompt",
                   has_facts=bool(long_term_facts), has_retry=ctx.is_retry)
        ctx.extras["system_parts"] = system_parts
        return NodeResult(next_node="merge", data={"system_parts": system_parts})
