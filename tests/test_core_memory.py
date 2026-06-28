"""Tests for conversation utility functions。"""

from anima.core.memory.conversation import count_rounds, estimate_tokens, find_message_boundaries


class TestCountRounds:
    def test_empty(self):
        assert count_rounds([]) == 0

    def test_two_rounds(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        assert count_rounds(msgs) == 2

    def test_no_assistant(self):
        msgs = [{"role": "user", "content": "q"}]
        assert count_rounds(msgs) == 0


class TestEstimateTokens:
    def test_non_empty(self):
        msgs = [{"role": "user", "content": "你好世界"}]
        assert estimate_tokens(msgs) > 0

    def test_empty_content(self):
        msgs = [{"role": "user", "content": ""}]
        assert estimate_tokens(msgs) == 0

    def test_multiple_messages(self):
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ]
        assert estimate_tokens(msgs) > 0


class TestFindBoundaries:
    def test_head_includes_system(self):
        msgs = [{"role": "system", "content": "你是助手"}]
        head, tail = find_message_boundaries(msgs, head_rounds=1, tail_rounds=1)
        assert 0 in head

    def test_tail_includes_last(self):
        msgs = [{"role": "user", "content": "hi"}]
        _, tail = find_message_boundaries(msgs)
        assert len(tail) == 1
