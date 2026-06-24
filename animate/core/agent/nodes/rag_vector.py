"""RAGVectorNode — embed + vector_search"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from animate.core.engine.node import Node, NodeResult
from animate.core.log import setup_logger

if TYPE_CHECKING:
    from animate.core.engine.context import RunContext

logger = setup_logger(__name__)


class RAGVectorNode(Node):
    """embed HTTP 调用 + vector_store.search。

    内部串行（embed 依赖），与 RAGKeywordNode / SystemPromptNode 并行。
    """

    reads = {"user_input"}
    writes = {"rag_vector_chunks"}

    def __init__(self, vector_store):
        self._vector_store = vector_store

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="rag_vector")
        try:
            from animate.core.rag.embedder import embed

            loop = asyncio.get_event_loop()
            query_vec = await loop.run_in_executor(None, embed, [ctx.user_input])
            results = self._vector_store.search(query_vec)
            chunks = [chunk for chunk, score in results]
            preview = (chunks[0][:60] + "...") if chunks else ""
            logger.info("[%s] rag_vector: %d chunks [%s]",
                        ctx.trace_id, len(chunks), preview)
            await emit("node.done", name="rag_vector", chunks=len(chunks), preview=preview)
        except Exception as e:
            logger.warning("[%s] rag_vector failed: %s", ctx.trace_id, e)
            chunks = []
            await emit("node.done", name="rag_vector", chunks=0, preview="")
        ctx.extras["rag_vector_chunks"] = chunks
        return NodeResult(next_node="merge", data={"chunks": chunks})
