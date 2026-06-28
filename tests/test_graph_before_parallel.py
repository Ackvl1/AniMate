"""Integration tests — fan_out → join → merge → react 全流程"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from anima.core.engine.graph import Graph, GraphEngine
from anima.core.engine.context import RunContext
from anima.core.engine.node import Node, NodeResult


@pytest.mark.asyncio
async def test_fan_out_join_runs_all_nodes():
    """BSP 引擎 fan_out 三个节点，join 后运行 merge，验证所有节点执行。"""
    from anima.core.agent.nodes.rag_vector import RAGVectorNode
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    from anima.core.agent.nodes.system_prompt import SystemPromptNode
    from anima.core.agent.nodes.merge import MergeNode

    g = Graph()
    g.add_node("rag_vector", RAGVectorNode(vector_store=MagicMock()))
    g.add_node("rag_keyword", RAGKeywordNode(keyword_store=MagicMock()))
    g.add_node("system_prompt", SystemPromptNode(persona="你是祥子"))
    g.add_node("merge", MergeNode())

    g.add_fan_out("__entry__", ["rag_vector", "rag_keyword", "system_prompt"])
    g.add_join(["rag_vector", "rag_keyword", "system_prompt"], "merge")
    g.set_entry("__entry__")

    ctx = RunContext(user_input="你好")

    with patch("anima.core.rag.embedder.embed") as mock_embed:
        mock_embed.return_value = [[0.1, 0.2]]
        engine = g.create_engine(max_steps=10)
        await engine.run(ctx, AsyncMock())

    assert "rag_vector" in engine.executed_nodes
    assert "rag_keyword" in engine.executed_nodes
    assert "system_prompt" in engine.executed_nodes
    assert "merge" in engine.executed_nodes
    assert len(ctx.messages) >= 1
    assert ctx.messages[0]["role"] == "system"


@pytest.mark.asyncio
async def test_rag_node_failure_does_not_block():
    """RAG 节点异常不应阻塞其他节点。"""
    from anima.core.agent.nodes.rag_vector import RAGVectorNode
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    from anima.core.agent.nodes.system_prompt import SystemPromptNode
    from anima.core.agent.nodes.merge import MergeNode

    failing_vs = MagicMock()
    failing_vs.search.side_effect = Exception("crash")

    g = Graph()
    g.add_node("rag_vector", RAGVectorNode(vector_store=failing_vs))
    g.add_node("rag_keyword", RAGKeywordNode(keyword_store=MagicMock()))
    g.add_node("system_prompt", SystemPromptNode(persona="你是祥子"))
    g.add_node("merge", MergeNode())

    g.add_fan_out("__entry__", ["rag_vector", "rag_keyword", "system_prompt"])
    g.add_join(["rag_vector", "rag_keyword", "system_prompt"], "merge")
    g.set_entry("__entry__")

    ctx = RunContext(user_input="你好")

    with patch("anima.core.rag.embedder.embed") as mock_embed:
        mock_embed.return_value = [[0.1, 0.2]]
        engine = g.create_engine(max_steps=10)
        await engine.run(ctx, AsyncMock())

    # merge 应仍运行，system prompt 应包含人设
    assert "merge" in engine.executed_nodes
    assert "你是祥子" in ctx.messages[0]["content"]


@pytest.mark.asyncio
async def test_before_parallel_to_react_flows():
    """从 fan_out→join→merge 到 react 的完整流程。"""
    from anima.core.agent.nodes.rag_vector import RAGVectorNode
    from anima.core.agent.nodes.rag_keyword import RAGKeywordNode
    from anima.core.agent.nodes.system_prompt import SystemPromptNode
    from anima.core.agent.nodes.merge import MergeNode
    from anima.core.agent.nodes.react import ReactNode

    vs = MagicMock()
    vs.search.return_value = [("知识chunk", 0.9)]
    ks = MagicMock()
    ks.search.return_value = [("关键词chunk", 0.7)]

    g = Graph()
    g.add_node("rag_vector", RAGVectorNode(vector_store=vs))
    g.add_node("rag_keyword", RAGKeywordNode(keyword_store=ks))
    g.add_node("system_prompt", SystemPromptNode(persona="你是祥子"))
    g.add_node("merge", MergeNode())
    g.add_node("react", ReactNode(llm=MagicMock(), tools=MagicMock()))

    g.add_fan_out("__entry__", ["rag_vector", "rag_keyword", "system_prompt"])
    g.add_join(["rag_vector", "rag_keyword", "system_prompt"], "merge")
    g.add_edge("merge", "react")
    g.set_entry("__entry__")

    ctx = RunContext(user_input="今天天气")
    engine = g.create_engine(max_steps=10)

    with patch("anima.core.rag.embedder.embed") as mock_embed:
        mock_embed.return_value = [[0.1, 0.2]]
        await engine.run(ctx, AsyncMock())

    assert "知识chunk" in ctx.messages[0]["content"]
    assert "关键词chunk" in ctx.messages[0]["content"]
    assert ctx.messages[-1]["role"] == "user"
    assert "merge" in engine.executed_nodes
    assert "react" in engine.executed_nodes
