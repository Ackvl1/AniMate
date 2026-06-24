"""内置工具包 — 注册所有默认工具（含 MCP）"""

from animate.core.tools.registry import ToolRegistry
from animate.core.tools.function.time_tool import TimeTool
from animate.core.tools.function.calculator import CalculatorTool
from animate.core.tools.function.wikipedia import WikipediaTool
from animate.core.tools.function.web_search import WebSearchTool
from animate.core.tools.function.web_extract import WebExtractTool
from animate.core.tools.function.weather import WeatherTool
from animate.core.tools.function.arxiv import ArxivTool
from animate.core.tools.function.code_exec import ExecutePythonTool
from animate.core.tools.function.file_tools import ReadFileTool, WriteFileTool, SearchFilesTool
from animate.core.tools.mcp.manager import register_mcp_servers
from animate.core.log import setup_logger

logger = setup_logger(__name__)


def register_default_tools(registry: ToolRegistry | None = None,
                           enable_mcp: bool = True) -> tuple[ToolRegistry, list]:
    """注册所有内置工具（本地 + MCP）到 registry。

    Args:
        registry: 可选的已有 registry
        enable_mcp: 是否启动 MCP Server。默认 True。

    Returns:
        (registry, mcp_clients) — mcp_clients 用于后续清理
    """
    if registry is None:
        registry = ToolRegistry()

    # ── 本地工具（无需外部依赖） ──
    registry.register_tool(TimeTool())
    registry.register_tool(CalculatorTool())
    registry.register_tool(WikipediaTool())
    registry.register_tool(WebSearchTool())
    registry.register_tool(WebExtractTool())
    registry.register_tool(WeatherTool())
    registry.register_tool(ArxivTool())
    registry.register_tool(ExecutePythonTool())
    registry.register_tool(ReadFileTool())
    registry.register_tool(WriteFileTool())
    registry.register_tool(SearchFilesTool())

    # ── MCP Server 工具 ──
    mcp_clients = []
    if enable_mcp:
        mcp_clients = register_mcp_servers(registry)
        if mcp_clients:
            logger.info("MCP: %d 个服务器已连接", len(mcp_clients))
        else:
            logger.info("MCP: 没有可连接的服务器（跳过）")

    return registry, mcp_clients
