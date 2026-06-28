"""Tests for RAGKeywordNode — keyword_search"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from anima.core.engine.context import RunContext
from anima.core.engine.node import Node, NodeResult


@pytest.fixture
def mock_keyword_store():
    ks = MagicMock()
    ks.search.return_value = [("kw_chunk1", 0.7), ("kw_chunk2", 0.6)]
    return ks


@pytest.mark.asyncio
async def test_is_node_subclass(mock_keyword_store):
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    node = RAGKeywordNode(keyword_store=mock_keyword_store)
    assert isinstance(node, Node)


@pytest.mark.asyncio
async def test_returns_merge_next_node(mock_keyword_store):
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    node = RAGKeywordNode(keyword_store=mock_keyword_store)
    ctx = RunContext(user_input="今天天气")
    result = await node.run(ctx, AsyncMock())
    assert result.next_node is None  # direct 边由引擎处理


@pytest.mark.asyncio
async def test_invokes_search(mock_keyword_store):
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    node = RAGKeywordNode(keyword_store=mock_keyword_store)
    ctx = RunContext(user_input="今天天气")
    result = await node.run(ctx, AsyncMock())

    mock_keyword_store.search.assert_called_once_with("今天天气")
    assert result.diff["rag_keyword_chunks"] == ["kw_chunk1", "kw_chunk2"]


@pytest.mark.asyncio
async def test_search_failure_returns_empty(mock_keyword_store):
    mock_keyword_store.search.side_effect = Exception("search error")
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    node = RAGKeywordNode(keyword_store=mock_keyword_store)
    ctx = RunContext(user_input="今天天气")
    result = await node.run(ctx, AsyncMock())

    assert result.diff["rag_keyword_chunks"] == []


@pytest.mark.asyncio
async def test_search_empty_returns_empty(mock_keyword_store):
    mock_keyword_store.search.return_value = []
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    node = RAGKeywordNode(keyword_store=mock_keyword_store)
    ctx = RunContext(user_input="今天天气")
    result = await node.run(ctx, AsyncMock())

    assert result.diff["rag_keyword_chunks"] == []
