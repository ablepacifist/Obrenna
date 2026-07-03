"""Tests for the streaming model runtime: reasoning_effort payload + thinking parsing."""
import httpx
import pytest

from app.agent.runtime import (
    _format_tools_for_model,
    _get_allowed_tools_for_request,
    allowed_mcp_tools_config,
)
from app.model_runtime.config import RuntimeConfig
from app.model_runtime.streaming import chat_completion_stream


def _ollama_config() -> RuntimeConfig:
    return RuntimeConfig(
        provider="openai_compatible",
        base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3:8b"},
    )


def _non_ollama_config() -> RuntimeConfig:
    return RuntimeConfig(
        provider="openai_compatible",
        base_url="http://localhost:1234/v1",
        models={"orchestrator": "gpt-mini"},
    )


def _make_fake_client(lines, captured):
    """Build a fake httpx.AsyncClient that captures the JSON payload and feeds SSE lines."""

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        async def aiter_lines(self):
            for line in lines:
                yield line

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **kwargs):
            captured.update(kwargs.get("json", {}))

            class _CM:
                async def __aenter__(self):
                    return FakeResponse()

                async def __aexit__(self, *a):
                    return False

            return _CM()

    return FakeClient


def _sse(*chunks) -> list[str]:
    """Wrap JSON chunk dicts as SSE `data:` lines, ending with [DONE]."""
    import json
    return [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]


@pytest.mark.asyncio
async def test_ollama_thinking_enabled_sets_reasoning_effort_medium(monkeypatch):
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", think=True,
    )]

    assert captured["reasoning_effort"] == "medium"
    assert "think" not in captured
    assert "options" not in captured
    assert events[0] == {"type": "token", "content": "ok"}


@pytest.mark.asyncio
async def test_ollama_thinking_disabled_sets_reasoning_effort_none(monkeypatch):
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", think=False,
    ):
        pass

    assert captured["reasoning_effort"] == "none"
    assert "think" not in captured


@pytest.mark.asyncio
async def test_ollama_default_think_disabled_sets_none(monkeypatch):
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    ):
        pass

    # Default (no think kwarg) must still explicitly disable reasoning for Ollama.
    assert captured["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_non_ollama_does_not_send_reasoning_controls(monkeypatch):
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    async for _ in chat_completion_stream(
        _non_ollama_config(), [{"role": "user", "content": "hi"}],
        model="gpt-mini", think=True,
    ):
        pass

    assert "reasoning_effort" not in captured
    assert "think" not in captured
    assert "options" not in captured


@pytest.mark.asyncio
async def test_keep_alive_sent_when_provided(monkeypatch):
    """A non-None keep_alive is forwarded verbatim in the Ollama payload."""
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", keep_alive=-1,
    ):
        pass

    assert captured["keep_alive"] == -1


@pytest.mark.asyncio
async def test_keep_alive_omitted_when_none(monkeypatch):
    """keep_alive=None must NOT add the field — preserve the runtime default."""
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    ):
        pass

    assert "keep_alive" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delta",
    [
        {"thinking": "thinking A"},
        {"reasoning": "thinking B"},
        {"reasoning_content": "thinking C"},
    ],
)
async def test_reasoning_delta_fields_emit_thinking_delta(delta, monkeypatch):
    lines = _sse({"choices": [{"delta": delta}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b", think=True,
    )]

    assert events[0]["type"] == "thinking_delta"
    assert events[0]["content"].startswith("thinking")


@pytest.mark.asyncio
async def test_message_form_reasoning_emits_thinking_delta(monkeypatch):
    # Some providers put reasoning on choice.message instead of delta.
    lines = _sse({"choices": [{"message": {"reasoning_content": "full reasoning"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b", think=True,
    )]

    assert events[0] == {"type": "thinking_delta", "content": "full reasoning"}


@pytest.mark.asyncio
async def test_ollama_eval_counters_yielded_as_terminal_stream_stats(monkeypatch):
    # Ollama emits prompt_eval_count / eval_count (and friends) at the top level
    # of the terminal stream chunk. The runtime needs these as a single terminal
    # event to record prefill/decode telemetry, and the Ollama payload must carry
    # stream_options.include_usage so the endpoint emits usage at all.
    chunk = {
        "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
        "prompt_eval_count": 12,
        "prompt_eval_duration": 0.045,
        "eval_count": 3,
        "eval_duration": 0.030,
    }
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_sse(chunk), captured))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    )]

    stats_events = [e for e in events if e["type"] == "stream_stats"]
    assert len(stats_events) == 1
    assert stats_events[0]["stats"]["prompt_eval_count"] == 12
    assert stats_events[0]["stats"]["eval_count"] == 3
    # stream_stats is the terminal event (after the token).
    assert events[-1] == stats_events[0]
    # The stream_options include_usage flag is sent on the wire for Ollama.
    assert captured.get("stream_options") == {"include_usage": True}


