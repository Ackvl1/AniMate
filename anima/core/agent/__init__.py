"""Anima Agent Agent 子系统"""

# ── Agent 门面 ──
from anima.core.agent.agent import Agent
from anima.core.agent.response import AgentResponse, ReflectionSignal

# ── 图引擎类型（便捷导入） ──
from anima.core.engine.node import Node, NodeResult, AgentEvent
from anima.core.engine.context import RunContext, RunServices
from anima.core.engine.graph import Graph, GraphEngine

# ── 权限管理 ──
from anima.core.agent.permission import PermissionManager

__all__ = [
    # Agent 门面
    "Agent",
    "AgentResponse",
    "ReflectionSignal",
    # 图引擎
    "Node",
    "NodeResult",
    "AgentEvent",
    "RunContext",
    "RunServices",
    "Graph",
    "GraphEngine",
    # 权限管理
    "PermissionManager",
]
