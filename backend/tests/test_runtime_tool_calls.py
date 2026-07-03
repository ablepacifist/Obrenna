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
    async def test_web_search_missing_query_repaired_from_user_message(self):
        """A web_search call missing `query` is backfilled from the user message."""
        captured: dict = {}

        def handler(p):
            captured["args"] = p["arguments"]
            return {"results": [], "query": p["arguments"].get("query"), "count": 0}

        transport = InMemoryTransport()
        transport.register_handler("tools/call", handler)
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [{
            "id": "call_ws",
            "type": "function",
            "function": {"name": "web_search", "arguments": {}},
        }]
        results = await handle_tool_calls(
            tool_calls, client, user_message="best pizza in winnipeg",
        )
        # Repaired query reached the MCP; no error result.
        assert captured["args"]["query"] == "best pizza in winnipeg"
        assert "error" not in results[0]["content"] or '"error": true' not in results[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_web_search_blank_query_treated_as_missing(self):
        """A whitespace-only query is treated as missing and repaired."""
        captured: dict = {}
        transport = InMemoryTransport()
        transport.register_handler(
            "tools/call", lambda p: captured.update(args=p["arguments"]) or {"results": []},
        )
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [{
            "id": "call_ws",
            "type": "function",
            "function": {"name": "web_search", "arguments": {"query": "   "}},
        }]
        await handle_tool_calls(tool_calls, client, user_message="tacos near me")
        assert captured["args"]["query"] == "tacos near me"

    @pytest.mark.asyncio
    async def test_web_search_unrepairable_short_circuits(self):
        """No user text to backfill from → structured error, MCP never called."""
        called = {"n": 0}

        def handler(p):
            called["n"] += 1
            return {"results": []}

        transport = InMemoryTransport()
        transport.register_handler("tools/call", handler)
        client = MCPClient(transport)
        await client.initialize()

        tool_calls = [{
            "id": "call_ws",
            "type": "function",
            "function": {"name": "web_search", "arguments": {}},
        }]
        results = await handle_tool_calls(tool_calls, client, user_message="")
        assert called["n"] == 0  # dispatch short-circuited
        payload = json.loads(results[0]["content"])
        assert payload["error"] is True
        assert payload["retryable"] is True
        assert "query" in payload["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_required_arg_no_repair_short_circuits(self):
        """A tool with no repair strategy short-circuits on a missing required arg."""
        called = {"n": 0}
        transport = InMemoryTransport()
        transport.register_handler(
            "tools/call", lambda p: called.update(n=called["n"] + 1) or {"result": 0},
        )
        client = MCPClient(transport)
        await client.initialize()

        # calculator requires `expression`; no repair registered for it.
        tool_calls = [{
            "id": "call_calc",
            "type": "function",
            "function": {"name": "calculator", "arguments": {}},
        }]
        results = await handle_tool_calls(tool_calls, client, user_message="2+2")
        assert called["n"] == 0
        payload = json.loads(results[0]["content"])
        assert payload["error"] is True
        assert "expression" in payload["message"].lower()

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


class TestParallelToolDispatch:
    """Fix #4 — independent read-only tool calls run concurrently via gather;
    stateful/sensitive/dependent tools run serially; results stay in order."""

    @pytest.mark.asyncio
    async def test_two_read_only_tools_run_concurrently(self):
        client = _ConcurrencyTrackingClient(delay=0.02)
        tool_calls = [
            {"id": "c1", "type": "function",
             "function": {"name": "get_time", "arguments": {}}},
            {"id": "c2", "type": "function",
             "function": {"name": "calculator", "arguments": {"expression": "1+1"}}},
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 2
        # Both ran, in original order.
        assert results[0]["tool_call_id"] == "c1"
        assert results[1]["tool_call_id"] == "c2"
        # Concurrency: two read-only tools overlapped (max_active >= 2).
        assert client.max_active >= 2, (
            "two gather-eligible tools should run concurrently, "
            f"max_active was {client.max_active}"
        )

    @pytest.mark.asyncio
    async def test_get_location_stays_serial_with_calculator(self):
        client = _ConcurrencyTrackingClient(delay=0.02)
        tool_calls = [
            {"id": "c1", "type": "function",
             "function": {"name": "calculator", "arguments": {"expression": "2+2"}}},
            {"id": "c2", "type": "function",
             "function": {"name": "get_location", "arguments": {}}},
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 2
        # Order preserved even though get_location is serial after the parallel batch.
        assert results[0]["tool_call_id"] == "c1"
        assert results[1]["tool_call_id"] == "c2"
        # get_location is never gathered — nothing overlapped.
        assert client.max_active == 1, (
            "get_location must run serially; max_active was "
            f"{client.max_active}"
        )

    @pytest.mark.asyncio
    async def test_unknown_tool_runs_serially(self):
        client = _ConcurrencyTrackingClient(delay=0.01)
        tool_calls = [
            {"id": "c1", "type": "function",
             "function": {"name": "get_time", "arguments": {}}},
            {"id": "c2", "type": "function",
             "function": {"name": "nonexistent_tool", "arguments": {}}},
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert len(results) == 2
        assert [r["tool_call_id"] for r in results] == ["c1", "c2"]
        # Unknown tool fails closed — not gather-eligible → no overlap.
        assert client.max_active == 1

    @pytest.mark.asyncio
    async def test_results_preserve_order_regardless_of_completion(self):
        # The first call sleeps much longer than the second; a gather would
        # complete the second first. Results must still come back in input order.
        client = _ConcurrencyTrackingClient(delay_map={"get_time": 0.05,
                                                       "calculator": 0.001})
        tool_calls = [
            {"id": "c1", "type": "function",
             "function": {"name": "get_time", "arguments": {}}},
            {"id": "c2", "type": "function",
             "function": {"name": "calculator", "arguments": {"expression": "3+3"}}},
        ]
        results = await handle_tool_calls(tool_calls, client)
        assert [r["tool_call_id"] for r in results] == ["c1", "c2"]
        assert results[0]["tool_name"] == "get_time"
        assert results[1]["tool_name"] == "calculator"


class _ConcurrencyTrackingClient:
    """Fake MCP client that records concurrent call counts and per-name delays.

    Used to assert that gather-eligible tools actually overlap in wall-clock
    time (max_active >= 2) while serial tools never do.
    """

    def __init__(self, delay: float = 0.0, delay_map: dict | None = None):
        self.delay = delay
        self.delay_map = delay_map or {}
        self.active = 0
        self.max_active = 0

    async def call_tool(self, name: str, args: dict) -> str:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay_map.get(name, self.delay))
            return f"{name}:ok"
        finally:
            self.active -= 1


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

    @pytest.mark.asyncio
    async def test_tool_call_emits_helper_narration_between_call_and_result(self, monkeypatch):
        """A helper-model narration `tool_progress` event (stage="narrating",
        carrying call_id) is emitted between `tool_call` and `tool_result` so
        the card headline describes what the tool is doing while still running."""
        from app.agent import runtime as rt
        import app.mcp.tools as mcp_tools

        rounds = iter([
            [{"type": "tool_calls_done", "calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "calculator", "arguments": {"expression": "6*7"}}}]}],
            [{"type": "token", "content": "The answer is 42."}],
        ])

        async def fake_stream(config, messages, **kwargs):
            for ev in next(rounds):
                yield ev

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        class _StubMemory:
            def to_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        async def fake_acall(name, args):
            return {"result": 42.0, "expression": "6*7"}

        monkeypatch.setattr(mcp_tools, "acall_tool", fake_acall)

        # Deterministic narration — no real model round-trip.
        async def fake_gather_narrations(config, calls):
            return ["Crunching the calculation 6 * 7"]

        monkeypatch.setattr(rt, "gather_narrations", fake_gather_narrations)

        config = RuntimeConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:27b"},
        )
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:27b", "tool_call_mode": "openai_native"},
        })

        events = [e async for e in orchestrate_turn(
            "what is 6*7", "chat-narr", db=None, config=config, resolved_plan=plan,
            workers_enabled=False,
        )]

        types = [e.type for e in events]
        call_idx = types.index("tool_call")
        result_idx = types.index("tool_result")
        assert call_idx < result_idx

        narrating = [
            e for e in events
            if e.type == "tool_progress"
            and e.payload.get("stage") == "narrating"
            and e.payload.get("call_id") == "call_1"
        ]
        assert narrating, "expected a narrating tool_progress event with call_id='call_1'"
        assert "Crunching" in narrating[0].payload.get("summary", "")

        # The narration lands between tool_call and tool_result.
        narr_idx = types.index(narrating[0].type)  # first tool_progress narrating
        # Find the index of THIS narrating event precisely (there may be other
        # tool_progress events; match by call_id payload).
        narr_pos = next(i for i, e in enumerate(events) if e is narrating[0])
        assert call_idx < narr_pos < result_idx

    @pytest.mark.asyncio
    async def test_native_continuation_round_keeps_tools_available(self, monkeypatch):
        """Step 5 guard: a native orchestrator must be offered tools on a
        continuation round so it can CHAIN — say something, call a tool, reason,
        call another tool. Previously ``model_tools`` was nulled after the first
        tool round, capping native models at one tool call per turn. With
        compaction + tier-aware caps + cheap continuation rounds in place, the
        disarm is gone; this test proves the model gets a second tool call and
        that finalization (not continuation) is what drops tools.
        """
        from app.agent import runtime as rt

        class StubMemory:
            def to_static_messages(self):
                return []

            def to_dynamic_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: StubMemory())
        monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})

        rounds = iter([
            [{"type": "tool_calls_done", "calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "calculator", "arguments": {"expression": "1+1"}}}]}],
            [{"type": "tool_calls_done", "calls": [
                {"id": "call_2", "type": "function",
                 "function": {"name": "calculator", "arguments": {"expression": "2+2"}}}]}],
            [{"type": "token", "content": "chained answer"}],
        ])
        captured = []

        async def fake_stream(config, messages, **kwargs):
            captured.append(kwargs)
            for ev in next(rounds):
                yield ev

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        async def fake_handle_tool_calls(tool_calls, mcp_client):
            return [{"tool_call_id": tc["id"], "tool_name": "calculator", "content": "2"}
                    for tc in tool_calls]

        monkeypatch.setattr(rt, "handle_tool_calls", fake_handle_tool_calls)

        config = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1", models={})
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:27b", "tool_call_mode": "openai_native", "max_tool_rounds": 2},
        })

        events = [e async for e in orchestrate_turn(
            "add then add again", "chat-chain", None, config, plan, workers_enabled=False)]

        # Three model passes: round 1 tool, round 2 tool (the chain), round 3 finalization.
        assert len(captured) == 3, f"expected 3 model passes, got {len(captured)}"
        # Round 1: tools offered (native sends OpenAI tool definitions).
        assert captured[0].get("tools") is not None
        # Round 2 — the continuation/chaining round — must STILL be offered tools.
        # This is the core Step 5 assertion; it was None before the fix.
        assert captured[1].get("tools") is not None, (
            "continuation round must keep tools available so a native model can chain"
        )
        # Round 3 — finalization (round 2's tool call hit max_tool_rounds=2) — drops tools.
        assert captured[2].get("tools") is None, (
            "finalization round must drop tools so the model writes the answer"
        )
        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert "chained answer" in tokens


