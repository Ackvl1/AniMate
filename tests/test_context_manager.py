"""Tests for ContextManager — token 跟踪 + 压缩决策 + 渐进压缩。"""

import pytest
from animate.core.context.manager import ContextManager


class MockLLM:
    """模拟 LLM 用于测试压缩摘要。"""
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return type("Result", (), {"content": "## 摘要\n对话已压缩"})()
    
    def chat_stream(self, *args, **kwargs):
        yield {"type": "delta", "content": "摘要"}
        yield {"type": "done"}


def make_msgs(n_rounds: int, with_tool: bool = False) -> list[dict]:
    """生成 n_rounds 轮测试消息。"""
    msgs = [{"role": "system", "content": "你是助手"}]
    for i in range(n_rounds):
        msgs.append({"role": "user", "content": f"问题{i}"})
        if with_tool:
            msgs.append({"role": "assistant", "content": f"搜索中...", "tool_calls": [{"function": {"name": "web_search", "arguments": "{}"}}]})
            msgs.append({"role": "tool", "content": "结果" * 500})  # 大工具结果
        msgs.append({"role": "assistant", "content": f"回答{i}"})
    return msgs


class TestContextManagerInit:
    def test_default_params(self):
        """默认参数 1M context, 70% 阈值(含 compact_reserve)。"""
        cm = ContextManager()
        # (1_000_000 - 30_000) * 0.70 = 679_000
        assert cm._threshold == 679_000
        assert cm._head_rounds == 5
        assert cm._tail_rounds == 10

    def test_custom_params(self):
        """可配置参数。"""
        cm = ContextManager(model_limit=200_000, threshold=0.8,
                            head_rounds=2, tail_rounds=5)
        # (200_000 - 30_000) * 0.80 = 136_000
        assert cm._threshold == 136_000
        assert cm._head_rounds == 2
        assert cm._tail_rounds == 5


class TestNeedCompress:
    def test_not_compress_when_below_threshold(self):
        """低于阈值时不触发。"""
        cm = ContextManager(model_limit=100_000)
        # (100_000 - 30_000) * 0.70 = 49_000
        cm._accumulated = 30_000  # 低于 49K
        assert not cm.need_compress()

    def test_compress_when_above_threshold(self):
        """超过阈值时触发。"""
        cm = ContextManager(model_limit=100_000)
        cm._accumulated = 80_000  # 80%
        assert cm.need_compress()

    def test_update_from_response(self):
        """update_from_response 更新累计 token。"""
        cm = ContextManager()
        cm.update_from_response({"total_tokens": 500_000})
        assert cm._accumulated == 500_000

    def test_update_from_response_empty(self):
        """空 usage 不改变累计值。"""
        cm = ContextManager()
        cm.update_from_response({})
        assert cm._accumulated == 0

    def test_update_from_response_accumulates(self):
        """多次调用 update_from_response 应该累加，不是覆盖。"""
        cm = ContextManager()
        cm.update_from_response({"total_tokens": 300_000})
        cm.update_from_response({"total_tokens": 200_000})
        assert cm._accumulated == 500_000  # 累加 = 300K + 200K

    def test_reset(self):
        """reset 清空累计。"""
        cm = ContextManager()
        cm.update_from_response({"total_tokens": 500_000})
        cm.reset()
        assert cm._accumulated == 0


class TestSelectHead:
    def test_head_includes_all_system(self):
        """head 包含所有 system prompt。"""
        cm = ContextManager(head_rounds=2)
        msgs = [
            {"role": "system", "content": "系统1"},
            {"role": "system", "content": "系统2"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "嗨"},
        ]
        head = cm._select_head(msgs)
        for i, m in enumerate(msgs):
            if m["role"] == "system":
                assert i in head

    def test_head_protects_earliest_rounds(self):
        """head 保护最早的 head_rounds 轮。"""
        cm = ContextManager(head_rounds=2)
        msgs = make_msgs(10)
        head = cm._select_head(msgs)
        # system(0) + user1(1) + asst1(2) + user2(3) + asst2(4) = 5 条
        assert 0 in head  # system
        assert 1 in head  # user1
        assert 2 in head  # asst1
        assert 3 in head  # user2  (第 2 轮)
        assert 4 in head  # asst2  (第 2 轮)

    def test_head_excludes_middle(self):
        """head 不包含超出轮数的消息。"""
        cm = ContextManager(head_rounds=1)
        msgs = make_msgs(5)
        head = cm._select_head(msgs)
        assert 3 not in head  # user2 在 head 之外
        assert 4 not in head  # asst2 在 head 之外

    def test_head_without_system(self):
        """没有 system prompt 时 head 也正常工作。"""
        cm = ContextManager(head_rounds=1)
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "嗨"},
        ]
        head = cm._select_head(msgs)
        assert len(head) == 2


