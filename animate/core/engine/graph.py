"""Graph — 图定义 + BSP 调度引擎"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from animate.core.engine.node import Node, NodeResult
from animate.core.engine.context import RunContext

# EventEmitter 类型
EventEmitter = Callable[..., Coroutine | None]


async def _noop_emit(*args, **kwargs):
    """默认空 emit（不发射任何事件）。"""
    pass


@dataclass
class Edge:
    """图中一条有向边。"""
    source: str
    target: str
    edge_type: str = "direct"  # direct | conditional | fan_out | join
    router: Callable | None = None
    mapping: dict[str, str | None] | None = None


class Graph:
    """图定义：节点 + 边的注册，引擎创建。"""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._entry: str | None = None

    # ── 节点注册 ────────────────────────────────────

    def add_node(self, name: str, node: Node) -> None:
        self.nodes[name] = node

    def set_entry(self, name: str) -> None:
        self._entry = name

    # ── 边注册 ──────────────────────────────────────

    def add_edge(self, source: str, target: str) -> None:
        self.edges.append(Edge(source=source, target=target, edge_type="direct"))

    def add_conditional_edge(
        self,
        source: str,
        router: Callable[[NodeResult], str | None],
        mapping: dict[str, str | None],
    ) -> None:
        self.edges.append(Edge(
            source=source, target="", edge_type="conditional",
            router=router, mapping=mapping,
        ))

    def add_fan_out(self, source: str, targets: list[str]) -> None:
        for t in targets:
            self.edges.append(Edge(source=source, target=t, edge_type="fan_out"))

    def add_join(self, sources: list[str], target: str) -> None:
        for s in sources:
            self.edges.append(Edge(source=s, target=target, edge_type="join"))

    # ── 验证 ────────────────────────────────────────

    def validate(self) -> list[str]:
        warnings = []
        for name in self.nodes:
            has_in = any(e.target == name for e in self.edges) or name == self._entry
            has_out = any(e.source == name for e in self.edges)
            if not has_in and not has_out and len(self.nodes) > 1:
                warnings.append(f"孤立节点: {name}")
        return warnings

    # ── 创建引擎 ────────────────────────────────────

    def create_engine(self, max_steps: int = 50) -> GraphEngine:
        return GraphEngine(self, max_steps=max_steps)


class GraphEngine:
    """BSP 调度引擎。

    每轮超级步：
      1. 找出所有就绪节点（上游全部完成）
      2. 冲突检测 → 不冲突的并行执行
      3. 执行 → 收集 NodeResult
      4. 根据边/条件边决定下一批就绪节点
      5. 有回路边则重新标记上游就绪
    """

    def __init__(self, graph: Graph, max_steps: int = 50):
        self._graph = graph
        self._max_steps = max_steps
        self.executed_nodes: list[str] = []
        self._completed: set[str] = set()      # 已完成的节点
        self._pending: set[str] = set()         # 已就绪待执行的节点
        self._node_results: dict[str, NodeResult] = {}  # 每个节点的结果

    async def run(self, ctx: RunContext, emit: EventEmitter | None = None) -> GraphEngine:
        """执行图，返回自身（供链式调用）。"""
        entry = self._graph._entry
        if not entry:
            raise ValueError("未设置入口节点")

        self._pending = {entry}
        self._completed.clear()
        self._node_results.clear()
        self.executed_nodes.clear()
        steps = 0

        while self._pending and steps < self._max_steps:
            steps += 1

            # 冲突检测：同批写入相同字段的节点不能并行
            ready, deferred = self._resolve_conflicts(list(self._pending))
            self._pending.clear()
            self._pending.update(deferred)

            # 并行执行就绪节点
            tasks = [self._run_node(name, ctx, emit) for name in ready]
            await asyncio.gather(*tasks)

            # 更新完成状态
            for name in ready:
                self._completed.add(name)
                self.executed_nodes.append(name)
                result = self._node_results.get(name)
                self._schedule_downstream(name, result)

        return self

    async def _run_node(self, name: str, ctx: RunContext, emit: EventEmitter | None = None) -> None:
        """执行一个节点并保存结果。跳过虚拟节点（无实际 Node 对象）。"""
        node = self._graph.nodes.get(name)
        if node is None:
            return  # fan_out 等虚拟节点，仅用于调度

        _emit = emit if emit is not None else _noop_emit
        result = await node.run(ctx, _emit)
        self._node_results[name] = result

    def _schedule_downstream(self, node_name: str, result: NodeResult | None) -> None:
        """根据 NodeResult 和边决定下一个就绪节点。"""
        edges = [e for e in self._graph.edges if e.source == node_name]

        for edge in edges:
            if edge.edge_type == "direct":
                self._pending.add(edge.target)

            elif edge.edge_type == "conditional":
                if edge.router and result:
                    next_key = edge.router(result)
                    next_node = edge.mapping.get(next_key) if edge.mapping else next_key
                    if next_node:
                        self._pending.add(next_node)

            elif edge.edge_type == "fan_out":
                self._pending.add(edge.target)

            elif edge.edge_type == "join":
                # join 边：检查所有上游是否都完成了
                sources = [e.source for e in self._graph.edges
                           if e.target == edge.target and e.edge_type == "join"]
                if all(s in self._completed for s in sources):
                    self._pending.add(edge.target)

    def _resolve_conflicts(self, candidates: list[str]) -> tuple[list[str], list[str]]:
        """从候选节点中解决写冲突，返回 (可并行执行的节点列表, 被延迟的节点列表)。"""
        if len(candidates) <= 1:
            return candidates, []

        # 检查任意两个节点是否有写冲突
        ready = []
        deferred = []
        written: set[str] = set()
        for name in candidates:
            node = self._graph.nodes.get(name)
            if not node:
                continue
            writes = node.writes if hasattr(node, "writes") else set()
            if writes & written:
                # 有冲突，跳过这个节点（下次超级步再试）
                deferred.append(name)
            else:
                ready.append(name)
                written |= writes

        # 如果全部冲突退化为串行
        if not ready:
            ready = [candidates[0]]
            deferred = candidates[1:]

        return ready, deferred
