"""Tests for SessionStore — session 生命周期管理 (rotation, freeze, search)。"""

import json
import pytest
from animate.core.session.store import SessionStore


def make_msgs(n_rounds: int, session_id: str = "s1") -> list[dict]:
    """生成 n_rounds 轮测试消息。"""
    msgs = [{"role": "system", "content": f"你是助手 [{session_id}]"}]
    for i in range(n_rounds):
        msgs.append({"role": "user", "content": f"{session_id}: 问题{i}"})
        msgs.append({"role": "assistant", "content": f"{session_id}: 回答{i}"})
    return msgs


class TestSessionLifecycle:
    @pytest.fixture
    def store(self):
        return SessionStore(db_path=":memory:")

    def test_init_creates_table(self, store):
        """初始化后 sessions 表应存在。"""
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        assert row is not None

    def test_init_session(self, store):
        """init_session 创建新 session 并存储消息。"""
        msgs = make_msgs(3)
        store.init_session("abc123", msgs)
        assert store.count() == 1

    def test_init_session_stores_messages(self, store):
        """消息正确序列化存储。"""
        msgs = make_msgs(3)
        store.init_session("abc123", msgs)
        loaded = store.load("abc123")
        assert len(loaded) == len(msgs)

    def test_load_roundtrips_content(self, store):
        """存储的消息与加载的内容一致。"""
        msgs = make_msgs(2)
        store.init_session("s1", msgs)
        loaded = store.load("s1")
        assert loaded[0]["content"] == msgs[0]["content"]
        assert loaded[1]["content"] == msgs[1]["content"]

    def test_load_nonexistent_returns_empty(self, store):
        """加载不存在的 session 返回空列表。"""
        assert store.load("nonexistent") == []

    def test_finalize_marks_session(self, store):
        """finalize 将 session 标记为非活跃。"""
        store.init_session("s1", make_msgs(2))
        store.finalize("s1")
        assert not store.is_active("s1")

    def test_init_session_is_active(self, store):
        """init_session 创建的 session 默认活跃。"""
        store.init_session("s1", make_msgs(2))
        assert store.is_active("s1")

    def test_count(self, store):
        """count 返回 session 总数。"""
        store.init_session("s1", make_msgs(1))
        store.init_session("s2", make_msgs(1))
        assert store.count() == 2

    def test_list_sessions(self, store):
        """list_sessions 返回所有 session。"""
        store.init_session("s1", make_msgs(1))
        store.init_session("s2", make_msgs(1))
        sessions = store.list_sessions()
        assert len(sessions) == 2
        sids = [s["session_id"] for s in sessions]
        assert "s1" in sids
        assert "s2" in sids

    def test_list_active_only(self, store):
        """list_sessions 可过滤仅活跃 session。"""
        store.init_session("s1", make_msgs(1))
        store.init_session("s2", make_msgs(1))
        store.finalize("s2")
        active = store.list_sessions(active_only=True)
        assert len(active) == 1
        assert active[0]["session_id"] == "s1"

    def test_list_includes_parent(self, store):
        """list_sessions 结果包含 parent_id。"""
        store.init_session("s1", make_msgs(1), parent_id="root")
        sessions = store.list_sessions()
        assert sessions[0]["parent_id"] == "root"

    def test_finalize_nonexistent_no_error(self, store):
        """finalize 不存在的 session 不抛异常。"""
        store.finalize("nonexistent")

    def test_multiple_finalize_no_double(self, store):
        """重复 finalize 不影响计数。"""
        store.init_session("s1", make_msgs(1))
        store.finalize("s1")
        store.finalize("s1")
        assert store.count() == 1

    def test_overwrite_session(self, store):
        """同名 session 重新 init 会覆盖。"""
        msgs1 = make_msgs(1)
        msgs2 = make_msgs(1, session_id="s1")
        store.init_session("s1", msgs1)
        store.init_session("s1", msgs2)
        assert store.count() == 1


class TestSessionAncestors:
    @pytest.fixture
    def store(self):
        return SessionStore(db_path=":memory:")

    def test_no_parent_returns_empty(self, store):
        """无父 session 时返回自身。"""
        store.init_session("s1", make_msgs(1))
        chain = store.ancestor_chain("s1")
        assert chain == ["s1"]

    def test_with_parents(self, store):
        """返回完整的祖先链。"""
        store.init_session("root", make_msgs(1))
        store.init_session("root_c1", make_msgs(1), parent_id="root")
        store.init_session("root_c2", make_msgs(1), parent_id="root_c1")
        chain = store.ancestor_chain("root_c2")
        assert chain == ["root_c2", "root_c1", "root"]

    def test_nonexistent_returns_empty(self, store):
        """不存在的 session 返回空。"""
        assert store.ancestor_chain("nonexistent") == []

    def test_search_ancestors(self, store):
        """跨祖先 session 搜索消息（LIKE 查询）。"""
        store.init_session("root", [
            {"role": "user", "content": "我喜欢猫"},
        ])
        store.init_session("root_c1", [
            {"role": "user", "content": "今天天气好"},
        ], parent_id="root")
        results = store.search_ancestors("root_c1", "猫")
        assert len(results) >= 1
        assert any("猫" in r["content"] for r in results)

    def test_search_ancestors_limit(self, store):
        """search_ancestors 受 limit 限制。"""
        for i in range(5):
            sid = f"root_c{i}" if i > 0 else "root"
            parent = f"root_c{i-1}" if i > 0 else None
            store.init_session(sid, [
                {"role": "user", "content": f"消息{i}"},
            ], parent_id=parent)
        results = store.search_ancestors("root_c4", "消息", limit=2)
        assert len(results) <= 2

    def test_search_ancestors_empty(self, store):
        """空查询返回空。"""
        store.init_session("s1", make_msgs(1))
        assert store.search_ancestors("s1", "") == []
