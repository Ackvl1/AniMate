"""Tests for RunContext and RunServices。"""

import pytest
from dataclasses import fields
from anima.core.engine.context import RunContext, RunServices


class TestRunServices:
    def test_default_memory_is_none(self):
        svc = RunServices()
        assert svc.memory is None

    def test_can_set_memory(self):
        svc = RunServices(memory=object())
        assert svc.memory is not None

    def test_used_in_runcontext(self):
        ctx = RunContext(user_input="hi")
        assert isinstance(ctx.services, RunServices)
        assert ctx.services.memory is None

    def test_can_inject_memory_via_services(self):
        mem = object()
        ctx = RunContext(user_input="hi")
        ctx.services.memory = mem
        assert ctx.services.memory is mem


class TestRunContextNew:
    def test_init_defaults(self):
        ctx = RunContext(user_input="hello")
        assert ctx.user_input == "hello"
        assert ctx.messages == []
        assert ctx.llm_call_count == 0
        assert ctx.final_text == ""
        assert ctx.extras == {}

    def test_extras_dict(self):
        ctx = RunContext(user_input="hi")
        ctx.extras["rag_chunks"] = ["chunk1", "chunk2"]
        assert len(ctx.extras["rag_chunks"]) == 2

    def test_no_legacy_fields(self):
        ctx = RunContext(user_input="hi")
        assert not hasattr(ctx, "system_prompt_parts")
        assert not hasattr(ctx, "history")
