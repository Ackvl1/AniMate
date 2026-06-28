"""MCP Server 管理器 — 注册 MCP 工具到 ToolRegistry"""

from __future__ import annotations

import os
import shlex
from typing import Any

from anima.core.log import setup_logger
from anima.core.tools.base import LocalTool
from anima.core.tools.mcp.client import MCPClient
from anima.core.tools.registry import ToolRegistry

logger = setup_logger(__name__)

# ── MCP 模块目录（npm 依赖安装位置） ────────
_MCP_DIR = os.path.abspath(os.path.dirname(__file__))

def _node_modules(path: str) -> str:
    """将相对 node_modules/ 路径转为绝对路径。"""
    return os.path.join(_MCP_DIR, "node_modules", path)

# ── MCP Server 配置 ────────────────────────────────────────
# 每个条目: {name, command, env}
# name: 服务器名（用于标识）
# command: 启动命令（list of str）
# env: 环境变量（可选）
#
# 按需取消注释或添加。需要 API key 的已标注。

MCP_SERVER_CONFIGS: list[dict[str, Any]] = [
    # ── Filesystem ──
    # 文件读写操作。限制在指定目录内。无需 API Key。
    {
        "name": "filesystem",
        "command": [
            "node",
            _node_modules("@modelcontextprotocol/server-filesystem/dist/index.js"),
            os.path.expanduser("~/Desktop"),
        ],
    },
    # ── Brave Search ──
    # 互联网搜索。需要 BRAVE_API_KEY 环境变量。
    # 注册免费 key: https://brave.com/search/api/
    {
        "name": "brave-search",
        "command": [
            "node",
            _node_modules("@modelcontextprotocol/server-brave-search/dist/index.js"),
        ],
        "env": {
            "BRAVE_API_KEY": os.environ.get("BRAVE_API_KEY", ""),
        },
    },
    # ── GitHub ──
    # 管理 GitHub 仓库、Issue、PR。
    # 需要 GITHUB_TOKEN 环境变量。
    {
        "name": "github",
        "command": [
            "node",
            _node_modules("@modelcontextprotocol/server-github/dist/index.js"),
        ],
        "env": {
            "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        },
    },
    # ── Memory（知识图谱记忆） ──
    # 基于知识图谱的持久化记忆。无需 API Key。
    {
        "name": "memory",
        "command": [
            "node",
            _node_modules("@modelcontextprotocol/server-memory/dist/index.js"),
        ],
    },
]


class MCPToolWrapper(LocalTool):
    """将 MCP 工具包装为 LocalTool。自动处理与本地工具的重名冲突。"""

    def __init__(self, client: MCPClient, tool_def: dict, server_name: str = "",
                 existing_names: set[str] | None = None):
        self._client = client
        self._tool_def = tool_def
        self._mcp_tool_name = tool_def.get("name", "unknown")
        self.description = tool_def.get("description", "") or ""
        schema = tool_def.get("inputSchema", {})
        self.parameters = schema if schema else {"type": "object", "properties": {}}

        # 如果 MCP 工具与本地工具重名，加服务器名前缀
        raw_name = self._mcp_tool_name
        if existing_names and raw_name in existing_names:
            self.name = f"{server_name}_{raw_name}"
            logger.info("MCP 工具 '%s' 重名 → 重命名为 '%s'", raw_name, self.name)
        else:
            self.name = raw_name

    def execute(self, **kwargs) -> str:
        return self._client.call_tool(self._mcp_tool_name, kwargs)


def register_mcp_servers(registry: ToolRegistry) -> list[MCPClient]:
    """启动配置中的所有 MCP Server，注册其工具到 registry。

    Returns:
        已启动的 MCPClient 列表（用于后续 stop）
    """
    clients = []

    for cfg in MCP_SERVER_CONFIGS:
        name = cfg["name"]
        command = cfg["command"]
        env = cfg.get("env")

        # 跳过需要 API Key 但没配的
        if env:
            missing = [k for k, v in env.items() if not v]
            if missing:
                logger.info("跳过 MCP '%s': 缺少环境变量 %s", name, missing)
                continue

        logger.info("启动 MCP Server: %s → %s", name, shlex.join(command))
        try:
            client = MCPClient(command=command, env=env, name=name, timeout=30)
            client.start()

            tools = client.list_tools()
            registered = 0
            existing = set(registry.names)
            for tool_def in tools:
                wrapper = MCPToolWrapper(client, tool_def, server_name=name,
                                         existing_names=existing)
                registry.register_tool(wrapper)
                registered += 1

            logger.info("MCP '%s' 已连接: %d 个工具", name, registered)
            clients.append(client)

        except Exception as e:
            logger.warning("MCP '%s' 启动失败: %s", name, e)
            try:
                client.stop()
            except Exception:
                pass

    return clients
