"""Tests for ToolRegistry (RED — should fail first)"""

import pytest
from anima.core.tools.registry import ToolRegistry
from anima.core.tools.base import LocalTool


class TestToolRegistry:
    def test_register_and_execute(self):
        registry = ToolRegistry()
        registry.register(
            name="get_time",
            description="获取当前时间",
            handler=lambda: "12:00",
        )
        result = registry.execute("get_time", {})
        assert result == "12:00"

    def test_unknown_tool_returns_error(self):
        registry = ToolRegistry()
        result = registry.execute("unknown", {})
        assert "未找到" in result

    def test_list_schemas(self):
        registry = ToolRegistry()
        registry.register(
            name="echo",
            description="回显",
            handler=lambda msg: msg,
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
        schemas = registry.list_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "echo"


class TestLocalTool:
    def test_subclass(self):
        class EchoTool(LocalTool):
            name = "echo"
            description = "echo"

            def execute(self, **kwargs) -> str:
                return kwargs.get("msg", "")

        tool = EchoTool()
        assert tool.name == "echo"
        assert tool.to_schema()["function"]["name"] == "echo"
