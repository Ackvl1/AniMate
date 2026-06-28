"""PermissionManager — session 级 HITL 权限管理。

权限规则：
  - 只读工具（is_read_only=True）→ 自动放行
  - 非只读工具 → 首次调用征求用户意见
  - 用户批准后同一 session 不再重复询问该工具
  - auto_mode 模式下跳过所有询问（QQ 群场景）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from anima.core.tools.base import LocalTool

# 权限检查回调类型：async (tool_name, args) -> bool
PermissionCallback = Callable[[str, dict], Awaitable[bool]]


class PermissionManager:
    """Session 级 HITL 权限管理器。"""

    def __init__(self, callback: PermissionCallback | None = None,
                 auto_mode: bool = False):
        self._allowed: set[str] = set()  # 本 session 已批准的工具名
        self._callback = callback
        self._auto_mode = auto_mode

    async def check(self, tool_name: str, tool: "LocalTool", args: dict) -> bool:
        """检查工具是否可以执行。

        Returns:
            True = 允许执行，False = 用户拒绝
        """
        if self._auto_mode:
            return True
        if tool_name in self._allowed:
            return True
        if tool.is_read_only:
            return True  # 只读工具永远放行
        if self._callback:
            approved = await self._callback(tool_name, args)
            if approved:
                self._allowed.add(tool_name)
            return approved
        return True  # 没有 callback = auto 模式等价

    def reset(self) -> None:
        """清空 session 记录。"""
        self._allowed.clear()
