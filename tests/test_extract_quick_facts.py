"""Tests for MemoryStore.extract_quick_facts — regex-based fact extraction."""

import pytest
from animate.core.memory.store import MemoryStore


class TestExtractQuickFacts:
    @pytest.fixture
    def store(self):
        return MemoryStore(db_path=":memory:")

    def test_chinese_preference(self, store):
        """'我喜欢吃猫粮' 应提取出用户偏好。"""
        fids = store.extract_quick_facts("我喜欢吃猫粮")
        assert len(fids) >= 1
        facts = store.search_facts("猫粮")
        assert any("猫粮" in f["content"] for f in facts)

    def test_english_preference(self, store):
        fids = store.extract_quick_facts("I prefer dark mode")
        assert len(fids) >= 1

    def test_remember(self, store):
        """'记住我喜欢编程' 应提取。"""
        fids = store.extract_quick_facts("记住我喜欢编程")
        assert len(fids) >= 1

    def test_remember_with_direction(self, store):
        """'记住别叫我先生' 应提取。"""
        fids = store.extract_quick_facts("记住别叫我先生")
        assert len(fids) >= 1

    def test_no_match(self, store):
        """无关消息不提取。"""
        fids = store.extract_quick_facts("今天天气怎么样")
        assert fids == []

    def test_empty_message(self, store):
        fids = store.extract_quick_facts("")
        assert fids == []

    def test_short_fact_filtered(self, store):
        """太短的事实（<=3字符）不提取。"""
        fids = store.extract_quick_facts("记住a")
        assert fids == []

    def test_dedup_across_turns(self, store):
        """多轮相同偏好不重复。"""
        store.extract_quick_facts("我喜欢吃猫粮")
        store.extract_quick_facts("我喜欢吃猫粮")
        assert store.count() == 1
