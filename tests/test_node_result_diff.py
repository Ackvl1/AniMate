"""Tests for NodeResult diff field (Phase 6)"""
import pytest
from animate.core.engine.node import NodeResult


class TestNodeResultDiff:
    """NodeResult 应该支持 diff 字段返回状态差异"""
    
    def test_node_result_has_diff_field(self):
        """NodeResult 应该有 diff 字段"""
        result = NodeResult(next_node="after")
        assert hasattr(result, "diff")
    
    def test_node_result_diff_default_none(self):
        """diff 默认值应该是 None"""
        result = NodeResult(next_node="after")
        assert result.diff is None
    
    def test_node_result_with_diff(self):
        """NodeResult 应该能接受 diff 参数"""
        diff = {"emotion": "happy", "gesture": "wave"}
        result = NodeResult(next_node="after", diff=diff)
        assert result.diff == diff
    
    def test_node_result_diff_is_dict(self):
        """diff 应该是 dict 类型"""
        result = NodeResult(diff={"field": "value"})
        assert isinstance(result.diff, dict)
    
    def test_node_result_next_node_still_works(self):
        """next_node 字段应该正常工作"""
        result = NodeResult(next_node="reflect", diff={"test": True})
        assert result.next_node == "reflect"
        assert result.diff == {"test": True}
