"""Tests for MemoryNode returning diff (Phase 6.2)"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from animate.core.engine.context import RunContext
from animate.core.agent.nodes.memory_node import MemoryNode


class TestMemoryNodeDiff:
    """MemoryNode 应该返回 diff 而不是写 ctx"""
    
    def _make_node(self, facts=None):
        provider = MagicMock()
        if facts is None:
            provider.prefetch.return_value = ["fact1", "fact2"]
        else:
            provider.prefetch.return_value = facts
        return MemoryNode(provider)
    
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    def test_returns_diff_with_memory_facts(self):
        """应该返回 diff.memory_facts"""
        node = self._make_node(["fact1", "fact2"])
        ctx = RunContext(user_input="hello")
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff is not None
        assert result.diff["memory_facts"] == ["fact1", "fact2"]
    
    def test_does_not_write_ctx_extras(self):
        """不应该直接写 ctx.extras"""
        node = self._make_node(["fact1"])
        ctx = RunContext(user_input="hello")
        
        self._run(node.run(ctx, AsyncMock()))
        
        assert "memory_facts" not in ctx.extras
    
    def test_empty_facts_returns_empty_list(self):
        """无事实时返回空列表"""
        node = self._make_node([])
        ctx = RunContext(user_input="hello")
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff["memory_facts"] == []
    
    def test_exception_returns_empty_list(self):
        """异常时返回空列表"""
        provider = MagicMock()
        provider.prefetch.side_effect = RuntimeError("DB error")
        node = MemoryNode(provider)
        ctx = RunContext(user_input="hello")
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff["memory_facts"] == []
    
    def test_next_node_unchanged(self):
        """next_node 保持不变"""
        node = self._make_node()
        ctx = RunContext(user_input="hello")
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.next_node == "system_prompt"
