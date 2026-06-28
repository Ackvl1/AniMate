"""MCP Client — JSON-RPC 2.0 over stdio 传输"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any


class MCPError(Exception):
    """MCP 协议错误。"""


class MCPClient:
    """MCP 客户端，通过 stdio 与 MCP Server 通信。

    用法:
        client = MCPClient(command=["node", "server.js"], env={"KEY": "val"})
        client.start()
        tools = client.list_tools()
        result = client.call_tool("tool_name", {"arg": "val"})
        client.stop()
    """

    def __init__(self, command: list[str], env: dict[str, str] | None = None,
                 name: str = "mcp-server", timeout: float = 30.0):
        self._command = command
        self._env = env
        self._name = name
        self._timeout = timeout
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._buffer = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """启动 MCP Server 子进程并完成初始化握手。"""
        if self.is_running:
            return

        # Windows 上 npx 是 .cmd 文件，需要完整 env PATH
        env = os.environ.copy()
        if self._env:
            env.update(self._env)
        # 确保 nodejs 目录在 PATH 中
        node_dir = os.path.dirname(shutil.which("node") or "")
        if node_dir and node_dir not in env.get("PATH", ""):
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")

        # Windows: 解析 .cmd/.exe 路径（subprocess 找不到 PATHEXT）
        cmd = list(self._command)
        resolved = shutil.which(cmd[0])
        if resolved:
            cmd[0] = resolved
        self._command_str = shlex.join(cmd)

        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,  # 行缓冲
        )

        # 握手：initialize + initialized（带启动超时）
        start_deadline = time.time() + self._timeout
        while time.time() < start_deadline:
            if self._process.poll() is not None:
                stderr = self._process.stderr.read()
                raise MCPError(
                    f"MCP Server '{self._name}' 启动失败 (code={self._process.returncode}): {stderr[:500]}"
                )
            try:
                result = self._request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "animate", "version": "1.0"},
                })
                # initialized 通知（不需要响应）
                self._notify("notifications/initialized")
                return
            except MCPError:
                # 进程还在启动中，重试
                time.sleep(0.5)

        raise MCPError(f"MCP Server '{self._name}' 启动超时 ({self._timeout}s)")

    def stop(self) -> None:
        """关闭 MCP Server 子进程。"""
        if self._process and self.is_running:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def list_tools(self) -> list[dict]:
        """获取 MCP Server 提供的工具列表。

        Returns:
            [{name, description, inputSchema}, ...]
        """
        result = self._request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """调用 MCP 工具。

        Args:
            name: 工具名
            arguments: 参数

        Returns:
            工具返回的文本内容
        """
        result = self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })

        # 解析 content 数组
        content = result.get("content", [])
        texts = []
        for item in content:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)

    def _request(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应。"""
        if not self.is_running:
            raise MCPError(f"MCP Server '{self._name}' 未运行")

        self._request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        with self._lock:
            self._write_line(req)
            resp = self._read_response(self._request_id)

        if "error" in resp:
            err = resp["error"]
            raise MCPError(f"MCP 工具调用错误: {err.get('message', str(err))}")

        return resp.get("result", {})

    def _notify(self, method: str) -> None:
        """发送 JSON-RPC 通知（无响应）。"""
        req = {
            "jsonrpc": "2.0",
            "method": method,
        }
        with self._lock:
            self._write_line(req)

    def _write_line(self, data: dict) -> None:
        """写一行 JSON 到 stdin。"""
        line = json.dumps(data, ensure_ascii=False)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

    def _read_response(self, expected_id: int) -> dict:
        """从 stdout 读取 JSON-RPC 响应。"""
        deadline = time.time() + self._timeout

        while time.time() < deadline:
            line = self._process.stdout.readline()
            if not line:
                # 检查进程是否退出
                ret = self._process.poll()
                stderr = self._process.stderr.read()
                raise MCPError(
                    f"MCP Server '{self._name}' 已退出 (code={ret}): {stderr[:500]}"
                )

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 找到匹配 id 的响应
            if "id" in msg and msg.get("id") == expected_id:
                return msg

            # 忽略通知和日志
            if "method" in msg:
                continue

        raise MCPError(f"MCP 请求超时 (id={expected_id})")
