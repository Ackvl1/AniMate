"""Tests for MergeNode — 不 clear ctx.messages，只插 system prompt。"""

import pytest
from animate.core.agent.nodes.merge import MergeNode


class TestMergeNodeNoClear:
    """验证 MergeNode 不再清空已有 messages。"""

    @pytest.fixture
    def node(self):
        return MergeNode()

    @pytest.fixture
    def mock_ctx(self):
        """构造模拟的 RunContext（模拟 agent.py 已注入 user_input）。"""
        class MockCtx:
            def __init__(self):
                self.user_input = "你好"
                # 新架构：agent.py 在 engine.run 前已将 user_input 注入 messages
                self.messages = [
                    {"role": "user", "content": "上一轮问题"},
                    {"role": "assistant", "content": "上一轮回答"},
                    {"role": "user", "content": "你好"},  # agent.py 注入
                ]
                self.extras = {
                    "system_parts": ["你是助手", "情绪指令"],
                    "rag_vector_chunks": [],
                    "rag_keyword_chunks": [],
                }
                self.services = type("S", (), {"memory": None})()
                self.trace_id = "test"
        return MockCtx()

    @pytest.mark.asyncio
    async def test_does_not_clear_existing_messages(self, node, mock_ctx):
        """MergeNode 运行后历史消息仍然存在。"""
        async def noop_emit(*args, **kwargs):
            pass
        await node.run(mock_ctx, noop_emit)
        assert len(mock_ctx.messages) >= 2
        # 历史消息还在
        contents = [m["content"] for m in mock_ctx.messages]
        assert "上一轮问题" in contents
        assert "上一轮回答" in contents

    @pytest.mark.asyncio
    async def test_inserts_system_at_front(self, node, mock_ctx):
        """system prompt 被插入到 messages 最前。"""
        async def noop_emit(*args, **kwargs):
            pass
        await node.run(mock_ctx, noop_emit)
        assert mock_ctx.messages[0]["role"] == "system"
        assert "你是助手" in mock_ctx.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_appends_user_input_at_end(self, node, mock_ctx):
        """user input 在末尾。"""
        async def noop_emit(*args, **kwargs):
            pass
        await node.run(mock_ctx, noop_emit)
        assert mock_ctx.messages[-1]["role"] == "user"
        assert mock_ctx.messages[-1]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_replaces_system_when_already_exists(self, node, mock_ctx):
        """messages 已有 system prompt 时替换而非插入。"""
        mock_ctx.messages.insert(0, {"role": "system", "content": "旧的系统指令"})
        async def noop_emit(*args, **kwargs):
            pass
        await node.run(mock_ctx, noop_emit)
        assert mock_ctx.messages[0]["role"] == "system"
        assert mock_ctx.messages[0]["content"] != "旧的系统指令"
        assert "你是助手" in mock_ctx.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_injects_rag_chunks(self, node, mock_ctx):
        """RAG chunk 被追加到 system prompt 中。"""
        mock_ctx.extras["rag_vector_chunks"] = ["知识1", "知识2"]
        async def noop_emit(*args, **kwargs):
            pass
        await node.run(mock_ctx, noop_emit)
        assert "知识1" in mock_ctx.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_total_messages_order(self, node, mock_ctx):
        """完整消息顺序: system, history..., user。"""
        async def noop_emit(*args, **kwargs):
            pass
        mock_ctx.messages = [
            {"role": "user", "content": "历史1"},
            {"role": "assistant", "content": "历史回复1"},
            {"role": "user", "content": "你好"},  # agent.py 注入
        ]
        await node.run(mock_ctx, noop_emit)
        roles = [m["role"] for m in mock_ctx.messages]
        assert roles == ["system", "user", "assistant", "user"]
