"""Tests for MemoryStore — SQLite + FTS5 事实存储。"""

import pytest
from anima.core.memory.store import MemoryStore


class TestMemoryStore:
    @pytest.fixture
    def store(self):
        return MemoryStore(db_path=":memory:")

    def test_add_fact(self, store):
        fact_id = store.add_fact("用户喜欢猫", category="user_pref")
        assert fact_id > 0

    def test_add_fact_dedup(self, store):
        """重复内容不重复插入。"""
        id1 = store.add_fact("用户喜欢猫")
        id2 = store.add_fact("用户喜欢猫")
        assert id1 == id2

    def test_search_fact(self, store):
        store.add_fact("用户喜欢猫")
        results = store.search_facts("猫")
        assert len(results) >= 1

    def test_search_no_match(self, store):
        store.add_fact("用户喜欢猫")
        assert store.search_facts("狗") == []

    def test_search_limit(self, store):
        for i in range(20):
            store.add_fact(f"事实{i}")
        results = store.search_facts("事实", limit=3)
        assert len(results) == 3

    def test_list_facts(self, store):
        for i in range(5):
            store.add_fact(f"事实{i}")
        assert store.count() == 5

    def test_remove_fact(self, store):
        fid = store.add_fact("用户喜欢猫")
        assert store.remove_fact(fid)
        assert store.count() == 0

    def test_remove_nonexistent(self, store):
        assert not store.remove_fact(9999)

    def test_update_trust(self, store):
        """信任评分更新。"""
        fid = store.add_fact("用户喜欢猫")
        store.update_fact(fid, trust_delta=0.1)
        facts = store.search_facts("猫")
        assert facts[0]["trust_score"] >= 0.35  # default 0.3 + delta 0.1

    def test_trust_clamped(self, store):
        """信任评分在 [0, 1] 之间。"""
        fid = store.add_fact("用户喜欢猫")
        store.update_fact(fid, trust_delta=10.0)
        facts = store.search_facts("猫")
        assert facts[0]["trust_score"] == 1.0

    def test_list_by_category(self, store):
        store.add_fact("偏好猫", category="user_pref")
        store.add_fact("项目用Python", category="project")
        results = store.list_facts(category="user_pref")
        assert len(results) == 1
        assert results[0]["content"] == "偏好猫"

    def test_record_feedback_helpful(self, store):
        """feedback helpful 增加信任。"""
        fid = store.add_fact("事实A")
        result = store.record_feedback(fid, helpful=True)
        assert result["new_trust"] > result["old_trust"]
        assert result["helpful_count"] == 1

    def test_record_feedback_unhelpful(self, store):
        """feedback unhelpful 减少信任。"""
        fid = store.add_fact("事实A")
        result = store.record_feedback(fid, helpful=False)
        assert result["new_trust"] < result["old_trust"]

    def test_record_feedback_nonexistent(self, store):
        with pytest.raises(KeyError):
            store.record_feedback(9999, helpful=True)

    def test_count_after_init(self, store):
        assert store.count() == 0
