"""Tests for animate/core/engine/graph.py — Graph definition + BSP scheduling."""

import pytest
from unittest.mock import MagicMock

from animate.core.engine.graph import Graph, Edge
from animate.core.engine.node import Node, NodeResult
from animate.core.engine.context import RunContext


class SimpleNode(Node):
    """最小 Node 实现，用于图测试。"""
    def __init__(self, name, reads=None, writes=None):
        self._name = name
        self.reads = reads or set()
        self.writes = writes or set()
        self.run_count = 0

    async def run(self, ctx, emit):
        self.run_count += 1
        return NodeResult(next_node=None, data={})


class TestGraphDefinition:
    def test_add_node(self):
        """注册一个节点后应在 nodes 中。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        assert "a" in g.nodes

    def test_add_edge(self):
        """添加边后应记录在 edges 中。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        g.add_node("b", SimpleNode("b"))
        g.add_edge("a", "b")
        assert any(e.source == "a" and e.target == "b" and e.edge_type == "direct" for e in g.edges)

    def test_add_conditional_edge(self):
        """条件边应记录 router 和 mapping。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        g.add_node("b", SimpleNode("b"))
        g.add_node("c", SimpleNode("c"))

        def router(result):
            return "b" if result.data.get("x") else "c"

        g.add_conditional_edge("a", router, {"b": "b", "c": "c"})
        ce = [e for e in g.edges if e.edge_type == "conditional"]
        assert len(ce) == 1
        assert ce[0].source == "a"
        assert ce[0].router is not None
        assert ce[0].mapping == {"b": "b", "c": "c"}

    def test_add_fan_out(self):
        """并行边应记录多个下游。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        g.add_node("b", SimpleNode("b"))
        g.add_node("c", SimpleNode("c"))
        g.add_fan_out("a", ["b", "c"])
        targets = [e.target for e in g.edges if e.source == "a" and e.edge_type == "fan_out"]
        assert "b" in targets
        assert "c" in targets

    def test_add_join(self):
        """汇聚边应记录多个上游。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        g.add_node("b", SimpleNode("b"))
        g.add_node("c", SimpleNode("c"))
        g.add_join(["a", "b"], "c")
        join_sources = [e.source for e in g.edges if e.target == "c" and e.edge_type == "join"]
        assert "a" in join_sources
        assert "b" in join_sources

    def test_validate_orphan_node(self):
        """孤立节点应警告。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        g.add_node("b", SimpleNode("b"))
        g.add_edge("a", "b")
        warnings = g.validate()
        assert len(warnings) == 0

    def test_validate_orphan_detected(self):
        """真正孤立的节点应被检测到。"""
        g = Graph()
        g.add_node("a", SimpleNode("a"))
        g.add_node("orphan", SimpleNode("orphan"))
        g.set_entry("a")
        warnings = g.validate()
        assert any("orphan" in w for w in warnings)


class TestBSPExecution:
    @pytest.mark.asyncio
    async def test_simple_chain(self):
        """A → B → C，应依次执行。"""
        g = Graph()
        a = SimpleNode("a")
        b = SimpleNode("b")
        c = SimpleNode("c")
        g.add_node("a", a)
        g.add_node("b", b)
        g.add_node("c", c)
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.set_entry("a")

        ctx = RunContext(user_input="test")
        engine = g.create_engine()
        await engine.run(ctx)

        assert a.run_count == 1
        assert b.run_count == 1
        assert c.run_count == 1
        assert len(engine.executed_nodes) == 3

    @pytest.mark.asyncio
    async def test_conditional_branch(self):
        """条件边应根据 router 结果走正确分支。"""
        g = Graph()
        a = SimpleNode("a")
        b = SimpleNode("b")
        c = SimpleNode("c")
        executed = {"a": False, "b": False, "c": False}

        async def run_a(ctx, emit):
            executed["a"] = True
            return NodeResult(data={"which": "b"})

        async def run_b(ctx, emit):
            executed["b"] = True
            return NodeResult(data={})

        async def run_c(ctx, emit):
            executed["c"] = True
            return NodeResult(data={})

        a.run = run_a
        b.run = run_b
        c.run = run_c
        g.add_node("a", a)
        g.add_node("b", b)
        g.add_node("c", c)
        g.add_conditional_edge("a", lambda r: r.data.get("which", "c"), {"b": "b", "c": "c"})
        g.set_entry("a")

        ctx = RunContext(user_input="test")
        engine = g.create_engine()
        await engine.run(ctx)

        assert executed["a"] is True
        assert executed["b"] is True
        assert executed["c"] is False

    @pytest.mark.asyncio
    async def test_fan_out_join(self):
        """并行 fan-out 后 join，两个下游都应执行。"""
        g = Graph()
        a = SimpleNode("a")
        b = SimpleNode("b")
        c = SimpleNode("c")
        d = SimpleNode("d")
        g.add_node("a", a)
        g.add_node("b", b)
        g.add_node("c", c)
        g.add_node("d", d)
        g.add_fan_out("a", ["b", "c"])
        g.add_join(["b", "c"], "d")
        g.set_entry("a")

        ctx = RunContext(user_input="test")
        engine = g.create_engine()
        await engine.run(ctx)

        assert a.run_count == 1
        assert b.run_count == 1
        assert c.run_count == 1
        assert d.run_count == 1

    @pytest.mark.asyncio
    async def test_react_loop(self):
        """react → router → tool → react 回路。"""
        g = Graph()
        loop_count = {"react": 0, "tool": 0}

        async def run_react(ctx, emit):
            loop_count["react"] += 1
            # 第一次和第二次都有 tool，第三次没有
            wants_tool = loop_count["react"] <= 2
            return NodeResult(data={"wants_tool": wants_tool})

        async def run_tool(ctx, emit):
            loop_count["tool"] += 1
            return NodeResult(data={})

        react = SimpleNode("react")
        react.run = run_react
        tool = SimpleNode("tool")
        tool.run = run_tool

        g.add_node("react", react)
        g.add_node("tool", tool)

        def router(result):
            if result.data.get("wants_tool"):
                return "tool"
            return "end"

        g.add_conditional_edge("react", router, {"tool": "tool", "end": None})
        g.add_edge("tool", "react")
        g.set_entry("react")

        ctx = RunContext(user_input="test")
        engine = g.create_engine(max_steps=10)
        await engine.run(ctx)

        assert loop_count["react"] == 3  # 第一次 + 回路第二次 + 最终无工具
        assert loop_count["tool"] == 2   # 两次工具执行
