"""Tests for long-term memory — 事实提取 + 注入。"""

import json
import pytest
from anima.core.memory.store import MemoryStore
from anima.core.memory.default_provider import DefaultMemoryProvider
from anima.core.agent import Agent
from anima.core.llm.models import LLMResult


class MockLLM:
    def __init__(self, reply="默认回复"):
        self.reply = reply
        self.call_count = 0
        self.all_messages = []

    def chat(self, messages, tools=None):
        self.all_messages.append(messages)
        self.call_count += 1
        return LLMResult(content=self.reply)

    def chat_stream(self, messages, tools=None):
        self.all_messages.append(messages)
        self.call_count += 1
        yield {"type": "delta", "content": self.reply}
        yield {"type": "done"}


class MockVectorStore:
    def search(self, query_vec):
        return []


class MockKeywordStore:
    def search(self, query):
        return []


def _make_agent(llm, store=None):
    mem_store = store or MemoryStore(db_path=":memory:")
    provider = DefaultMemoryProvider(store=mem_store)
    agent = Agent(
        llm=llm,
        persona="你是测试助手",
        vector_store=MockVectorStore(),
        keyword_store=MockKeywordStore(),
        memory_provider=provider,
    )
    return agent, mem_store


class TestFactExtraction:
    def test_facts_extracted_after_chat(self):
        """chat() 后 memory_store 有正则提取的事实。"""
        llm = MockLLM(reply="你好呀")
        agent, store = _make_agent(llm)
        agent.chat("我喜欢吃猫粮")
        facts = store.search_facts("猫粮")
        assert len(facts) >= 1

    def test_facts_extracted_content_matches(self):
        """regex 提取的事实内容正确。"""
        llm = MockLLM(reply="好的")
        agent, store = _make_agent(llm)
        agent.chat("记住我住在北京")
        facts = store.list_facts()
        all_texts = [f["content"] for f in facts]
        assert any("北京" in t for t in all_texts)

    def test_duplicate_facts_deduplicated(self):
        """相同事实重复 chat 不会重复插入。"""
        llm = MockLLM(reply="喵")
        agent, store = _make_agent(llm)
        agent.chat("我喜欢吃猫粮")
        agent.chat("我再说一遍我喜欢吃猫粮")
        assert store.count() == 1

    def test_irrelevant_message_no_extraction(self):
        """无关消息不提取。"""
        llm = MockLLM(reply="好")
        agent, store = _make_agent(llm)
        agent.chat("今天天气真好")
        assert store.count() == 0


class TestFactInjection:
    def test_facts_injected_to_prompt(self):
        """下一轮 chat 的 system prompt 应包含已有事实。"""
        mem_store = MemoryStore(db_path=":memory:")
        mem_store.add_fact("用户喜欢猫")
        provider = DefaultMemoryProvider(store=mem_store)
        llm = MockLLM(reply="你好")
        agent = Agent(
            llm=llm,
            persona="你是测试助手",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
            memory_provider=provider,
        )
        agent.chat("你还记得我喜欢什么吗")

        # 检查发给 LLM 的 system message 是否包含事实
        assert len(llm.all_messages) >= 1
        system_msgs = [m for m in llm.all_messages[0] if m["role"] == "system"]
        assert len(system_msgs) >= 1
        combined = " ".join(m.get("content", "") for m in system_msgs)
        assert "猫" in combined

    def test_facts_injection_limit(self):
        """事实超过上限时只注入前 10 条。"""
        mem_store = MemoryStore(db_path=":memory:")
        for i in range(20):
            mem_store.add_fact(f"用户偏好{i}")
        provider = DefaultMemoryProvider(store=mem_store)
        llm = MockLLM(reply="好的")
        agent = Agent(
            llm=llm,
            persona="你是测试助手",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
            memory_provider=provider,
        )
        agent.chat("测试")

        system_msgs = [m for m in llm.all_messages[0] if m["role"] == "system"]
        combined = " ".join(m.get("content", "") for m in system_msgs)
        import re
        fact_count = len(re.findall(r"用户偏好\d+", combined))
        assert fact_count <= 10

    def test_reset_keeps_long_term_facts(self):
        """agent.reset() 后 memory_store 的事实仍在。"""
        mem_store = MemoryStore(db_path=":memory:")
        mem_store.add_fact("用户喜欢猫")
        provider = DefaultMemoryProvider(store=mem_store)
        llm = MockLLM(reply="好的")
        agent = Agent(
            llm=llm,
            persona="你是测试助手",
            vector_store=MockVectorStore(),
            keyword_store=MockKeywordStore(),
            memory_provider=provider,
        )
        agent.reset()
        assert mem_store.count() >= 1

    def test_facts_empty_when_no_match(self):
        """无关消息不提取。"""
        llm = MockLLM(reply="你好")
        agent, store = _make_agent(llm)
        agent.chat("你好")
        assert store.count() == 0
