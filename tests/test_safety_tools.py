"""Tests for Fail-Closed tool safety attributes (RED - should fail first)"""
import pytest
from anima.core.tools.base import LocalTool
from anima.core.tools.function.time_tool import TimeTool
from anima.core.tools.function.code_exec import ExecutePythonTool
from anima.core.tools.function.file_tools import WriteFileTool


class TestLocalToolSafety:
    def test_default_safety_attributes(self):
        """新工具默认 is_read_only=False, is_parallel_safe=False, is_destructive=False"""
        class NewTool(LocalTool):
            name = "new_tool"
            description = "test"
            def execute(self, **kwargs) -> str:
                return "ok"

        tool = NewTool()
        assert tool.is_read_only is False, "默认 is_read_only=False（安全：假定有副作用）"
        assert tool.is_parallel_safe is False, "默认 is_parallel_safe=False（安全：假定不能并发）"
        assert tool.is_destructive is False, "默认 is_destructive=False（安全：假定非破坏性）"

    def test_read_only_tool_overrides(self):
        """只读工具可以覆盖 is_read_only=True"""
        class ReadOnlyTool(LocalTool):
            name = "read_only"
            description = "test"
            is_read_only = True
            is_parallel_safe = True
            def execute(self, **kwargs) -> str:
                return "data"

        tool = ReadOnlyTool()
        assert tool.is_read_only is True
        assert tool.is_parallel_safe is True

    def test_destructive_tool_overrides(self):
        """破坏性工具可以覆盖 is_destructive=True"""
        tool = ExecutePythonTool()
        assert tool.is_destructive is True
        assert tool.is_read_only is False
        assert tool.is_parallel_safe is False

    def test_to_schema_contains_safety_meta(self):
        """to_schema() 应包含 x_is_read_only 和 x_is_destructive 字段"""
        class TestTool(LocalTool):
            name = "test_tool"
            description = "test"
            is_read_only = True
            is_destructive = False
            def execute(self, **kwargs) -> str:
                return "ok"

        schema = TestTool().to_schema()
        func = schema["function"]
        assert "x_is_read_only" in func, "schema 应包含 x_is_read_only"
        assert "x_is_destructive" in func, "schema 应包含 x_is_destructive"
        assert func["x_is_read_only"] is True
        assert func["x_is_destructive"] is False

    def test_time_tool_is_read_only(self):
        """TimeTool 应为只读 + 可并行 + 非破坏性"""
        tool = TimeTool()
        assert tool.is_read_only is True
        assert tool.is_parallel_safe is True
        assert tool.is_destructive is False

    def test_write_file_tool_permission(self):
        """WriteFileTool 应为非只读（需要 HITL 确认）"""
        tool = WriteFileTool()
        assert tool.is_read_only is False, "WriteFileTool 应需要权限确认"
        assert tool.is_parallel_safe is False