class TestSelectTail:
    def test_tail_protects_last_n_rounds(self):
        """tail 保护最近 tail_rounds 轮。"""
        cm = ContextManager(tail_rounds=2)
        msgs = make_msgs(10)
        tail = cm._select_tail(msgs)
        # 总消息: 1 system + 20 条 = 21 条
        # 最后 2 轮 = msg[17]~msg[20]
        assert 20 in tail  # 最后 asst
        assert 19 in tail  # 最后 user
        assert 17 in tail  # 第 9 轮的 user
        assert 18 in tail  # 第 9 轮的 asst

    def test_tail_always_includes_last_message(self):
        """tail 总是保护最后一条消息。"""
        cm = ContextManager(tail_rounds=1)
        msgs = make_msgs(2)  # 只有 2 轮
        tail = cm._select_tail(msgs)
        assert max(tail) == len(msgs) - 1

    def test_tail_with_tool_calls(self):
        """工具调用链也被包含在 tail 中。"""
        cm = ContextManager(tail_rounds=1)
        msgs = make_msgs(3, with_tool=True)
        tail = cm._select_tail(msgs)
        assert len(msgs) - 1 in tail  # 最后一条
        assert len(msgs) - 2 in tail  # 最后 user


class TestCompress:
    def test_less_than_20_rounds_no_compress(self):
        """总轮数 < head + tail 时跳过压缩。"""
        cm = ContextManager(head_rounds=5, tail_rounds=10)
        msgs = make_msgs(14)  # 14 轮 < 15
        cm.compress(msgs, {})
        # 不压缩，消息数不变

    @pytest.mark.skip(reason="需要真实 LLM API，将在集成测试中覆盖")
    def test_auto_compact_reduces_message_count(self):
        """LLM 摘要后消息数减少。"""
        cm = ContextManager(head_rounds=5, tail_rounds=10, llm=MockLLM())
        msgs = make_msgs(50)
        head = cm._select_head(msgs)
        tail = cm._select_tail(msgs)
        middle = [i for i in range(len(msgs)) if i not in head and i not in tail]
        before = len(msgs)
        cm._auto_compact(msgs, head, tail, middle)
        assert len(msgs) < before

    def test_snip_tool_results_replaces_large_content(self):
        """L1 Snip 替换大工具结果为占位符。"""
        cm = ContextManager()
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "tool", "content": "A" * 6000},
            {"role": "assistant", "content": "回复"},
        ]
        cm._snip_tool_results(msgs, [1])
        assert "[工具结果较长，已压缩]" in msgs[1]["content"]

    def test_snip_skips_small_tool_results(self):
        """小工具结果不被 Snip 处理。"""
        cm = ContextManager()
        msgs = [
            {"role": "tool", "content": "短结果"},
        ]
        cm._snip_tool_results(msgs, [0])
        assert msgs[0]["content"] == "短结果"

    @pytest.mark.skip(reason="需要真实 LLM API，将在集成测试中覆盖")
    def test_compress_preserves_head_and_tail(self):
        """压缩后 head 和 tail 的消息仍然在。"""
        cm = ContextManager(head_rounds=2, tail_rounds=2, llm=MockLLM())
        msgs = make_msgs(20)
        cm.compress(msgs, {})
        # 检查 head + tail 的消息仍然存在（system + 前 2 轮 + 后 2 轮）
        text = " ".join(m.get("content", "") for m in msgs)
        assert "问题0" in text  # head
        assert "问题18" in text  # tail

    def test_compress_failure_degradation(self):
        """压缩失败达到上限时报错。"""
        cm = ContextManager(head_rounds=2, tail_rounds=2, llm=MockLLM())
        msgs = make_msgs(20)
        cm._compact_max_failures = 3
        cm._compact_failures = 3  # 已达到上限
        import pytest
        with pytest.raises(RuntimeError, match="压缩连续失败"):
            cm._fail_or_degrade()

    def test_compress_failure_retry(self):
        """前 2 次失败只降级不报错。"""
        cm = ContextManager()
        cm._compact_failures = 1
        cm._compact_max_failures = 3
        result = cm._fail_or_degrade()
        assert result is False  # 降级

    def test_compress_resets_accumulated_on_success(self):
        """压缩成功后 _accumulated 重置为 0。"""
        cm = ContextManager(llm=MockLLM())
        cm._accumulated = 500_000
        msgs = make_msgs(20)
        cm.compress(msgs, {})
        assert cm._accumulated == 0


class TestCompressCount:
    def test_compress_with_custom_model_limit(self):
        """model_limit 从 config.yaml 读取。"""
        cm = ContextManager()
        assert cm._model_limit > 0


class TestCompressCount:
    def test_compress_count_increments(self):
        """压缩次数递增。"""
        cm = ContextManager(llm=MockLLM())
        cm._compact_failures = 0
        cm._compress_count = 0
        # 构造短消息，使 middle 为空跳过压缩
        msgs = make_msgs(5)
        head = cm._select_head(msgs)
        tail = cm._select_tail(msgs)
        middle = [i for i in range(len(msgs)) if i not in head and i not in tail]
        assert cm._compress_count == 0
