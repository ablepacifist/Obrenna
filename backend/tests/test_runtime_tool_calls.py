"""Tests for tool invocation loop in agent runtime."""
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.runtime import (
    ResolvedPlan,
    classify_intent_fast,
    orchestrate_turn,
    handle_tool_calls,
    is_exp0_plan,
    route_requires_workers,
    _build_orchestrator_messages,
    _format_tools_for_model,
    _get_allowed_tools_for_request,
    allowed_mcp_tools_config,
)
from app.mcp.client import MCPClient, InMemoryTransport
from app.model_runtime.config import RuntimeConfig


class TestToolCallHandling:
    """Test handle_tool_calls integration."""

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"result": 42})
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [
            {
                "id": "call_001",
                "type": "function",
                "function": {
                    "name": "calculator",
                    "arguments": {"expression": "6*7"},
                },
            }
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 1
        assert results[0]["tool_call_id"] == "call_001"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"output": f"result for {p['name']}"})
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [
            {
                "id": "call_001",
                "type": "function",
                "function": {"name": "get_time", "arguments": {}},
            },
            {
                "id": "call_002",
                "type": "function",
                "function": {"name": "calculator", "arguments": {"expression": "1+1"}},
            },
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"content": [{"type": "text", "text": "Tool not found"}]})
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [
            {
                "id": "call_001",
                "type": "function",
                "function": {"name": "nonexistent_tool", "arguments": {}},
            }
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 1
        assert "not found" in results[0]["content"].lower()


class TestToolFormatting:
    """Test tool definition formatting for model API."""

    def test_format_tools_for_model(self):
        allowed_tools = [
            {
                "name": "calculator",
                "description": "Evaluate arithmetic",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "The expression"},
                    },
                    "required": ["expression"],
                },
            },
            {
                "name": "get_time",
                "description": "Get current time",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ]
        result = _format_tools_for_model(allowed_tools)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "calculator"
        assert result[0]["function"]["parameters"]["type"] == "object"
        assert "expression" in result[0]["function"]["parameters"]["properties"]
        assert result[0]["function"]["parameters"]["required"] == ["expression"]

    def test_format_tools_empty(self):
        result = _format_tools_for_model([])
        assert result == []

    def test_format_tools_unknown_name_raises(self):
        # A tool allowed in config but absent from TOOL_DEFS is a config error:
        # the runtime must raise loudly rather than ship empty parameters the
        # model could never call correctly.
        allowed = [{"name": "test", "description": "Test tool"}]
        with pytest.raises(ValueError, match="TOOL_DEFS"):
            _format_tools_for_model(allowed)


class TestToolFiltering:
    """Test tool filtering based on request settings."""

    def test_all_tools_when_web_search_disabled(self):
        allowed = [
            {"name": "calculator", "category": "utility"},
            {"name": "web_search", "category": "web"},
            {"name": "get_time", "category": "utility"},
        ]
        result = _get_allowed_tools_for_request(allowed, web_search_enabled=False)
        names = [t["name"] for t in result]
        assert "calculator" in names
        assert "web_search" not in names
        assert "get_time" in names

    def test_all_tools_when_web_search_enabled(self):
        allowed = [
            {"name": "calculator", "category": "utility"},
            {"name": "web_search", "category": "web"},
            {"name": "get_time", "category": "utility"},
        ]
        result = _get_allowed_tools_for_request(allowed, web_search_enabled=True)
        names = [t["name"] for t in result]
        assert "calculator" in names
        assert "web_search" in names
        assert "get_time" in names

    def test_empty_allowed(self):
        result = _get_allowed_tools_for_request([], web_search_enabled=True)
        assert result == []


