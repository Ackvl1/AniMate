"""Tests for RAGVectorNode — embed + vector_search"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from animate.core.engine.context import RunContext
from animate.core.engine.node import Node, NodeResult


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.search.return_value = [("chunk1", 0.9), ("chunk2", 0.8)]
    return vs


@pytest.mark.asyncio
async def test_is_node_subclass(mock_vector_store):
    from animate.core.agent.nodes.rag_vector import RAGVectorNode
    node = RAGVectorNode(vector_store=mock_vector_store)
    assert isinstance(node, Node)


@pytest.mark.asyncio
async def test_returns_merge_next_node(mock_vector_store):
    from animate.core.agent.nodes.rag_vector import RAGVectorNode
    node = RAGVectorNode(vector_store=mock_vector_store)
    ctx = RunContext(user_input="今天天气")
    result = await node.run(ctx, AsyncMock())
    assert result.next_node == "merge"


@pytest.mark.asyncio
async def test_invokes_embed_and_search(mock_vector_store):
    from animate.core.agent.nodes.rag_vector import RAGVectorNode
    node = RAGVectorNode(vector_store=mock_vector_store)
    ctx = RunContext(user_input="今天天气")
    with patch("animate.core.rag.embedder.embed") as mock_embed:
        mock_embed.return_value = [[0.1, 0.2]]
        result = await node.run(ctx, AsyncMock())

    mock_embed.assert_called_once_with(["今天天气"])
    mock_vector_store.search.assert_called_once()
    assert result.data["chunks"] == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_embed_failure_returns_empty(mock_vector_store):
    from animate.core.agent.nodes.rag_vector import RAGVectorNode
    node = RAGVectorNode(vector_store=mock_vector_store)
    ctx = RunContext(user_input="今天天气")
    with patch("animate.core.rag.embedder.embed") as mock_embed:
        mock_embed.side_effect = Exception("API error")
        result = await node.run(ctx, AsyncMock())

    assert result.data["chunks"] == []


@pytest.mark.asyncio
async def test_search_empty_returns_empty(mock_vector_store):
    mock_vector_store.search.return_value = []
    from animate.core.agent.nodes.rag_vector import RAGVectorNode
    node = RAGVectorNode(vector_store=mock_vector_store)
    ctx = RunContext(user_input="今天天气")
    with patch("animate.core.rag.embedder.embed") as mock_embed:
        mock_embed.return_value = [[0.1, 0.2]]
        result = await node.run(ctx, AsyncMock())

    assert result.data["chunks"] == []
