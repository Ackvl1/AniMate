"""RAGKeywordNode — keyword_search"""

from __future__ import annotations

from typing import TYPE_CHECKING

from animate.core.engine.node import Node, NodeResult
from animate.core.log import setup_logger

if TYPE_CHECKING:
    from animate.core.engine.context import RunContext

logger = setup_logger(__name__)


class RAGKeywordNode(Node):
    """关键词检索。无外部依赖，可与 RAGVectorNode 并行。"""

    reads = {"user_input"}
    writes = {"rag_keyword_chunks"}

    def __init__(self, keyword_store):
        self._keyword_store = keyword_store

    async def run(self, ctx: "RunContext", emit) -> NodeResult:
        await emit("node.start", name="rag_keyword")
        try:
            results = self._keyword_store.search(ctx.user_input)
            chunks = [chunk for chunk, score in results]
            preview = (chunks[0][:60] + "...") if chunks else ""
            logger.info("[%s] rag_keyword: %d chunks [%s]",
                        ctx.trace_id, len(chunks), preview)
            await emit("node.done", name="rag_keyword", chunks=len(chunks), preview=preview)
        except Exception as e:
            logger.warning("[%s] rag_keyword failed: %s", ctx.trace_id, e)
            chunks = []
            await emit("node.done", name="rag_keyword", chunks=0, preview="")
        return NodeResult(diff={"rag_keyword_chunks": chunks})
