"""Verification tests for the multi-step tool-calling improvement plan.

Covers the three behaviors that were missing dedicated coverage after
Steps 2-6: structural tool-result compaction (preserve the sufficiency shape,
not head-truncate), per-round ``reasoning_effort`` gating keyed on
``reasoning_distilled``, and the per-orchestrator catalog capability lookups
(``reasoning_distilled`` / ``max_tool_rounds`` / ``tool_result_budget``).

The native-chaining guard (Step 5) and the prompt-JSON plural envelope
(Step 6) live in ``test_runtime_tool_calls.py`` and ``test_streaming.py``.
"""
import json

from app.agent.runtime import (
    _compact_tool_results,
    _round_reasoning_effort,
)
from app.services.hardware_catalog import (
    load_catalog,
    max_tool_rounds_for,
    reasoning_distilled_for,
    tool_result_budget_for,
)


# ── Step 2: structural compaction ────────────────────────────────────────────

def test_compact_web_search_preserves_all_titles_urls_and_caps_snippets():
    """web_search trim keeps every result's title+url (the sufficiency shape)
    and budgets each snippet body — NOT a head-truncation that drops entry #4."""
    n = 6
    content = json.dumps({"results": [
        {"title": f"T{i}", "url": f"http://x/{i}", "snippet": "s" * 500}
        for i in range(n)
    ]})
    tool_results = [{"tool_call_id": "c1", "tool_name": "web_search", "content": content}]
    calls = [{"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": {}}}]

    raw, comp = _compact_tool_results(tool_results, calls, per_result_budget=600)

    parsed = json.loads(tool_results[0]["content"])
    # All N entries survive, with their title+url intact and ordered.
    assert len(parsed["results"]) == n
    for i, r in enumerate(parsed["results"]):
        assert r["title"] == f"T{i}"
        assert r["url"] == f"http://x/{i}"
        # per_snippet = max(120, 600 // 6) = 120; ellipsis adds one char.
        assert len(r["snippet"]) <= 121
    # Compaction actually reduced the size.
    assert comp < raw


def test_compact_passthrough_tools_unchanged():
    """calculator/get_time/get_location return tens of tokens — folding them is
    pure overhead, so they pass through byte-for-byte regardless of budget."""
    for tool in ("calculator", "get_time", "get_location"):
        content = "42"
        tool_results = [{"tool_call_id": "c", "tool_name": tool, "content": content}]
        calls = [{"id": "c", "type": "function", "function": {"name": tool, "arguments": {}}}]
        raw, comp = _compact_tool_results(tool_results, calls, per_result_budget=10)
        assert tool_results[0]["content"] == content
        assert raw == comp  # nothing trimmed


def test_compact_file_read_keeps_head_and_tail():
    """file_read trims the middle, preserving head+tail so file structure
    (imports/exports) stays visible."""
    content = "L" * 2000
    tool_results = [{"tool_call_id": "c", "tool_name": "file_read", "content": content}]
    calls = [{"id": "c", "type": "function", "function": {"name": "file_read", "arguments": {}}}]
    raw, comp = _compact_tool_results(tool_results, calls, per_result_budget=400)
    out = tool_results[0]["content"]
    assert comp < raw
    assert out.startswith("L")
    assert out.endswith("L")
    assert "[middle truncated]" in out


def test_compact_mutates_in_place_and_returns_char_counts():
    """The chokepoint mutates result['content'] in place (both feed-back branches
    read it from the same dict) and reports raw/compacted chars for tracing."""
    tool_results = [{"tool_call_id": "c", "tool_name": "web_search",
                      "content": json.dumps({"results": [{"title": "t", "url": "u", "snippet": "x" * 800}]})}]
    calls = [{"id": "c", "type": "function", "function": {"name": "web_search", "arguments": {}}}]
    raw, comp = _compact_tool_results(tool_results, calls, per_result_budget=200)
    assert raw > comp > 0
    # The dict was mutated in place — re-reading gives the compacted content.
    assert json.loads(tool_results[0]["content"])["results"][0]["title"] == "t"


