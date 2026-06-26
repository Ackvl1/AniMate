"""Tests for AfterNode returning diff (Phase 6.2)"""
import pytest
import asyncio
from unittest.mock import AsyncMock
from animate.core.engine.context import RunContext
from animate.core.agent.nodes.after import AfterNode


class TestAfterNodeDiff:
    """AfterNode 应该返回 diff 而不是写 ctx"""
    
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    def test_returns_diff_with_fields(self):
        """应该返回 diff.final_text, emotion, gesture"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "hello world"
        ctx.emotion = "happy"
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff is not None
        assert "final_text" in result.diff
        assert "emotion" in result.diff
    
    def test_does_not_write_ctx(self):
        """不应该直接写 ctx"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "hello"
        ctx.emotion = "happy"
        
        self._run(node.run(ctx, AsyncMock()))
        
        # ctx 应该保持原值
        assert ctx.final_text == ""
        assert ctx.emotion == "happy"  # 原值不变
    
    def test_empty_text_returns_empty_final(self):
        """空文本返回空 final_text"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = ""
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff["final_text"] == ""
    
    def test_strips_markers(self):
        """应该清理标记"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "(happy,wave) hello"
        ctx.emotion = "happy"
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert "(happy" not in result.diff["final_text"]
        assert "hello" in result.diff["final_text"]
    
    def test_validates_unknown_emotion(self):
        """未知 emotion 应该 fallback 到 calm"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "hello"
        ctx.emotion = "nonexistent"
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff["emotion"] == "calm"
    
    def test_empty_emotion_defaults_to_calm(self):
        """空 emotion 应该默认 calm"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "hello"
        ctx.emotion = ""
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.diff["emotion"] == "calm"
    
    def test_gesture_correction(self):
        """不匹配的 gesture 应该被修正"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "hello"
        ctx.emotion = "sad"
        ctx.gesture = "dance"  # sad 不允许 dance
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        # gesture 应该被修正为 sad 允许的值
        assert result.diff["gesture"] != "dance"
    
    def test_next_node_unchanged(self):
        """next_node 保持不变"""
        node = AfterNode()
        ctx = RunContext()
        ctx.raw_text = "hello"
        
        result = self._run(node.run(ctx, AsyncMock()))
        
        assert result.next_node == "reflect"
