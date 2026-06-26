"""Tests for RunContext snapshot/restore (Phase 6)"""
import pytest
from animate.core.engine.context import RunContext


class TestRunContextSnapshot:
    """RunContext 应该支持 snapshot 和 restore"""
    
    def test_snapshot_returns_dict(self):
        """snapshot 应该返回 dict"""
        ctx = RunContext(user_input="hello")
        snap = ctx.snapshot()
        assert isinstance(snap, dict)
    
    def test_snapshot_contains_data_fields(self):
        """snapshot 应该包含所有数据字段"""
        ctx = RunContext(user_input="hello")
        ctx.emotion = "happy"
        ctx.gesture = "wave"
        ctx.raw_text = "test"
        ctx.final_text = "done"
        ctx.is_retry = True
        ctx.feedback = "improve"
        ctx.llm_call_count = 5
        ctx.accumulated_usage = 1000
        
        snap = ctx.snapshot()
        assert snap["user_input"] == "hello"
        assert snap["emotion"] == "happy"
        assert snap["gesture"] == "wave"
        assert snap["raw_text"] == "test"
        assert snap["final_text"] == "done"
        assert snap["is_retry"] is True
        assert snap["feedback"] == "improve"
        assert snap["llm_call_count"] == 5
        assert snap["accumulated_usage"] == 1000
    
    def test_snapshot_copies_messages(self):
        """snapshot 应该拷贝 messages 列表"""
        ctx = RunContext()
        ctx.messages.append({"role": "user", "content": "hi"})
        
        snap = ctx.snapshot()
        ctx.messages.append({"role": "assistant", "content": "hello"})
        
        assert len(snap["messages"]) == 1
        assert len(ctx.messages) == 2
    
    def test_snapshot_copies_extras(self):
        """snapshot 应该拷贝 extras 字典"""
        ctx = RunContext()
        ctx.extras["key"] = "value"
        
        snap = ctx.snapshot()
        ctx.extras["key"] = "changed"
        
        assert snap["extras"]["key"] == "value"
        assert ctx.extras["key"] == "changed"
    
    def test_restore_clears_messages(self):
        """restore 应该先清空再恢复 messages"""
        ctx = RunContext()
        ctx.messages.append({"role": "user", "content": "hi"})
        ctx.messages.append({"role": "assistant", "content": "hello"})
        
        snap = ctx.snapshot()
        ctx.messages.append({"role": "user", "content": "new"})
        
        ctx.restore(snap)
        assert len(ctx.messages) == 2
        assert ctx.messages[0]["content"] == "hi"
    
    def test_restore_clears_extras(self):
        """restore 应该先清空再恢复 extras"""
        ctx = RunContext()
        ctx.extras["key1"] = "value1"
        
        snap = ctx.snapshot()
        ctx.extras["key2"] = "value2"
        
        ctx.restore(snap)
        assert "key2" not in ctx.extras
        assert ctx.extras["key1"] == "value1"
    
    def test_restore_simple_fields(self):
        """restore 应该恢复简单字段"""
        ctx = RunContext(user_input="hello")
        ctx.emotion = "happy"
        
        snap = ctx.snapshot()
        ctx.emotion = "sad"
        
        ctx.restore(snap)
        assert ctx.user_input == "hello"
        assert ctx.emotion == "happy"
    
    def test_full_roundtrip(self):
        """完整的 snapshot → 修改 → restore 流程"""
        ctx = RunContext(user_input="test")
        ctx.emotion = "happy"
        ctx.messages.append({"role": "user", "content": "hi"})
        ctx.extras["fact"] = "real"
        
        snap = ctx.snapshot()
        
        # 模拟节点修改
        ctx.emotion = "sad"
        ctx.messages.append({"role": "assistant", "content": "hello"})
        ctx.extras["fact"] = "changed"
        ctx.extras["new"] = "added"
        
        # restore
        ctx.restore(snap)
        
        assert ctx.emotion == "happy"
        assert len(ctx.messages) == 1
        assert ctx.extras["fact"] == "real"
        assert "new" not in ctx.extras