class TestRuntimeContextInjection:
    """Runtime clock grounding should be injected per turn and remain dynamic."""

    def test_injects_compact_runtime_context_for_prompt_json(self):
        messages = _build_orchestrator_messages(
            user_message="what year is it",
            static_parts=[],
            dynamic_parts=[],
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
            static_parts=[],
            dynamic_parts=[],
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
            static_parts=[],
            dynamic_parts=[],
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
            static_parts=[],
            dynamic_parts=[],
            evidence_summary="",
            previous_messages=[],
            tool_call_mode="openai_native",
            allowed_tools=None,
        )
        assert not any(m.get("name") == "runtime_relative_dates" for m in messages)


class TestRuntimeDbTransactionBoundaries:
    @pytest.mark.asyncio
    async def test_context_read_transaction_closes_before_model_stream(self, monkeypatch):
        from app.agent import runtime as rt

        class TrackingDb:
            def __init__(self):
                self.rollback_count = 0

            def rollback(self):
                self.rollback_count += 1

        class StubMemory:
            def to_static_messages(self):
                return []

            def to_dynamic_messages(self):
                return []

        tracking_db = TrackingDb()

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: StubMemory())

        async def fake_stream(*args, **kwargs):
            assert tracking_db.rollback_count >= 1
            yield {"type": "token", "content": "final answer"}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        config = RuntimeConfig(
            provider="openai_compatible",
            base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:4b"},
        )
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:4b", "tool_call_mode": "prompt_json"},
        })

        events = [e async for e in orchestrate_turn(
            "hello", "chat-db-boundary", tracking_db, config, plan,
            workers_enabled=False,
        )]

        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert tokens == "final answer"


