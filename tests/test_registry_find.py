"""Tests for ToolRegistry.find()"""
from anima.core.tools.registry import ToolRegistry
from anima.core.tools.base import LocalTool


class TestToolRegistryFind:
    def test_find_returns_tool_after_register_tool(self):
        registry = ToolRegistry()
        class MyTool(LocalTool):
            name = "my_tool"
            description = "test"
            is_read_only = True
            def execute(self, **kwargs): return "ok"
        tool = MyTool()
        registry.register_tool(tool)
        found = registry.find("my_tool")
        assert found is tool
        assert found.is_read_only is True

    def test_find_returns_none_for_unknown(self):
        registry = ToolRegistry()
        assert registry.find("nonexistent") is None

    def test_find_returns_none_if_register_without_tool(self):
        """用 register() 而非 register_tool() 注册的工具不会被 find() 找到"""
        registry = ToolRegistry()
        registry.register("echo", "echo", handler=lambda: "ok")
        assert registry.find("echo") is None

    def test_find_returns_correct_instance(self):
        """多个工具时 find 返回正确的那个"""
        registry = ToolRegistry()
        class A(LocalTool):
            name = "tool_a"
            description = ""
            is_read_only = True
            def execute(self, **kwargs): return "a"
        class B(LocalTool):
            name = "tool_b"
            description = ""
            is_read_only = False
            def execute(self, **kwargs): return "b"
        a, b = A(), B()
        registry.register_tool(a)
        registry.register_tool(b)
        assert registry.find("tool_a").is_read_only is True
        assert registry.find("tool_b").is_read_only is False
