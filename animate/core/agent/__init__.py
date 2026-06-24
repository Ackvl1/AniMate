"""AniMate Agent 子系统"""

# ── Agent 门面 ──
from animate.core.agent.agent import Agent
from animate.core.agent.response import AgentResponse, ReflectionSignal

# ── 图引擎类型（便捷导入） ──
from animate.core.engine.node import Node, NodeResult, AgentEvent
from animate.core.engine.context import RunContext, RunServices
from animate.core.engine.graph import Graph, GraphEngine

# ── 权限管理 ──
from animate.core.agent.permission import PermissionManager

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