@pytest.mark.asyncio
async def test_content_delta_still_emits_token(monkeypatch):
    lines = _sse({"choices": [{"delta": {"content": "hello"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    )]

    assert events[0] == {"type": "token", "content": "hello"}


@pytest.mark.asyncio
async def test_tool_calls_still_stream(monkeypatch):
    # Ollama delivers the tool_calls delta together with finish_reason="tool_calls"
    # in the same chunk. Verify thinking parsing didn't break tool-call streaming.
    lines = _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",
        "type": "function", "function": {"name": "get_time", "arguments": "{}"}}]},
        "finish_reason": "tool_calls"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=[{"type": "function", "function": {"name": "get_time"}}],
    )]

    assert events[-1]["type"] == "tool_calls_done"
    assert events[-1]["calls"][0]["function"]["name"] == "get_time"


@pytest.mark.asyncio
async def test_online_toggle_puts_web_search_on_wire(monkeypatch):
    # web_search=True must result in a real web_search tool definition (with the
    # `query` parameter) in the request payload sent to the model, plus
    # tool_choice="auto". This would have failed before the schema-merge fix.
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    allowed = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search_enabled=True)
    tools = _format_tools_for_model(allowed)
    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=tools,
    ):
        pass

    assert captured.get("tool_choice") == "auto"
    assert "tools" in captured
    ws = next(t for t in captured["tools"] if t["function"]["name"] == "web_search")
    assert ws["function"]["parameters"]["required"] == ["query"]


@pytest.mark.asyncio
async def test_online_toggle_off_omits_web_search(monkeypatch):
    captured: dict = {}
    lines = _sse({"choices": [{"delta": {"content": "ok"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, captured))

    allowed = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search_enabled=False)
    tools = _format_tools_for_model(allowed)
    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=tools,
    ):
        pass

    names = [t["function"]["name"] for t in captured.get("tools", [])]
    assert "web_search" not in names
    assert "calculator" in names  # other tools still offered


@pytest.mark.asyncio
async def test_tool_call_arguments_split_across_chunks(monkeypatch):
    # The parser must accumulate function.arguments as a string across chunks
    # sharing the same tool_calls index until finish_reason="tool_calls" flushes.
    # Split the JSON {"query":"news this week"} across two intermediate chunks.
    def _tc_delta(index, **function_fields):
        func = {"name": "", "arguments": ""}
        func.update(function_fields)
        return {"tool_calls": [{"index": index, "id": "call_1", "type": "function", "function": func}]}

    chunk1 = {"choices": [{"delta": _tc_delta(0, name="web_search", arguments='{"quer')}]}
    chunk2 = {"choices": [{"delta": _tc_delta(0, arguments='y":"news this week"}')}]}
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    lines = _sse(chunk1, chunk2, chunk3)
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=[{"type": "function", "function": {"name": "web_search"}}],
    )]

    assert events[-1]["type"] == "tool_calls_done"
    call = events[-1]["calls"][0]
    assert call["function"]["name"] == "web_search"
    assert call["function"]["arguments"] == {"query": "news this week"}