# ── Step 4: per-round reasoning_effort gating ────────────────────────────────

def test_round_reasoning_effort_stock_model():
    f = _round_reasoning_effort
    # Stock: round 1 full, continuation dark (mechanical sufficiency check),
    # finalization dark for everyone.
    assert f(True, 1, False, False) == "medium"
    assert f(True, 2, False, False) == "none"
    assert f(True, 3, False, False) == "none"
    assert f(True, 5, True, False) == "none"   # finalization


def test_round_reasoning_effort_distilled_model():
    f = _round_reasoning_effort
    # Distilled: round 1 full (need CoT to form the envelope), continuation
    # downshifts to low (keeps envelope formation alive), finalization dark.
    assert f(True, 1, False, True) == "medium"
    assert f(True, 2, False, True) == "low"
    assert f(True, 3, False, True) == "low"
    assert f(True, 5, True, True) == "none"     # finalization for everyone


def test_round_reasoning_effort_thinking_disabled_is_all_none():
    f = _round_reasoning_effort
    # The turn-level opt-out is preserved: thinking off -> every round none,
    # for both stock and distilled, continuation and finalization.
    for rd in (False, True):
        assert f(False, 1, False, rd) == "none"
        assert f(False, 3, False, rd) == "none"
        assert f(False, 2, True, rd) == "none"


def test_round_reasoning_effort_keyed_on_distilled_not_round_only():
    """The discriminator is distilled-vs-stock, not the round number alone: a
    continuation round is 'none' for stock but 'low' for distilled."""
    assert _round_reasoning_effort(True, 2, False, False) == "none"
    assert _round_reasoning_effort(True, 2, False, True) == "low"


# ── Steps 3 & 4: per-orchestrator catalog capabilities ───────────────────────

def test_catalog_per_orchestrator_capabilities_match_plan():
    """The five orchestrator model_definitions carry the resolved capabilities
    the runtime now sources (instead of the dead global max_tool_rounds)."""
    cat = load_catalog()
    expected = {
        "qwen3.5-0.8b-claude-opus-reasoning-distilled": (True, 2, 3000),
        "qwen3.5-4b-claude-opus-reasoning-distilled-v2": (True, 3, 4000),
        "qwen3.5-9b-claude-opus-reasoning-distilled": (True, 4, 6000),
        "qwen3.5-27b": (False, 5, 10000),
        "qwen3.6-35b-a3b": (False, 5, 12000),
    }
    for slug, (rd, mtr, trb) in expected.items():
        assert reasoning_distilled_for(cat, slug) is rd, slug
        assert max_tool_rounds_for(cat, slug) == mtr, slug
        assert tool_result_budget_for(cat, slug) == trb, slug


def test_catalog_distilled_floor_has_tighter_round_budget_than_stock_ceiling():
    """The EXP0 distilled floor is capped more tightly than the big stock tier —
    the inverse of the old flat-global-5 that blew context on the floor."""
    cat = load_catalog()
    floor = max_tool_rounds_for(cat, "qwen3.5-0.8b-claude-opus-reasoning-distilled")
    ceiling = max_tool_rounds_for(cat, "qwen3.5-27b")
    assert floor < ceiling
    # Distilled models are all flagged true; stock ones false.
    assert reasoning_distilled_for(cat, "qwen3.5-4b-claude-opus-reasoning-distilled-v2") is True
    assert reasoning_distilled_for(cat, "qwen3.6-35b-a3b") is False


def test_catalog_lookups_default_safely_for_unknown_model():
    """An unknown slug falls back to safe defaults, so a missing entry never
    breaks the loop."""
    cat = load_catalog()
    slug = "definitely-not-a-real-model-slug"
    assert reasoning_distilled_for(cat, slug) is False
    assert max_tool_rounds_for(cat, slug) == 3
    assert tool_result_budget_for(cat, slug) == 4000