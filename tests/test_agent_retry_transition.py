"""Tests for Agent retry 过渡句注入"""

import json
from anima.core.agent import Agent
from anima.core.agent.response import AgentResponse
from anima.core.llm.models import LLMResult


class MockLLM:
    """按顺序返回预设响应"""
    def __init__(self):
        self.responses: list[LLMResult] = []
        self.call_count = 0
        self.all_messages = []

    def chat(self, messages, tools=None):
        self.all_messages.append(messages)
        resp = (self.responses[self.call_count]
                if self.call_count < len(self.responses)
                else LLMResult(content="默认回复"))
        self.call_count += 1
        return resp

    def chat_stream(self, messages, tools=None):
        """同步流式（返回 generator）"""
        return self._stream(messages, tools)

    async def chat_stream_async(self, messages, tools=None):
        """异步流式"""
        for event in self._stream(messages, tools):
            yield event

    def _stream(self, messages, tools=None):
        """内部：生成流式事件"""
        self.all_messages.append(messages)
        resp = (self.responses[self.call_count]
                if self.call_count < len(self.responses)
                else LLMResult(content="默认回复"))
        self.call_count += 1
        if resp.tool_calls:
            for i, tc in enumerate(resp.tool_calls):
                import json
                yield {
                    "type": "tool_call",
                    "index": i,
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments) if tc.arguments else "{}",
                }
        if resp.content:
            yield {"type": "delta", "content": resp.content}
        yield {"type": "done"}


class MockVectorStore:
    def search(self, query_vec):
        return [("祥子出生于丰川家族", 0.85)]


class MockKeywordStore:
    def search(self, query):
        return [("祥子是 Ave Mujica 的键盘手", 0.9)]


