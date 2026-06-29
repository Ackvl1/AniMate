"""Tests for GraphEngine apply_diff + FIELD_WRITERS (Phase 6)"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from anima.core.engine.graph import Graph, GraphEngine
from anima.core.engine.node import Node, NodeResult
from anima.core.engine.context import RunContext, FIELD_WRITERS
from anima.core.errors import FieldWriteError


# ── 测试用节点 ──

class SimpleNode(Node):
    """简单节点：返回 diff（使用 react 节点名，允许写 emotion）"""
    reads = {"emotion"}
    writes = {"emotion", "final_text"}
    
    async def run(self, ctx, emit) -> NodeResult:
        return NodeResult(
            next_node=None,
            diff={"emotion": "happy", "final_text": "hello"}
        )


class ExtrasNode(Node):
    """写 extras 的节点（使用 memory 节点名，允许写 memory_facts）"""
    reads = {"user_input"}
    writes = {"memory_facts"}
    
    async def run(self, ctx, emit) -> NodeResult:
        return NodeResult(
            next_node=None,
            diff={"memory_facts": ["fact1", "fact2"]}
        )


class UnauthorizedNode(Node):
    """越权写入的节点（使用 memory 节点名，但写 final_text）"""
    reads = set()
    writes = {"memory_facts"}  # 声明写 memory_facts
    
    async def run(self, ctx, emit) -> NodeResult:
        return NodeResult(
            next_node=None,
            diff={"final_text": "hacked"}  # 但实际写 final_text
        )


class NoDiffNode(Node):
    """不返回 diff 的节点"""
    reads = set()
    writes = set()
    
    async def run(self, ctx, emit) -> NodeResult:
        return NodeResult(next_node=None)


# ── 测试 ──

class TestEngineApplyDiff:
    """GraphEngine 应该自动 apply diff"""
    
    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    def test_apply_diff_updates_ctx(self):
        """apply_diff 应该更新 ctx 字段"""
        g = Graph()
        g.add_node("after", SimpleNode())  # 使用 after 节点名（允许写 final_text）
        g.add_edge("after", "__end__")
        g.set_entry("after")
        
        ctx = RunContext()
        ctx.emotion = "sad"
        
        engine = g.create_engine()
        self._run_async(engine.run(ctx, AsyncMock()))
        
        assert ctx.emotion == "happy"
        assert ctx.final_text == "hello"
    
    def test_apply_diff_extras(self):
        """apply_diff 应该更新 extras"""
        g = Graph()
        g.add_node("memory", ExtrasNode())  # 使用 memory 节点名
        g.add_edge("memory", "__end__")
        g.set_entry("memory")
        
        ctx = RunContext()
        
        engine = g.create_engine()
        self._run_async(engine.run(ctx, AsyncMock()))
        
        assert ctx.extras["memory_facts"] == ["fact1", "fact2"]
    
    def test_apply_diff_field_writers_violation(self):
        """越权写入应该抛出 FieldWriteError"""
        g = Graph()
        g.add_node("memory", UnauthorizedNode())  # 使用 memory 节点名
        g.set_entry("memory")
        
        ctx = RunContext()
        
        engine = g.create_engine()
        
        with pytest.raises(FieldWriteError):
            self._run_async(engine.run(ctx, AsyncMock()))
    
    def test_no_diff_node_does_not_modify_ctx(self):
        """不返回 diff 的节点不应该修改 ctx"""
        g = Graph()
        g.add_node("nodiff", NoDiffNode())
        g.add_edge("nodiff", "__end__")
        g.set_entry("nodiff")
        
        ctx = RunContext()
        ctx.emotion = "sad"
        original_emotion = ctx.emotion
        
        engine = g.create_engine()
        self._run_async(engine.run(ctx, AsyncMock()))
        
        assert ctx.emotion == original_emotion


class TestFieldWriters:
    """FIELD_WRITERS 应该正确校验"""
    
    def test_field_writers_covers_all_fields(self):
        """FIELD_WRITERS 应该覆盖所有已知字段"""
        expected_fields = {
            "user_input", "messages", "raw_text", "final_text",
            "emotion", "gesture", "llm_call_count", "accumulated_usage",
            "is_retry", "feedback", "retry_feedback_injected",
            "rag_vector_chunks", "rag_keyword_chunks", "system_parts", "memory_facts",
        }
        assert expected_fields.issubset(set(FIELD_WRITERS.keys()))
    
    def test_check_write_permission_allows(self):
        """check_write_permission 应该允许声明的写入"""
        ctx = RunContext()
        assert ctx.check_write_permission("emotion", "react") is True
    
    def test_check_write_permission_denies(self):
        """check_write_permission 应该拒绝未声明的写入"""
        ctx = RunContext()
        assert ctx.check_write_permission("emotion", "memory") is False
    
    def test_check_write_permission_undeclared_allows(self):
        """未声明的字段应该允许任意写入"""
        ctx = RunContext()
        assert ctx.check_write_permission("custom_field", "any_node") is True