class TestMCPClientInMemory:
    """Test MCPClient with InMemoryTransport."""

    @pytest.mark.asyncio
    async def test_initialize(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/list", lambda p: {"tools": []})
        client = MCPClient(transport)
        result = await client.initialize()
        assert result is True

    @pytest.mark.asyncio
    async def test_list_tools(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/list", lambda p: {"tools": [{"name": "test"}]})
        client = MCPClient(transport)
        await client.initialize()
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_call_tool(self):
        transport = InMemoryTransport()
        transport.register_handler("tools/call", lambda p: {"content": [{"type": "text", "text": "hello world"}]})
        client = MCPClient(transport)
        await client.initialize()
        result = await client.call_tool("test_tool", {})
        assert "hello" in result


class TestResolvedPlanToolCallMode:
    """ResolvedPlan must surface the orchestrator's tool_call_mode with a safe default."""

    def test_explicit_prompt_json(self):
        plan = ResolvedPlan({"orchestrator": {"model": "x", "tool_call_mode": "prompt_json"}})
        assert plan.orchestrator_tool_call_mode == "prompt_json"

    def test_explicit_openai_native(self):
        plan = ResolvedPlan({"orchestrator": {"model": "x", "tool_call_mode": "openai_native"}})
        assert plan.orchestrator_tool_call_mode == "openai_native"

    def test_defaults_to_native_when_absent(self):
        plan = ResolvedPlan({"orchestrator": {"model": "x"}})
        assert plan.orchestrator_tool_call_mode == "openai_native"

    def test_invalid_value_falls_back_to_native(self):
        plan = ResolvedPlan({"orchestrator": {"model": "x", "tool_call_mode": "bogus"}})
        assert plan.orchestrator_tool_call_mode == "openai_native"


class TestExp0FastPath:
    """EXP0 should stay on deterministic/lightweight paths unless work needs helpers."""

    def test_detects_exp0_by_plan_id(self):
        assert is_exp0_plan({"plan_id": "EXP0-minimal", "orchestrator": {"model": "x"}})

    def test_detects_exp0_by_model_size(self):
        assert is_exp0_plan({"orchestrator": {"model": "qwen3.5-0.8b"}})

    def test_simple_chat_does_not_require_workers(self):
        intent = classify_intent_fast("hello there")
        assert intent == "chat"
        assert route_requires_workers(intent) is False

    def test_obvious_research_route_can_use_workers(self):
        intent = classify_intent_fast("research this with sources")
        assert intent == "web_research"
        assert route_requires_workers(intent) is True


class TestConfigAccess:
    """Test config access functions."""

    def test_allowed_mcp_tools_config(self):
        tools = allowed_mcp_tools_config()
        assert isinstance(tools, list)
        names = [t["name"] for t in tools]
        assert "calculator" in names
        assert "get_time" in names
        assert "web_search" in names

    def test_format_tools_includes_all_allowed(self):
        tools = _format_tools_for_model(allowed_mcp_tools_config())
        names = [t["function"]["name"] for t in tools]
        for name in ["calculator", "get_time", "web_search", "file_read", "get_location"]:
            assert name in names, f"Tool {name} should be in formatted tools"


class TestCanonicalSchemaMerge:
    """The model-facing tool list must be enriched from TOOL_DEFS (the canonical
    schema source), not the schema-stripped architecture_config allowlist.

    These tests exercise the REAL allowlist -> formatted-tools pipeline. Before the
    fix, architecture_config.json's allowed entries carried only name/description/
    category (no inputSchema), so every tool shipped with empty parameters and the
    model was never told web_search needs a `query`.
    """

    def test_real_pipeline_web_search_requires_query(self):
        tools = _format_tools_for_model(allowed_mcp_tools_config())
        ws = next(t for t in tools if t["function"]["name"] == "web_search")
        params = ws["function"]["parameters"]
        assert params["required"] == ["query"]
        assert "query" in params["properties"]
        assert params["properties"]["query"]["type"] == "string"

    def test_real_pipeline_calculator_requires_expression(self):
        tools = _format_tools_for_model(allowed_mcp_tools_config())
        calc = next(t for t in tools if t["function"]["name"] == "calculator")
        params = calc["function"]["parameters"]
        assert params["required"] == ["expression"]
        assert "expression" in params["properties"]

    def test_real_pipeline_no_arg_tools_kept_empty(self):
        # Tools that genuinely take no args (get_time, get_location) legitimately
        # have empty properties; everything else must carry a real schema.
        tools = _format_tools_for_model(allowed_mcp_tools_config())
        no_arg = {"get_time", "get_location"}
        for t in tools:
            name = t["function"]["name"]
            params = t["function"]["parameters"]
            if name in no_arg:
                assert params["properties"] == {}
            else:
                assert params["properties"], (
                    f"{name} shipped with empty parameters — schema merge is broken"
                )


class TestOrchestrateTurnPromptJson:
    """End-to-end exercise of the prompt-JSON tool-calling branch.

    ``orchestrate_turn`` is otherwise untested end-to-end. This drives it with a
    fake ``chat_completion_stream`` (round 1 yields a synthesized
    ``tool_calls_done`` — what the prompt-JSON scanner produces from the model's
    envelope; round 2 yields the final answer) and a stubbed memory context, then
    asserts the prompt-JSON contract: the tool contract is injected as a system
    message, NO OpenAI ``tools`` field is sent, the tool executes via the
    in-process MCP transport, the result is fed back as an assistant envelope +
    ``TOOL_RESULT(...)`` user message (NOT an OpenAI ``role:"tool"`` message), and
    a final answer streams.

    ``acall_tool`` is stubbed to return a REAL tool-handler shape — a plain
    result dict, exactly what ``mcp/tools.py`` handlers actually return (e.g.
    ``tool_get_time`` returns ``{"time": ..., ...}`` directly, not wrapped in
    ``{"content": {...}}``). The dev-mode transport in
    ``orchestrate_turn`` wraps that into the MCP ``{content:[{type,text}]}``
    envelope itself (see ``_dev_tools_call``), matching what the real stdio
    server does — so this test exercises the actual code path, not a shape
    invented to make the assertions pass.
    """

    @pytest.mark.asyncio
    async def test_prompt_json_tool_call_round_trip(self, monkeypatch):
        from app.agent import runtime as rt
        import app.mcp.tools as mcp_tools

        # Two rounds: tool call, then final answer.
        rounds = iter([
            [
                {"type": "token", "content": "Let me check the time. "},
                {"type": "tool_calls_done", "calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "get_time", "arguments": {}}}]},
            ],
            [
                {"type": "token", "content": "It is 12:00 UTC."},
            ],
        ])
        captured = []  # (messages, kwargs) per round

        async def fake_stream(config, messages, **kwargs):
            captured.append((messages, kwargs))
            for ev in next(rounds):
                yield ev

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        class _StubMemory:
            def to_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        # Real tool handlers return a plain result dict (see tool_get_time in
        # mcp/tools.py) — NOT pre-wrapped in an MCP content envelope. The
        # runtime's dev-mode transport (_dev_tools_call) is responsible for
        # wrapping it, matching the real stdio server's behavior.
        async def fake_acall(name, args):
            return {"iso_datetime": "2024-01-01T12:00:00", "human_readable": "It is 12:00 UTC"}

        monkeypatch.setattr(mcp_tools, "acall_tool", fake_acall)

        config = RuntimeConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:4b"},
        )
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:4b", "tool_call_mode": "prompt_json"},
        })

        events = [e async for e in orchestrate_turn(
            "what time is it", "chat1", db=None, config=config, resolved_plan=plan,
            workers_enabled=False, web_search=True,
        )]

        types = [e.type for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "done" in types

        # Final answer streamed; the tool-call envelope never leaked as text.
        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert "It is 12:00 UTC." in tokens
        assert "tool_call" not in tokens

        # The tool result event carries the executed content.
        result_events = [e for e in events if e.type == "tool_result"]
        assert result_events
        assert "It is 12:00 UTC" in result_events[0].payload.get("result", "")

        # Round 1: contract system message injected; no OpenAI tools field sent.
        round1_msgs, round1_kwargs = captured[0]
        contract = [m for m in round1_msgs
                    if m.get("role") == "system" and "tool_call" in m.get("content", "")]
        assert contract, "prompt-JSON tool contract should be injected as a system message"
        assert round1_kwargs.get("tool_call_mode") == "prompt_json"
        assert round1_kwargs.get("tools") is None  # prompt-json never sends OpenAI tools

        # Round 2: result fed back as prompt-JSON history, NOT OpenAI role:"tool".
        round2_msgs, _ = captured[1]
        # The assistant's tool call is recorded as the JSON envelope as text.
        envelope_msgs = [m for m in round2_msgs
                         if m.get("role") == "assistant" and m.get("content")]
        assert envelope_msgs, "assistant envelope message should be fed back"
        parsed = json.loads(envelope_msgs[-1]["content"])
        assert parsed == {"action": "tool_call", "tool": "get_time", "arguments": {}}
        assert any(m.get("role") == "user"
                   and "TOOL_RESULT(get_time)" in m.get("content", "")
                   for m in round2_msgs)
        assert not any(m.get("role") == "tool" for m in round2_msgs)


class TestOrchestrateTurnNativeToolCalling:
    """End-to-end exercise of the native (OpenAI tool_calls) tool-calling branch.

    This is the path CRIT-001 broke: ``handle_tool_calls`` was reading a
    dotted key ``"function.name"`` that never matched, so tool_name was always
    empty, and the result-feedback loop scanned for a nested-dict shape that
    never occurred, so tool results never made it back into the conversation.
    This test drives the real MCP call shape end-to-end and asserts the
    second model call actually receives the tool output.
    """

    @pytest.mark.asyncio
    async def test_native_tool_call_round_trip(self, monkeypatch):
        from app.agent import runtime as rt
        import app.mcp.tools as mcp_tools

        rounds = iter([
            [
                {"type": "tool_calls_done", "calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "calculator", "arguments": {"expression": "6*7"}}}]},
            ],
            [
                {"type": "token", "content": "The answer is 42."},
            ],
        ])
        captured = []

        async def fake_stream(config, messages, **kwargs):
            captured.append((messages, kwargs))
            for ev in next(rounds):
                yield ev

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        class _StubMemory:
            def to_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        # Real calculator handler shape: {"result": ..., "expression": ...}
        async def fake_acall(name, args):
            assert name == "calculator", f"tool name should resolve correctly, got {name!r}"
            return {"result": 42.0, "expression": "6*7"}

        monkeypatch.setattr(mcp_tools, "acall_tool", fake_acall)

        config = RuntimeConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:27b"},
        )
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:27b", "tool_call_mode": "openai_native"},
        })

        events = [e async for e in orchestrate_turn(
            "what is 6*7", "chat1", db=None, config=config, resolved_plan=plan,
            workers_enabled=False,
        )]

        types = [e.type for e in events]
        assert "tool_call" in types
        assert "tool_result" in types, "tool_result event must fire — this is what CRIT-001 broke"
        assert "done" in types

        result_events = [e for e in events if e.type == "tool_result"]
        assert result_events
        assert "42" in result_events[0].payload.get("result", "")

        # Round 2 messages must contain the tool's output, in the correct
        # OpenAI order: assistant(tool_calls) BEFORE the tool-role message.
        round2_msgs, _ = captured[1]
        tool_msgs = [m for m in round2_msgs if m.get("role") == "tool"]
        assert tool_msgs, "tool role message must be fed back — this is what CRIT-001 broke"
        assert "42" in tool_msgs[0].get("content", "")

        assistant_idx = next(
            i for i, m in enumerate(round2_msgs)
            if m.get("role") == "assistant" and m.get("tool_calls")
        )
        tool_idx = next(i for i, m in enumerate(round2_msgs) if m.get("role") == "tool")
        assert assistant_idx < tool_idx, (
            "assistant(tool_calls) message must precede tool-role messages per OpenAI contract"
        )

        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert "42" in tokens