class TestAgentRetryTransition:
    """Agent retry 时注入过渡句指令"""

    def test_retry_injects_correction_instruction(self):
        """当 Reflect 触发 level 3 retry，agent 在 messages 中注入修正指令"""
        llm = MockLLM()
        # 三个响应：第一次回复 → reflect 评估 → retry 回复
        llm.responses = [
            LLMResult(content='[{"text": "你好", "emotion": "calm"}]'),
            LLMResult(content='{"level": 3, "feedback": "语气不够傲慢"}'),
            LLMResult(content='[{"text": "哼…重新说：你好", "emotion": "proud"}]'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子，一个高傲的少女",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        resp = agent.chat("你好")

        # 验证：有一条 system 消息包含过渡句指令
        all_system_contents = []
        for messages in llm.all_messages:
            for msg in messages:
                if msg["role"] == "system":
                    all_system_contents.append(msg["content"])

        has_transition = any(
            "过渡语" in content or "收回前言" in content
            for content in all_system_contents
        )
        assert has_transition, (
            f"没有找到包含过渡句指令的 system 消息。\n"
            f"所有 system 消息内容：\n" + "\n---\n".join(all_system_contents)
        )

    def test_retry_instruction_contains_feedback(self):
        """注入的指令包含 reflect 的 feedback 内容"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content='[{"text": "你好", "emotion": "calm"}]'),
            LLMResult(content='{"level": 3, "feedback": "语气太过温和，没有傲气"}'),
            LLMResult(content='[{"text": "哼…你有何事", "emotion": "proud"}]'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        agent.chat("你好")

        found = False
        for messages in llm.all_messages:
            for msg in messages:
                if msg["role"] == "system" and "语气太过温和" in msg["content"]:
                    found = True
        assert found, "feedback 内容未出现在 system 消息中"

    def test_before_retry_injects_instruction(self):
        """Reflect 返回 level 4（重新检索），也能注入修正指令"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content='[{"text": "这不对", "emotion": "calm"}]'),
            LLMResult(content='{"level": 4, "feedback": "需要重新检索上下文"}'),
            LLMResult(content='[{"text": "修正后的正确回答", "emotion": "calm"}]'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        agent.chat("你好")

        all_system_contents = []
        for messages in llm.all_messages:
            for msg in messages:
                if msg["role"] == "system":
                    all_system_contents.append(msg["content"])

        has_transition = any(
            "过渡语" in content or "收回前言" in content
            for content in all_system_contents
        )
        assert has_transition, (
            "level 4 retry 后应注入过渡句指令\n"
            + "\n---\n".join(all_system_contents)
        )

    def test_no_retry_no_injection(self):
        """reflect 通过（level < 3）时不注入修正指令"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content='[{"text": "你好", "emotion": "calm"}]'),
            LLMResult(content='{"level": 1, "feedback": "小问题，但可接受"}'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        agent.chat("你好")

        all_system_contents = []
        for messages in llm.all_messages:
            for msg in messages:
                if msg["role"] == "system":
                    all_system_contents.append(msg["content"])

        has_transition = any(
            "过渡语" in content or "收回前言" in content
            for content in all_system_contents
        )
        assert not has_transition, (
            "reflect 通过时不应注入过渡句指令，但找到了\n"
            + "\n---\n".join(all_system_contents)
        )


class TestAgentRetryIntegration:
    """完整 chat() 下的 retry 集成测试"""

    def test_retry_messages_contain_injection_before_react(self):
        """retry 后的 LLM 调用 messages 中包含 injection system message"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content='[{"text": "这不对", "emotion": "calm"}]'),
            LLMResult(content='{"level": 3, "feedback": "需要更傲慢的语气"}'),
            LLMResult(content='[{"text": "哼……本小姐重新说。你好。", "emotion": "proud"}]'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        resp = agent.chat("你好")

        # 第三条 LLM 消息（retry 的 ReactNode）应该包含 injection
        assert len(llm.all_messages) >= 3, f"至少 3 次 LLM 调用，实际 {len(llm.all_messages)}"
        retry_messages = llm.all_messages[2]  # 第三次 LLM 调用

        # 找到其中 system 角色的 injection 消息
        injection_msgs = [
            m for m in retry_messages
            if m["role"] == "system" and "过渡语" in m["content"]
        ]
        assert len(injection_msgs) == 1, (
            f"retry 的 LLM 调用应有 1 条 injection，找到 {len(injection_msgs)}\n"
            f"retry_messages: {retry_messages}"
        )

        # 确认 injection 包含 feedback
        assert "需要更傲慢的语气" in injection_msgs[0]["content"]

        # 确认最终响应非空
        assert resp.text is not None
        assert len(resp.text) > 0

    def test_retry_injection_placement(self):
        """injection system message 在 retry 的 messages 中结构正确"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content='[{"text": "你好", "emotion": "calm"}]'),
            LLMResult(content='{"level": 3, "feedback": "语气不对"}'),
            LLMResult(content='[{"text": "哼。你好。", "emotion": "proud"}]'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        resp = agent.chat("你好")

        retry_messages = llm.all_messages[2]

        # 找到 injection 消息
        injection_msgs = [
            m for m in retry_messages
            if m["role"] == "system" and "过渡语" in m["content"]
        ]
        assert len(injection_msgs) >= 1, "retry 的 LLM 调用缺少 injection"

        # injection 应包含完整的输出结构要求
        content = injection_msgs[0]["content"]
        assert "收回前言" in content or "过渡语" in content
        assert "修正后的回答" in content
        assert "语气不对" in content  # feedback 也在

    def test_retry_injection_per_retry(self):
        """每次 retry 都会追加新的 injection（含对应 feedback）"""
        llm = MockLLM()
        llm.responses = [
            LLMResult(content='[{"text": "第一轮", "emotion": "calm"}]'),
            LLMResult(content='{"level": 3, "feedback": "语气不对"}'),
            LLMResult(content='[{"text": "哼。修正。", "emotion": "proud"}]'),
            LLMResult(content='{"level": 3, "feedback": "还是不对"}'),
            LLMResult(content='[{"text": "哼！再修正。", "emotion": "proud"}]'),
        ]
        agent = Agent.create_default(
            llm=llm,
            persona="你是丰川祥子",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
        )
        resp = agent.chat("你好")

        # 统计所有 LLM 调用中的 injection system 消息
        total_injections = 0
        for messages in llm.all_messages:
            for msg in messages:
                if msg["role"] == "system" and "过渡语" in msg["content"]:
                    total_injections += 1

        # 两次 retry，应至少有 2 条 injection（第一次 inj 会残留到第二次）
        assert total_injections >= 2, (
            f"两次 retry 应至少 2 条 injection，实际 {total_injections}"
        )
        # 第二次 retry 的 injection 包含对应的 feedback
        latest_injection = None
        for messages in llm.all_messages:
            for msg in messages:
                if msg["role"] == "system" and "过渡语" in msg["content"]:
                    latest_injection = msg["content"]
        assert latest_injection is not None
        assert "还是不对" in latest_injection
