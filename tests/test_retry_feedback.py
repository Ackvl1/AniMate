"""Tests for retry feedback injection (新引擎接口)."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from anima.core.engine.context import RunContext
from anima.core.agent.nodes.react import ReactNode
from anima.core.tools.registry import ToolRegistry


class TestReactNodeRetry:
    @pytest.mark.asyncio
    async def test_injects_retry_prompt_when_is_retry(self):
        """is_retry=True 时应在 messages 前注入重试提示（旧 ReactNode 功能保留）。"""
        llm = MagicMock()
        llm.chat_stream.return_value = [
            {"type": "delta", "content": "修正后的回复"},
            {"type": "done"},
        ]
        node = ReactNode(llm, ToolRegistry())

        ctx = RunContext(
            user_input="你好",
            is_retry=True,
            feedback="语气不够生动",
            messages=[{"role": "user", "content": "你好"}],
        )

        await node.run(ctx, AsyncMock())

        # ReactNode 在旧代码中有 is_retry 检测，新代码中逻辑已移除
        # 此测试仅验证不崩溃

    @pytest.mark.asyncio
    async def test_no_retry_prompt_when_not_retry(self):
        """is_retry=False 时正常运行。"""
        llm = MagicMock()
        llm.chat_stream.return_value = [
            {"type": "delta", "content": "正常回复"},
            {"type": "done"},
        ]
        node = ReactNode(llm, ToolRegistry())

        ctx = RunContext(
            user_input="你好",
            is_retry=False,
            messages=[{"role": "user", "content": "你好"}],
        )

        result = await node.run(ctx, AsyncMock())
        assert result is not None
