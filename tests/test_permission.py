"""Tests for PermissionManager — HITL 权限管理"""
import pytest
from animate.core.agent import PermissionManager
from animate.core.tools.base import LocalTool


class ReadOnlyTool(LocalTool):
    name = "read_only"
    description = "只读工具"
    is_read_only = True
    is_parallel_safe = True
    is_destructive = False
    def execute(self, **kwargs) -> str:
        return "read_only_result"


class DestructiveTool(LocalTool):
    name = "destructive"
    description = "破坏性工具"
    is_read_only = False
    is_parallel_safe = False
    is_destructive = True
    def execute(self, **kwargs) -> str:
        return "destructive_result"


class TestPermissionManager:
    @pytest.mark.asyncio
    async def test_read_only_auto_approve(self):
        """只读工具应自动放行，不触发 callback"""
        callback_called = False
        async def callback(name, args):
            nonlocal callback_called
            callback_called = True
            return True

        pm = PermissionManager(callback=callback)
        result = await pm.check("read_only", ReadOnlyTool(), {})
        assert result is True
        assert callback_called is False, "只读工具不应触发 callback"

    @pytest.mark.asyncio
    async def test_destructive_triggers_callback(self):
        """破坏性工具应触发 callback"""
        callback_called = False
        async def callback(name, args):
            nonlocal callback_called
            callback_called = True
            return True

        pm = PermissionManager(callback=callback)
        result = await pm.check("destructive", DestructiveTool(), {})
        assert result is True
        assert callback_called is True, "破坏性工具应触发 callback"

    @pytest.mark.asyncio
    async def test_user_deny_returns_false(self):
        """用户拒绝应返回 False"""
        async def callback(name, args):
            return False

        pm = PermissionManager(callback=callback)
        result = await pm.check("destructive", DestructiveTool(), {})
        assert result is False

    @pytest.mark.asyncio
    async def test_approved_tool_remembered(self):
        """批准后的工具本 session 不再重复询问"""
        call_count = 0
        async def callback(name, args):
            nonlocal call_count
            call_count += 1
            return True

        pm = PermissionManager(callback=callback)
        await pm.check("destructive", DestructiveTool(), {})
        await pm.check("destructive", DestructiveTool(), {})
        assert call_count == 1, "第二次不应触发 callback"

    @pytest.mark.asyncio
    async def test_auto_mode_skips_all(self):
        """auto_mode 下跳过所有询问"""
        callback_called = False
        async def callback(name, args):
            nonlocal callback_called
            callback_called = True
            return True

        pm = PermissionManager(callback=callback, auto_mode=True)
        result = await pm.check("destructive", DestructiveTool(), {})
        assert result is True
        assert callback_called is False, "auto_mode 不应触发 callback"

    @pytest.mark.asyncio
    async def test_reset_clears_memory(self):
        """reset 后应重新询问"""
        call_count = 0
        async def callback(name, args):
            nonlocal call_count
            call_count += 1
            return True

        pm = PermissionManager(callback=callback)
        await pm.check("destructive", DestructiveTool(), {})
        pm.reset()
        await pm.check("destructive", DestructiveTool(), {})
        assert call_count == 2, "reset 后应重新询问"

    @pytest.mark.asyncio
    async def test_no_callback_returns_true(self):
        """没有 callback 时自动放行（auto 等价）"""
        pm = PermissionManager()
        result = await pm.check("destructive", DestructiveTool(), {})
        assert result is True
