"""Tests for on_session_end LLM 深度事实提取"""
import pytest
from unittest.mock import MagicMock


class MockLLM:
    """Mock LLM for session_end tests."""

    def __init__(self, response=None, raise_exception=False, should_be_called=True):
        self._response = response or '{"facts": []}'
        self._raise = raise_exception
        self._should_be_called = should_be_called
        self.call_count = 0
        self.last_messages = None

    def chat(self, messages, tools=None):
        self.call_count += 1
        self.last_messages = messages
        if self._raise:
            raise RuntimeError("LLM API error")
        result = MagicMock()
        result.content = self._response
        return result


def _make_user_msgs(count):
    """构造 N 条 user 消息 + N 条 assistant 回复。"""
    msgs = []
    for i in range(count):
        msgs.append({"role": "user", "content": f"用户消息 {i}"})
        msgs.append({"role": "assistant", "content": f"角色回复 {i}"})
    return msgs


class TestSessionEndExtraction:
    """on_session_end LLM 深度提取测试"""

    def test_skip_when_fewer_than_4_user_messages(self):
        """user 消息 < 4 条 → 跳过提取，不调 LLM"""
        from animate.core.memory.default_provider import DefaultMemoryProvider
        provider = DefaultMemoryProvider()
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
            {"role": "user", "content": "再见"},
        ]
        llm = MockLLM(should_be_called=False)
        provider.on_session_end(messages, llm=llm)
        assert llm.call_count == 0
        assert provider._store.count() == 0

    def test_extract_facts_from_full_conversation(self):
        """user 消息 ≥ 4 条 → 调 LLM → 解析 → add_fact"""
        from animate.core.memory.default_provider import DefaultMemoryProvider
        provider = DefaultMemoryProvider()
        messages = [
            {"role": "user", "content": "我喜欢弹钢琴"},
            {"role": "assistant", "content": "哦？你弹什么曲子？"},
            {"role": "user", "content": "主要是古典乐"},
            {"role": "assistant", "content": "很棒呢"},
            {"role": "user", "content": "我最近在练肖邦"},
            {"role": "assistant", "content": "肖邦很棒"},
            {"role": "user", "content": "我还喜欢听爵士"},
        ]
        llm = MockLLM(response='{"facts": [{"content": "用户喜欢弹钢琴", "category": "user_pref"}, {"content": "用户最近在练肖邦", "category": "general"}]}')
        provider.on_session_end(messages, llm=llm)
        facts = provider._store.list_facts()
        assert len(facts) == 2
        assert any("钢琴" in f["content"] for f in facts)
        assert all(f["trust_score"] == 0.7 for f in facts)

    def test_persona_dialogue_not_extracted(self):
        """assistant 的表演性台词不入库（prompt 约束生效）"""
        from animate.core.memory.default_provider import DefaultMemoryProvider
        provider = DefaultMemoryProvider()
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "我是丰川祥子，我讨厌孤独"},
            {"role": "user", "content": "我喜欢猫"},
            {"role": "assistant", "content": "猫很可爱呢"},
            {"role": "user", "content": "我家有两只猫"},
        ]
        llm = MockLLM(response='{"facts": [{"content": "用户喜欢猫", "category": "user_pref"}, {"content": "用户家有两只猫", "category": "general"}]}')
        provider.on_session_end(messages, llm=llm)
        facts = provider._store.list_facts()
        assert not any("祥子" in f["content"] or "孤独" in f["content"] for f in facts)

    def test_dedup_after_normalization(self):
        """归一化后 "SC2" → "星际争霸2" 与已存事实去重"""
        from animate.core.memory.default_provider import DefaultMemoryProvider
        provider = DefaultMemoryProvider()
        provider._store.add_fact("用户喜欢星际争霸2", trust_score=0.3)
        messages = _make_user_msgs(4)
        llm = MockLLM(response='{"facts": [{"content": "用户喜欢SC2", "category": "user_pref"}]}')
        provider.on_session_end(messages, llm=llm)
        facts = provider._store.list_facts()
        sc2_facts = [f for f in facts if "星际" in f["content"]]
        assert len(sc2_facts) == 1

    def test_llm_failure_does_not_crash_reset(self):
        """LLM 调用失败 → on_session_end 不抛异常"""
        from animate.core.memory.default_provider import DefaultMemoryProvider
        provider = DefaultMemoryProvider()
        messages = _make_user_msgs(4)
        llm = MockLLM(raise_exception=True)
        provider.on_session_end(messages, llm=llm)
        assert provider._store.count() == 0

    def test_dual_write_state_and_audit(self):
        """fact 同时写入 MemoryStore（状态层）和 ChatLogDB（审计层）"""
        from animate.core.memory.default_provider import DefaultMemoryProvider
        from animate.core.memory.store import MemoryStore
        from animate.core.log import ChatLogDB
        store = MemoryStore(":memory:")
        log_db = ChatLogDB(":memory:")
        provider = DefaultMemoryProvider(store=store, log_db=log_db)
        messages = _make_user_msgs(4)
        llm = MockLLM(response='{"facts": [{"content": "用户喜欢音乐", "category": "user_pref"}]}')
        provider.on_session_end(messages, llm=llm)
        # 状态层
        assert store.count() == 1
        # 审计层
        audit = log_db.query_facts(limit=10)
        assert len(audit) == 1
        assert audit[0]["source_trace"] == "session_end"
