"""Tests for Analysis Scratchpad — 两步评估（analysis + summary 分拆，一次 LLM 调用）"""
import pytest
from unittest.mock import AsyncMock

from animate.core.engine.context import RunContext
from animate.core.agent.nodes.reflect import ReflectNode
from animate.core.llm.models import LLMResult


class MockLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1
        return LLMResult(content=self.reply)


class TestAnalysisScratchpad:
    @pytest.mark.asyncio
    async def test_analysis_tag_present_in_prompt(self):
        """评估 prompt 应要求先写 <analysis> 分析再写 <summary>"""
        node = ReflectNode(llm=MockLLM(reply='{"level": 0, "feedback": ""}'))
        # 验证 EVALUATE_PROMPT 包含 analysis 和 summary
        prompt = node.EVALUATE_PROMPT
        assert "<analysis>" in prompt, f"prompt 应包含 <analysis> 分析块: {prompt}"
        assert "<summary>" in prompt, f"prompt 应包含 <summary> 输出块: {prompt}"

    @pytest.mark.asyncio
    async def test_parse_summary_json(self):
        """ReflectNode 应从 <summary> 中解析 JSON，而不是 raw 文本"""
        llm_reply = (
            "<analysis>\n"
            "回复语气符合角色设定，内容相关，无明显问题。\n"
            "角色一致性：✅ 良好\n"
            "内容相关性：✅ 相关\n"
            "</analysis>\n"
            "<summary>\n"
            '{"level": 0, "feedback": "完美"}\n'
            "</summary>"
        )
        node = ReflectNode(llm=MockLLM(reply=llm_reply))
        ctx = RunContext(user_input="hi")
        ctx.final_text = "本小姐很好"
        result = await node.run(ctx, AsyncMock())
        assert result.next_node is None, "level 0 应结束"

    @pytest.mark.asyncio
    async def test_parse_summary_react_level(self):
        """<summary> level 3 应返回 react"""
        llm_reply = (
            "<analysis>语气不对</analysis>\n"
            "<summary>"
            '{"level": 3, "feedback": "语气太冷淡，需要更热情"}'
            "</summary>"
        )
        node = ReflectNode(llm=MockLLM(reply=llm_reply))
        ctx = RunContext(user_input="hi")
        ctx.final_text = "哦"
        result = await node.run(ctx, AsyncMock())
        assert result.next_node == "react"
        assert "语气" in ctx.feedback

    @pytest.mark.asyncio
    async def test_fallback_parsing_without_analysis(self):
        """如果 LLM 没输出 <analysis>，应能从纯 <summary> 或 JSON 中提取"""
        llm_reply = (
            "<summary>"
            '{"level": 0, "feedback": "无分析直接评估"}'
            "</summary>"
        )
        node = ReflectNode(llm=MockLLM(reply=llm_reply))
        ctx = RunContext(user_input="hi")
        ctx.final_text = "好"
        result = await node.run(ctx, AsyncMock())
        assert result.next_node is None, "无 analysis 也应正常工作"

    @pytest.mark.asyncio
    async def test_single_llm_call(self):
        """scratchpad 模式仍然只调用一次 LLM"""
        mock = MockLLM(reply="<summary>{\"level\": 0, \"feedback\": \"\"}</summary>")
        node = ReflectNode(llm=mock)
        ctx = RunContext(user_input="hi")
        ctx.final_text = "好"
        await node.run(ctx, AsyncMock())
        assert mock.call_count == 1, f"应只调用1次LLM, 实际{ mock.call_count}"

    @pytest.mark.asyncio
    async def test_empty_text_skips_eval(self):
        """空 text 应跳过评估"""
        node = ReflectNode(llm=MockLLM(reply=""))
        ctx = RunContext(user_input="")
        ctx.final_text = ""
        result = await node.run(ctx, AsyncMock())
        assert result.next_node is None
