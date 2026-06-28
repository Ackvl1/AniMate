"""MergeNode — 收三个上游结果 → 去重合并 → 组装 system prompt → messages

不再 clear() ctx.messages，只替换/插入 system prompt 在索引 0。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from anima.core.engine.node import Node, NodeResult
from anima.core.log import setup_logger

if TYPE_CHECKING:
    from anima.core.engine.context import RunContext

logger = setup_logger(__name__)


class MergeNode(Node):
    """收 RAGVectorNode、RAGKeywordNode、SystemPromptNode 的结果，组装 ctx.messages。"""

    reads = {"rag_vector_chunks", "rag_keyword_chunks", "system_parts", "messages", "user_input"}
    writes = {"messages"}

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="merge")

        # 1. 合并 RAG chunks（去重）
        vector_chunks = ctx.extras.get("rag_vector_chunks", [])
        keyword_chunks = ctx.extras.get("rag_keyword_chunks", [])
        all_chunks = list(dict.fromkeys(vector_chunks + keyword_chunks))

        # 2. 拼 system prompt
        system_parts = list(ctx.extras.get("system_parts", []))
        if all_chunks:
            system_parts.append("以下是相关知识：\n" + "\n---\n".join(all_chunks[:5]))
        system_text = "\n\n".join(system_parts)

        # 3. 局部构建 messages（不改 ctx，返回 diff）
        messages = list(ctx.messages)
        if messages and messages[0].get("role") == "system":
            messages[0] = {"role": "system", "content": system_text}
        else:
            messages.insert(0, {"role": "system", "content": system_text})

        # 4. 防御纵深：仅在极端回退场景（messages 末尾缺 user）时补入
        last_user_idx = next(
            (i for i in range(len(messages) - 1, -1, -1)
             if messages[i].get("role") == "user"), -1
        )
        if last_user_idx < 0:
            messages.append({"role": "user", "content": ctx.user_input})

        history_turns = sum(1 for m in messages if m["role"] == "assistant")
        logger.info("[%s] merge: %d rag chunks, %d history turns, %d total msgs",
                    ctx.trace_id, len(all_chunks), history_turns, len(messages))
        await emit("node.done", name="merge",
                   total_chunks=len(all_chunks), history_turns=history_turns)

        return NodeResult(diff={"messages": messages})
