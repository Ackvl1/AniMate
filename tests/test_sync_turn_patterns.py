"""Tests for sync_turn 15 pattern 覆盖"""
import pytest


class TestSyncTurnPatterns:
    """sync_turn 正则提取全覆盖测试"""

    def _extract(self, message: str) -> list[str]:
        """调用 extract_quick_facts 返回提取的事实内容列表"""
        from anima.core.memory.store import MemoryStore
        store = MemoryStore(":memory:")
        fids = store.extract_quick_facts(message)
        facts = []
        for fid in fids:
            row = store._conn.execute(
                "SELECT content FROM facts WHERE fact_id = ?", (fid,)
            ).fetchone()
            if row:
                facts.append(row["content"])
        return facts

    # ── 现有 5 个 pattern（回归） ──

    def test_chinese_preference(self):
        """#1: 我喜欢养猫 → 提取"""
        facts = self._extract("我喜欢养猫")
        assert any("猫" in f for f in facts)

    def test_chinese_want(self):
        """#1: 我想要一个Python脚本 → 提取"""
        facts = self._extract("我想要一个Python脚本")
        assert len(facts) >= 1

    def test_chinese_default(self):
        """#2: 我默认用MacOS → 提取"""
        facts = self._extract("我默认用MacOS")
        assert len(facts) >= 1

    def test_english_preference(self):
        """#3: I prefer Python → 提取"""
        facts = self._extract("I prefer Python")
        assert len(facts) >= 1

    def test_english_default(self):
        """#4: my favorite language is Python → 提取"""
        facts = self._extract("my favorite language is Python")
        assert len(facts) >= 1

    def test_remember_command(self):
        """#5: 记住我喜欢猫 → 提取"""
        facts = self._extract("记住我喜欢猫")
        assert len(facts) >= 1

    # ── 新增 10 个 pattern ──

    def test_address(self):
        """#6: 我住在北京 → 提取"""
        facts = self._extract("我住在北京")
        assert any("北京" in f for f in facts)

    def test_workplace(self):
        """#7: 我在阿里工作 → 提取"""
        facts = self._extract("我在阿里工作")
        assert any("阿里" in f for f in facts)

    def test_profession(self):
        """#8: 我是前端工程师 → 提取"""
        facts = self._extract("我是前端工程师")
        assert any("前端工程师" in f for f in facts)

    def test_possession(self):
        """#9: 我有一只猫咪 → 提取"""
        facts = self._extract("我有一只猫咪")
        assert any("猫咪" in f for f in facts)

    def test_plan(self):
        """#10: 我打算学钢琴 → 提取"""
        facts = self._extract("我打算学钢琴")
        assert any("钢琴" in f for f in facts)

    def test_habit(self):
        """#11: 我每天跑步 → 提取"""
        facts = self._extract("我每天跑步")
        assert any("跑步" in f for f in facts)

    def test_relationship(self):
        """#12: 我朋友在北京 → 提取位置信息"""
        facts = self._extract("我朋友在北京")
        assert any("在北京" in f for f in facts)

    def test_negative_preference(self):
        """#13: 我不喜欢香菜 → 提取"""
        facts = self._extract("我不喜欢香菜")
        assert any("香菜" in f for f in facts)

    def test_location(self):
        """#14: 我在上海 → 提取"""
        facts = self._extract("我在上海")
        assert any("上海" in f for f in facts)

    def test_recent_state(self):
        """#15: 我最近很忙 → 提取"""
        facts = self._extract("我最近很忙")
        assert any("忙" in f for f in facts)

    # ── 不应提取的边界 ──

    def test_greeting_not_extracted(self):
        """寒暄不提取"""
        facts = self._extract("你好啊")
        assert len(facts) == 0

    def test_question_not_extracted(self):
        """一般问题不提取"""
        facts = self._extract("今天天气怎么样")
        assert len(facts) == 0

    def test_short_message_not_extracted(self):
        """短消息不提取"""
        facts = self._extract("好的")
        assert len(facts) == 0
