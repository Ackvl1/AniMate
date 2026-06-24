"""Tests for MemoryStore trust scoring (Workstream C)."""
import pytest
from animate.core.memory.store import MemoryStore


class TestTrustScoring:
    """信任分系统：来源分级 + 检索晋升 + 冲突合并。"""

    def setup_method(self):
        self.store = MemoryStore(db_path=":memory:")

    def test_default_trust_is_0_3(self):
        """不传 trust_score 时默认 0.3。"""
        fid = self.store.add_fact("用户喜欢咖啡")
        rows = self.store.list_facts()
        assert len(rows) == 1
        assert rows[0]["trust_score"] == pytest.approx(0.3)

    def test_custom_trust_0_7(self):
        """传入 trust_score=0.7 时使用 0.7。"""
        fid = self.store.add_fact("用户喜欢咖啡", trust_score=0.7)
        rows = self.store.list_facts()
        assert rows[0]["trust_score"] == pytest.approx(0.7)

    def test_merge_trust_upgrade(self):
        """冲突时新信任分更高 → 提升。"""
        self.store.add_fact("用户喜欢咖啡", trust_score=0.3)
        self.store.add_fact("用户喜欢咖啡", trust_score=0.7)
        rows = self.store.list_facts()
        assert len(rows) == 1
        assert rows[0]["trust_score"] == pytest.approx(0.7)

    def test_merge_trust_no_downgrade(self):
        """冲突时新信任分更低 → 不降级。"""
        self.store.add_fact("用户喜欢咖啡", trust_score=0.7)
        self.store.add_fact("用户喜欢咖啡", trust_score=0.3)
        rows = self.store.list_facts()
        assert len(rows) == 1
        assert rows[0]["trust_score"] == pytest.approx(0.7)

    def test_retrieval_count_increment(self):
        """search_facts 命中后 retrieval_count +1。"""
        self.store.add_fact("用户喜欢咖啡", trust_score=0.5)
        # 初始 retrieval_count = 0
        rows = self.store.list_facts()
        assert rows[0]["retrieval_count"] == 0

        # 搜索命中
        results = self.store.search_facts("咖啡")
        assert len(results) == 1

        # retrieval_count 递增
        rows = self.store.list_facts()
        assert rows[0]["retrieval_count"] == 1

    def test_retrieval_boost_in_order(self):
        """retrieval_count 影响排序：高 retrieval 排前面。"""
        self.store.add_fact("事实A", trust_score=0.5)
        self.store.add_fact("事实B", trust_score=0.5)

        # 多次搜索事实B
        for _ in range(5):
            self.store.search_facts("事实B")

        # 事实B 因为 retrieval_count 高，排在前面
        results = self.store.search_facts("事实")
        assert results[0]["content"] == "事实B"

    def test_retrieval_boost_capped(self):
        """1000 次检索不会无限碾压（cap 有效）。"""
        self.store.add_fact("高分事实", trust_score=0.7)
        self.store.add_fact("低分事实", trust_score=0.3)

        # 低分事实被检索 1000 次
        for _ in range(1000):
            self.store.search_facts("低分事实")

        # 高分事实仍然排在前面（cap 0.2 不够翻盘 0.4 的差距）
        results = self.store.search_facts("事实")
        assert results[0]["content"] == "高分事实"

    def test_search_read_only_does_not_increment(self):
        """list_facts 不触发 retrieval_count 递增。"""
        self.store.add_fact("用户喜欢咖啡")
        self.store.list_facts()
        rows = self.store.list_facts()
        assert rows[0]["retrieval_count"] == 0
