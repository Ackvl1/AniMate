"""Tests for config.yaml compress parameters (Workstream A)."""
import pytest
from animate.core.context.manager import ContextManager


class TestConfigCompress:
    """config.yaml 压缩参数加载。"""

    def test_default_values(self):
        """默认值与硬编码一致。"""
        cm = ContextManager()
        assert cm._threshold == int(1_000_000 * 0.70 - 30_000 * 0.70)
        assert cm._head_rounds == 5
        assert cm._tail_rounds == 10
        assert cm._compact_reserve == 30_000

    def test_custom_values(self):
        """自定义参数生效。"""
        cm = ContextManager(
            model_limit=128_000,
            threshold=0.60,
            head_rounds=3,
            tail_rounds=5,
            compact_reserve=10_000,
        )
        assert cm._head_rounds == 3
        assert cm._tail_rounds == 5
        assert cm._compact_reserve == 10_000

    def test_reset_compress_count(self):
        """reset() 重置 _compress_count。"""
        cm = ContextManager()
        cm._compress_count = 5
        cm.reset()
        assert cm._compress_count == 0
