"""Tests for the orchestrator prompt band layout (Fix #1).

Verifies the static identity/role prompt (Band A) and the prompt-JSON tool
contract (Band A′) lead the message sequence, are byte-stable across turns
with different memory, and contain no per-turn dynamic content — so Ollama's
prefix/KV cache reuses them on turns 2+.
"""
from __future__ import annotations

from app.agent.runtime import _build_orchestrator_messages, WEB_SEARCH_HINT
from app.services.memory import (
    ORCHESTRATOR_STATIC_SYSTEM_PROMPT,
    MemoryContext,
    canonicalise_system_content,
)

_PERSONA = canonicalise_system_content(ORCHESTRATOR_STATIC_SYSTEM_PROMPT)
_ALLOWED_TOOLS = [{"name": "get_time", "description": "Get the current time", "inputSchema": {}}]


def _msgs(dynamic_parts, *, tool_call_mode="openai_native", allowed_tools=None, web_search_enabled=False):
    return _build_orchestrator_messages(
        user_message="Hello",
        static_parts=MemoryContext().to_static_messages(),
        dynamic_parts=dynamic_parts,
        evidence_summary="",
        previous_messages=[],
        tool_call_mode=tool_call_mode,
        allowed_tools=allowed_tools,
        web_search_enabled=web_search_enabled,
    )


class TestBandALeadsAndIsStatic:
    def test_band_a_is_first_message_and_matches_persona(self):
        msgs = _msgs([])
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == _PERSONA

    def test_band_a_has_no_dynamic_memory_content(self):
        # Even when dynamic memory is present, Band A itself stays clean.
        dynamic = MemoryContext(facts=[{"id": "f1", "text": "User prefers Python"}]).to_dynamic_messages()
        msgs = _msgs(dynamic)
        assert msgs[0]["content"] == _PERSONA
        assert "User prefers Python" not in msgs[0]["content"]
        assert "stored memories" not in msgs[0]["content"].lower()


class TestBandAPrimeToolContract:
    def test_tool_contract_precedes_dynamic_memory(self):
        dynamic = MemoryContext(facts=[{"id": "f1", "text": "User prefers Python"}]).to_dynamic_messages()
        msgs = _msgs(dynamic, tool_call_mode="prompt_json", allowed_tools=_ALLOWED_TOOLS)
        # Band A (persona), Band A′ (tool contract), Band B (dynamic memory).
        assert msgs[0]["content"] == _PERSONA
        assert "Available tools:" in msgs[1]["content"], "Band A′ must be the tool contract"
        assert "User prefers Python" in msgs[2]["content"], "Band B must follow the contract"
        assert "User prefers Python" not in msgs[1]["content"], (
            "the tool contract must not include per-turn memory"
        )

    def test_no_tool_contract_for_native_mode(self):
        # openai_native learns tools via the API ``tools`` field — no Band A′.
        msgs = _msgs([], tool_call_mode="openai_native", allowed_tools=_ALLOWED_TOOLS)
        assert msgs[0]["content"] == _PERSONA
        assert not any("Available tools:" in m.get("content", "") for m in msgs)


class TestBandADoublePrimeWebSearchHint:
    def test_hint_present_when_web_enabled_native_mode(self):
        # Native mode has no Band A′, so the hint is the second system message.
        msgs = _msgs([], tool_call_mode="openai_native", web_search_enabled=True)
        assert msgs[0]["content"] == _PERSONA
        assert msgs[1]["content"] == canonicalise_system_content(WEB_SEARCH_HINT)

    def test_hint_present_when_web_enabled_prompt_json_mode(self):
        # In prompt-json mode the hint follows the tool contract (Band A′).
        msgs = _msgs(
            [],
            tool_call_mode="prompt_json",
            allowed_tools=_ALLOWED_TOOLS,
            web_search_enabled=True,
        )
        assert msgs[0]["content"] == _PERSONA
        assert "Available tools:" in msgs[1]["content"]
        assert msgs[2]["content"] == canonicalise_system_content(WEB_SEARCH_HINT)

    def test_hint_absent_when_web_disabled(self):
        msgs = _msgs([], tool_call_mode="openai_native", web_search_enabled=False)
        assert not any(m.get("content") == canonicalise_system_content(WEB_SEARCH_HINT) for m in msgs)

    def test_hint_is_byte_stable_across_different_memory(self):
        # The toggle is stable within a chat, so the hint must be prefix-cacheable.
        d1 = MemoryContext(facts=[{"id": "f1", "text": "User prefers Python"}]).to_dynamic_messages()
        d2 = MemoryContext(facts=[{"id": "f2", "text": "User lives in Seattle"}]).to_dynamic_messages()
        m1 = _msgs(d1, tool_call_mode="prompt_json", allowed_tools=_ALLOWED_TOOLS, web_search_enabled=True)
        m2 = _msgs(d2, tool_call_mode="prompt_json", allowed_tools=_ALLOWED_TOOLS, web_search_enabled=True)
        # Bands A, A′, A″ all byte-identical; Band B differs.
        assert m1[0]["content"] == m2[0]["content"]
        assert m1[1]["content"] == m2[1]["content"]
        assert m1[2]["content"] == m2[2]["content"]
        assert m1[3]["content"] != m2[3]["content"]


class TestByteStablePrefix:
    def test_band_a_byte_identical_across_different_memory(self):
        d1 = MemoryContext(facts=[{"id": "f1", "text": "User prefers Python"}]).to_dynamic_messages()
        d2 = MemoryContext(facts=[{"id": "f2", "text": "User lives in Seattle"}]).to_dynamic_messages()
        msgs1 = _msgs(d1, tool_call_mode="prompt_json", allowed_tools=_ALLOWED_TOOLS)
        msgs2 = _msgs(d2, tool_call_mode="prompt_json", allowed_tools=_ALLOWED_TOOLS)
        # Band A identical...
        assert msgs1[0]["content"] == msgs2[0]["content"]
        # ...and Band A′ (tool contract) identical with the same tool set.
        assert msgs1[1]["content"] == msgs2[1]["content"]
        # ...while Band B differs.
        assert msgs1[2]["content"] != msgs2[2]["content"]


class TestDynamicBandStamp:
    def test_dynamic_band_carries_version_stamp(self):
        ctx = MemoryContext(
            facts=[{"id": "f1", "text": "User prefers Python"}],
            account_version=5,
            chat_version=3,
        )
        dynamic = ctx.to_dynamic_messages()
        assert len(dynamic) == 1
        assert dynamic[0]["content"].startswith("[mem v=5 cv=3]")

    def test_empty_context_has_no_dynamic_band(self):
        assert MemoryContext().to_dynamic_messages() == []