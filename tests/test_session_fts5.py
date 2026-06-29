"""Tests for SessionStore FTS5 全文索引升级。"""

import json
import pytest
from anima.core.session.store import SessionStore


@pytest.fixture
def store():
    return SessionStore(db_path=":memory:")


class TestFTS5TrigramIndex:
    """FTS5 trigram 索引基础测试。"""

    def test_fts5_table_exists(self, store):
        """FTS5 虚拟表 session_messages_fts 应存在。"""
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_messages_fts'"
        ).fetchone()
        assert row is not None

    def test_fts5_chinese_search(self, store):
        """FTS5 trigram 能搜索中文内容（需 3+ 字符）。"""
        store.init_session("s1", [
            {"role": "user", "content": "我喜欢吃火锅"},
            {"role": "assistant", "content": "火锅很好吃呢"},
        ])
        results = store.search_ancestors("s1", "火锅很")
        assert len(results) >= 1
        assert any("火锅" in r["content"] for r in results)

    def test_fts5_english_search(self, store):
        """FTS5 trigram 能搜索英文内容。"""
        store.init_session("s1", [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
        ])
        results = store.search_ancestors("s1", "capital")
        assert len(results) >= 1
        assert any("capital" in r["content"] for r in results)

    def test_fts5_japanese_search(self, store):
        """FTS5 trigram 能搜索日文内容（需 3+ 字符）。"""
        store.init_session("s1", [
            {"role": "user", "content": "東京は日本の首都です"},
            {"role": "assistant", "content": "はい、東京は日本の首都です"},
        ])
        results = store.search_ancestors("s1", "東京は日")
        assert len(results) >= 1
        assert any("東京" in r["content"] for r in results)

    def test_fts5_bm25_ranking(self, store):
        """FTS5 搜索结果按 BM25 相关性排序。"""
        store.init_session("s1", [
            {"role": "user", "content": "Python 是一种编程语言"},
            {"role": "assistant", "content": "Python 可以用来做很多事"},
        ])
        store.init_session("s2", [
            {"role": "user", "content": "Python 是最好的编程语言，我每天都在用 Python 编程"},
        ], parent_id="s1")
        results = store.search_ancestors("s2", "Python 是最")
        # 更相关的消息应该排在前面
        assert len(results) >= 1
        # s2 的消息包含更多 "Python 是最"，应该排在前面
        assert results[0]["session_id"] == "s2"

    def test_fts5_no_match_returns_empty(self, store):
        """FTS5 搜索无匹配返回空列表。"""
        store.init_session("s1", [
            {"role": "user", "content": "今天天气好"},
        ])
        results = store.search_ancestors("s1", "不存在的内容xyz")
        assert results == []

    def test_fts5_context_window(self, store):
        """FTS5 搜索返回匹配消息的上下文。"""
        store.init_session("s1", [
            {"role": "user", "content": "第一条消息"},
            {"role": "assistant", "content": "第二条消息"},
            {"role": "user", "content": "第三条消息 包含关键词"},
            {"role": "assistant", "content": "第四条消息"},
            {"role": "user", "content": "第五条消息"},
        ])
        results = store.search_ancestors("s1", "关键词", context_window=2)
        # 应该返回匹配消息及其上下文
        assert len(results) >= 1
        # 验证上下文包含前后消息
        contents = [r["content"] for r in results]
        assert any("第二条消息" in c for c in contents) or any("第四条消息" in c for c in contents)


class TestBrowseMode:
    """Browse 模式测试：无 query 时返回最近 session 列表。"""

    def test_browse_returns_sessions(self, store):
        """Browse 模式返回 session 列表。"""
        store.init_session("s1", [
            {"role": "user", "content": "第一条消息"},
            {"role": "assistant", "content": "第一条回复"},
        ])
        store.init_session("s2", [
            {"role": "user", "content": "第二条消息"},
            {"role": "assistant", "content": "第二条回复"},
        ])
        results = store.search_ancestors("s2", "")
        assert len(results) >= 2
        # 应该包含 session 元数据
        assert any(r.get("session_id") for r in results)

    def test_browse_with_limit(self, store):
        """Browse 模式支持 limit 参数。"""
        for i in range(5):
            store.init_session(f"s{i}", [
                {"role": "user", "content": f"消息{i}"},
            ])
        results = store.search_ancestors("s4", "", limit=3)
        assert len(results) <= 3

    def test_browse_shows_preview(self, store):
        """Browse 模式显示 session 首条消息预览。"""
        store.init_session("s1", [
            {"role": "user", "content": "这是预览内容"},
            {"role": "assistant", "content": "回复内容"},
        ])
        results = store.search_ancestors("s1", "")
        assert len(results) >= 1
        # 应该包含预览信息
        assert any("预览" in str(r) for r in results)


class TestSessionSearchToolMultiMode:
    """SessionSearchTool 多模式测试。"""

    def test_tool_search_mode(self):
        """Tool 在有 query 时使用 Search 模式。"""
        from anima.core.tools.function.memory_tools import SessionSearchTool
        store = SessionStore(db_path=":memory:")
        store.init_session("s1", [
            {"role": "user", "content": "测试消息内容"},
        ])
        tool = SessionSearchTool(store, "s1")
        result = tool.execute(query="测试消")
        data = json.loads(result)
        assert len(data) >= 1

    def test_tool_browse_mode(self):
        """Tool 在无 query 时使用 Browse 模式。"""
        from anima.core.tools.function.memory_tools import SessionSearchTool
        store = SessionStore(db_path=":memory:")
        store.init_session("s1", [
            {"role": "user", "content": "消息1"},
        ])
        tool = SessionSearchTool(store, "s1")
        result = tool.execute()
        data = json.loads(result)
        # Browse 模式应该返回 session 列表
        assert isinstance(data, list)
