"""Tests for SessionStore.save_messages — 每轮持久化。"""

import json
import pytest
from animate.core.session.store import SessionStore


class TestSaveMessages:
    @pytest.fixture
    def store(self):
        s = SessionStore(db_path=":memory:")
        s.init_session("s1", [{"role": "user", "content": "hello"}])
        return s

    def test_save_updates_messages(self, store):
        new_msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        store.save_messages("s1", new_msgs)
        loaded = store.load("s1")
        assert len(loaded) == 2
        assert loaded[1]["content"] == "hi"

    def test_save_nonexistent_no_error(self, store):
        """保存到不存在的 session 不抛异常。"""
        store.save_messages("nonexistent", [{"role": "user", "content": "hi"}])

    def test_save_preserves_existing_fields(self, store):
        """save 只更新 messages，不影响其他字段。"""
        store.finalize("s1")
        store.save_messages("s1", [{"role": "user", "content": "new"}])
        assert not store.is_active("s1")
        assert store.load("s1")[0]["content"] == "new"

    def test_save_empty_list(self, store):
        store.save_messages("s1", [])
        assert store.load("s1") == []

    def test_save_roundtrip_large(self, store):
        """大量消息的保存和加载。"""
        msgs = [{"role": "user" if i % 2 == 0 else "assistant",
                 "content": f"消息{i}" * 10} for i in range(100)]
        store.save_messages("s1", msgs)
        loaded = store.load("s1")
        assert len(loaded) == 100
        assert loaded[99]["content"] == "消息99" * 10
