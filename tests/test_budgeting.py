"""Tests for Result Budgeting — 工具输出预算控制 (RED - should fail first)"""
import os
import shutil
import pytest
from animate.core.tools.registry import ToolRegistry
from animate.core.tools.base import LocalTool

RESULT_BUDGET = 50000


class LongOutputTool(LocalTool):
    """返回超长输出的测试工具"""
    name = "long_output"
    description = "返回超长文本"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False

    def __init__(self, output_size: int = 60000):
        self._output_size = output_size

    def execute(self, **kwargs) -> str:
        return "A" * self._output_size


class ShortOutputTool(LocalTool):
    """返回短输出的测试工具"""
    name = "short_output"
    description = "返回短文本"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False

    def execute(self, **kwargs) -> str:
        return "短输出"


class TestResultBudgeting:
    def test_normal_output_not_truncated(self):
        """正常输出（< 预算）不应被截断"""
        registry = ToolRegistry()
        registry.register_tool(ShortOutputTool())
        result = registry.execute("short_output", {})
        assert result == "短输出"
        assert len(result) <= RESULT_BUDGET

    def test_large_output_truncated_to_budget(self):
        """超长输出（> 预算）应被截断到预算字符数"""
        registry = ToolRegistry()
        tool = LongOutputTool(output_size=60000)
        registry.register_tool(tool)
        result = registry.execute("long_output", {})

        # 应该被截断到 RESULT_BUDGET 字符 + 截断后缀
        # 后缀格式: "\n[完整结果(...)已保存到 ...]"
        assert len(result) <= RESULT_BUDGET + 200, f"长度 {len(result)} 超出预算"
        assert "..." in result or "已保存" in result or "截断" in result, \
            f"截断结果应包含提示信息: {result[:100]}"

    def test_really_large_output_has_path_info(self):
        """超大输出截断后应包含文件路径信息"""
        registry = ToolRegistry()
        tool = LongOutputTool(output_size=200000)
        registry.register_tool(tool)
        result = registry.execute("long_output", {})
        assert "已保存到" in result or "保存到" in result or ".txt" in result, \
            f"截断结果应提示完整结果保存路径: {result[:200]}"

    def test_boundary_just_at_budget(self):
        """输出刚好等于预算字符数时不应截断"""
        registry = ToolRegistry()
        tool = LongOutputTool(output_size=RESULT_BUDGET)
        registry.register_tool(tool)
        result = registry.execute("long_output", {})
        assert len(result) >= RESULT_BUDGET, "刚好等于预算的输出不应截断"

    def test_error_output_not_affected(self):
        """工具异常时预算逻辑不应干扰错误信息"""
        class ErrorTool(LocalTool):
            name = "error_tool"
            description = "返回错误"
            is_read_only = True
            def execute(self, **kwargs) -> str:
                raise ValueError("测试错误")

        registry = ToolRegistry()
        registry.register_tool(ErrorTool())
        result = registry.execute("error_tool", {})
        assert "错误" in result or "失败" in result