class TestToolLoopFinalization:
    @pytest.mark.asyncio
    async def test_max_tool_rounds_gets_forced_final_answer_pass(self, monkeypatch):
        from app.agent import runtime as rt

        class StubMemory:
            def to_static_messages(self):
                return []

            def to_dynamic_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: StubMemory())
        monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})

        calls = {"model": 0}

        async def fake_stream(*args, **kwargs):
            calls["model"] += 1
            if calls["model"] == 1:
                yield {
                    "type": "tool_calls_done",
                    "calls": [{
                        "id": "call_search",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": {"query": "Winnipeg this week"}},
                    }],
                }
            else:
                messages = args[1]
                assert any("Tool limit reached" in (m.get("content") or "") for m in messages)
                yield {"type": "token", "content": "Final Winnipeg summary."}

        async def fake_handle_tool_calls(tool_calls, mcp_client):
            return [{
                "tool_call_id": "call_search",
                "tool_name": "web_search",
                "content": json.dumps({"results": [{"title": "Winnipeg news", "snippet": "A local update."}]}),
            }]

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
        monkeypatch.setattr(rt, "handle_tool_calls", fake_handle_tool_calls)

        config = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1", models={})
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:4b", "tool_call_mode": "prompt_json", "max_tool_rounds": 1},
        })

        events = [e async for e in orchestrate_turn(
            "Summarize what happened in Winnipeg this week",
            "chat-tool-final",
            None,
            config,
            plan,
            web_search=True,
            workers_enabled=False,
        )]

        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert tokens == "Final Winnipeg summary."
        assert calls["model"] == 2

    @pytest.mark.asyncio
    async def test_finalization_tool_call_uses_non_empty_tool_result_fallback(self, monkeypatch):
        from app.agent import runtime as rt

        class StubMemory:
            def to_static_messages(self):
                return []

            def to_dynamic_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: StubMemory())
        monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})

        async def fake_stream(*args, **kwargs):
            yield {
                "type": "tool_calls_done",
                "calls": [{
                    "id": "call_search",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": {"query": "Winnipeg this week"}},
                }],
            }

        handle_calls = {"count": 0}

        async def fake_handle_tool_calls(tool_calls, mcp_client):
            handle_calls["count"] += 1
            return [{
                "tool_call_id": "call_search",
                "tool_name": "web_search",
                "content": json.dumps({"results": [{
                    "title": "Winnipeg headline",
                    "snippet": "A major local story happened.",
                    "url": "https://example.test/winnipeg",
                }]}),
            }]

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
        monkeypatch.setattr(rt, "handle_tool_calls", fake_handle_tool_calls)

        config = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1", models={})
        plan = ResolvedPlan({
            "orchestrator": {"model": "qwen3.5:4b", "tool_call_mode": "prompt_json", "max_tool_rounds": 1},
        })

        events = [e async for e in orchestrate_turn(
            "Summarize what happened in Winnipeg this week",
            "chat-tool-fallback",
            None,
            config,
            plan,
            web_search=True,
            workers_enabled=False,
        )]

        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert "Winnipeg headline" in tokens
        assert "A major local story happened" in tokens
        assert handle_calls["count"] == 1