class TestRuntimeContextInjection:
    """Runtime clock grounding should be injected per turn and remain dynamic."""

    def test_injects_compact_runtime_context_for_prompt_json(self):
        messages = _build_orchestrator_messages(
            user_message="what year is it",
            system_parts=[],
            evidence_summary="",
            previous_messages=[],
            tool_call_mode="prompt_json",
            allowed_tools=None,
        )
        runtime_context = next(
            m for m in messages
            if m.get("role") == "system" and m.get("name") == "runtime_context_clock"
        )
        assert "Today is" in runtime_context["content"]
        assert "Resolve relative dates using this date." in runtime_context["content"]
        assert str(datetime.now().year) in runtime_context["content"]

    def test_injects_full_runtime_context_for_openai_native(self):
        messages = _build_orchestrator_messages(
            user_message="what year is it",
            system_parts=[],
            evidence_summary="",
            previous_messages=[],
            tool_call_mode="openai_native",
            allowed_tools=None,
        )
        runtime_context = next(
            m for m in messages
            if m.get("role") == "system" and m.get("name") == "runtime_context_clock"
        )
        assert "Runtime context:" in runtime_context["content"]
        assert "Current local datetime is" in runtime_context["content"]
        assert "use get_time" in runtime_context["content"].lower()

    def test_injects_relative_date_hint_when_user_uses_relative_phrase(self):
        messages = _build_orchestrator_messages(
            user_message="show sales from last year",
            system_parts=[],
            evidence_summary="",
            previous_messages=[],
            tool_call_mode="openai_native",
            allowed_tools=None,
        )
        relative_hint = next(
            m for m in messages
            if m.get("role") == "system" and m.get("name") == "runtime_relative_dates"
        )
        assert "last_year" in relative_hint["content"]

    def test_does_not_inject_relative_date_hint_without_relative_phrase(self):
        messages = _build_orchestrator_messages(
            user_message="summarize the attached CSV",
            system_parts=[],
            evidence_summary="",
            previous_messages=[],
            tool_call_mode="openai_native",
            allowed_tools=None,
        )
        assert not any(m.get("name") == "runtime_relative_dates" for m in messages)