# ── Prompt-JSON tool-call adapter ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_json_envelope_synthesizes_tool_call(monkeypatch):
    # A prompt-json model emits the tool-call envelope inline in the text stream.
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    lines = _sse({"choices": [{"delta": {"content": "Let me check. " + envelope}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    # Only the preamble streams as text; the envelope is suppressed.
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Let me check. " in tokens
    assert "tool_call" not in tokens
    # A synthesized tool_calls_done event is emitted with the parsed call.
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    call = tc[0]["calls"][0]
    assert call["function"]["name"] == "get_time"
    assert call["function"]["arguments"] == {}
    assert call["id"].startswith("call_")


@pytest.mark.asyncio
async def test_prompt_json_direct_action_web_search_synthesizes_tool_call(monkeypatch):
    # Regression: small models sometimes emitted this direct-action shorthand,
    # which used to leak to chat as plain JSON instead of executing web_search.
    envelope = '{"action":"web_search","query":"what year is it","max_results":5}'
    lines = _sse({"choices": [{"delta": {"content": envelope}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "search"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "web_search" not in tokens
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    call = tc[0]["calls"][0]
    assert call["function"]["name"] == "web_search"
    assert call["function"]["arguments"] == {
        "query": "what year is it",
        "max_results": 5,
    }


@pytest.mark.asyncio
async def test_prompt_json_plural_envelope_synthesizes_multiple_calls(monkeypatch):
    # The plural envelope batches independent calls into one tool_calls_done
    # event so the runtime's gather-eligible path runs them concurrently. The
    # singular form stays supported; _done still stops after the one envelope.
    envelope = (
        '{"action":"tool_calls","calls":['
        '{"tool":"get_time","arguments":{}},'
        '{"tool":"web_search","arguments":{"query":"weather today","max_results":3}}'
        ']}'
    )
    lines = _sse({"choices": [{"delta": {"content": "Checking. " + envelope}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "time then weather"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    # Preamble streams; the envelope is suppressed (no JSON leaks to chat).
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Checking. " in tokens
    assert "tool_calls" not in tokens
    # One tool_calls_done carrying BOTH calls — the core Step 6 assertion.
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    calls = tc[0]["calls"]
    assert len(calls) == 2
    assert calls[0]["function"]["name"] == "get_time"
    assert calls[0]["function"]["arguments"] == {}
    assert calls[1]["function"]["name"] == "web_search"
    assert calls[1]["function"]["arguments"] == {"query": "weather today", "max_results": 3}
    # Distinct call ids, OpenAI-shaped.
    assert all(c["id"].startswith("call_") for c in calls)
    assert len({c["id"] for c in calls}) == 2


@pytest.mark.asyncio
async def test_prompt_json_plural_envelope_malformed_falls_through_to_text(monkeypatch):
    # A plural envelope with an empty/non-list calls field is NOT a tool call —
    # it must fall through to text (not synthesize an empty tool_calls_done).
    envelope = '{"action":"tool_calls","calls":[]}'
    lines = _sse({"choices": [{"delta": {"content": envelope}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]
    assert not any(e["type"] == "tool_calls_done" for e in events)
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "tool_calls" in tokens  # emitted as plain text, kept scanning


@pytest.mark.asyncio
async def test_prompt_json_envelope_split_across_chunks(monkeypatch):
    # The envelope arrives fragmented across chunks (incl. mid-marker). The
    # scanner must hold back the partial marker, accumulate, and synthesize once
    # complete. Text after the envelope is suppressed (the runtime breaks on the
    # tool call, so trailing text would be discarded anyway).
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    parts = ["Sure. ", envelope[:7], envelope[7:18], envelope[18:]]
    chunks = [{"choices": [{"delta": {"content": p}}]} for p in parts]
    chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    lines = _sse(*chunks)
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "Sure. "
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    assert tc[0]["calls"][0]["function"]["name"] == "get_time"


@pytest.mark.asyncio
async def test_native_mode_does_not_scan_for_envelope(monkeypatch):
    # In native mode (default), envelope-shaped text is plain text — no scanner.
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    lines = _sse({"choices": [{"delta": {"content": "text " + envelope}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    )]  # default tool_call_mode = openai_native

    assert not any(e["type"] == "tool_calls_done" for e in events)
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert envelope in tokens


@pytest.mark.asyncio
async def test_prompt_json_envelope_in_markdown_fence(monkeypatch):
    # Small models often wrap the envelope in a markdown code fence; the marker
    # search (for the literal {"action") must still find it inside the fence.
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    content = "```json\n" + envelope + "\n```"
    lines = _sse({"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    assert tc[0]["calls"][0]["function"]["name"] == "get_time"
    # The fence and envelope don't leak as answer text.
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "```" not in tokens
    assert "tool_call" not in tokens
