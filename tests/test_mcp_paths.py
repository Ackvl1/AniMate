"""Tests for animate/core/tools/mcp/manager.py — MCP module path resolution."""

from pathlib import Path

from animate.core.tools.mcp.manager import _node_modules, _MCP_DIR


def test_node_modules_resolves_correctly():
    """_node_modules() 应返回 mcp 目录下的 node_modules 绝对路径。"""
    path = _node_modules("@modelcontextprotocol/server-filesystem/dist/index.js")
    p = Path(path)
    assert p.exists()
    assert "node_modules" in path
    assert "@modelcontextprotocol" in path
    assert p.is_file()


def test_mcp_dir_is_correct():
    """_MCP_DIR 应是 animate/core/tools/mcp/。"""
    assert Path(_MCP_DIR, "package.json").exists()


def test_node_modules_resolves_to_mcp_local():
    """解析路径应包含 tools/mcp 而非项目根。"""
    path = _node_modules("@modelcontextprotocol/server-filesystem/dist/index.js")
    assert "tools" in path
    assert "mcp" in path
