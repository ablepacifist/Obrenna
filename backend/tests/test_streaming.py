"""Tests for the streaming model runtime.

Ollama requests go through the NATIVE /api/chat endpoint (NDJSON), which is the
only surface that honours options.num_ctx — the /v1/chat/completions compat
endpoint silently caps context at 4096 and truncates long prompts + tool-call
JSON. These tests assert the native request shape and NDJSON parsing. The
OpenAI-compat path (used for non-Ollama runtimes like LM Studio/vLLM) is still
covered via the non-ollama config + SSE fixtures.
"""
import json

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
    """Fake httpx.AsyncClient that captures the JSON payload and feeds `lines`
    back through aiter_lines() (works for both native NDJSON and SSE)."""

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
            captured["__url__"] = url

            class _CM:
                async def __aenter__(self):
                    return FakeResponse()

                async def __aexit__(self, *a):
                    return False

            return _CM()

    return FakeClient


# ── Native /api/chat NDJSON fixtures (Ollama path) ───────────────────────────


def _msg(content=None, thinking=None, tool_calls=None, done=False, **top):
    """Build one native /api/chat NDJSON chunk."""
    m: dict = {}
    if content is not None:
        m["content"] = content
    if thinking is not None:
        m["thinking"] = thinking
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    chunk = {"model": "qwen3:8b", "message": m, "done": done}
    chunk.update(top)
    return chunk


def _ndjson(*chunks) -> list[str]:
    """Native /api/chat emits newline-delimited JSON objects (no `data:` prefix)."""
    return [json.dumps(c) for c in chunks]


def _content_stream(text, **done_top):
    """A native stream that emits `text` then a terminal done chunk."""
    return _ndjson(_msg(content=text), _msg(content="", done=True, **done_top))


# ── SSE fixtures (OpenAI-compat path, non-ollama runtimes) ───────────────────


def _sse(*chunks) -> list[str]:
    """Wrap JSON chunk dicts as SSE `data:` lines, ending with [DONE]."""
    return [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]


# ── Native request-shape assertions ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_uses_native_api_chat_endpoint(monkeypatch):
    """Ollama must hit /api/chat, NOT /v1/chat/completions — only native honours
    options.num_ctx (the /v1 endpoint caps context at 4096 and truncates)."""
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    ):
        pass

    assert captured["__url__"] == "http://localhost:11434/api/chat"
    assert captured["stream"] is True


@pytest.mark.asyncio
async def test_ollama_thinking_enabled_sets_think_true(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", think=True,
    )]

    assert captured["think"] is True
    # Native controls reasoning via `think`, never the OpenAI-compat fields.
    assert "reasoning_effort" not in captured
    assert "stream_options" not in captured
    token = "".join(e["content"] for e in events if e["type"] == "token")
    assert token == "ok"


@pytest.mark.asyncio
async def test_ollama_thinking_disabled_sets_think_false(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", think=False,
    ):
        pass

    assert captured["think"] is False


@pytest.mark.asyncio
async def test_ollama_default_think_false(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    ):
        pass

    assert captured["think"] is False


@pytest.mark.asyncio
async def test_num_ctx_sent_as_native_options(monkeypatch):
    """num_ctx reaches Ollama as options.num_ctx on the native endpoint — this is
    the whole fix: /v1 ignored it and capped at 4096, truncating tool-call JSON."""
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", num_ctx=32768,
    ):
        pass

    assert captured["options"]["num_ctx"] == 32768


@pytest.mark.asyncio
async def test_num_ctx_omitted_from_options_when_none(monkeypatch):
    """num_ctx=None must not add options.num_ctx (options still carries temperature)."""
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    ):
        pass

    assert "num_ctx" not in captured["options"]


@pytest.mark.asyncio
async def test_num_ctx_not_sent_on_non_ollama_runtime(monkeypatch):
    """num_ctx is Ollama-specific — never sent to other OpenAI-compat runtimes."""
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_sse({"choices": [{"delta": {"content": "ok"}}]}), captured))

    async for _ in chat_completion_stream(
        _non_ollama_config(), [{"role": "user", "content": "hi"}],
        model="gpt-mini", num_ctx=32768,
    ):
        pass

    assert "options" not in captured


@pytest.mark.asyncio
async def test_keep_alive_sent_when_provided(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", keep_alive=-1,
    ):
        pass

    assert captured["keep_alive"] == -1


@pytest.mark.asyncio
async def test_keep_alive_omitted_when_none(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    ):
        pass

    assert "keep_alive" not in captured


# ── Native NDJSON parsing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_native_thinking_field_emits_thinking_delta(monkeypatch):
    """Native surfaces reasoning as message.thinking → thinking_delta (never a token)."""
    lines = _ndjson(_msg(thinking="reasoning here"), _msg(content="answer", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b", think=True,
    )]

    assert events[0] == {"type": "thinking_delta", "content": "reasoning here"}
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "answer"


@pytest.mark.asyncio
async def test_content_delta_emits_token(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("hello"), {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "hello"


@pytest.mark.asyncio
async def test_native_tool_calls_stream(monkeypatch):
    """Native delivers a complete tool call as message.tool_calls (args already a dict)."""
    lines = _ndjson(
        _msg(tool_calls=[{"function": {"name": "get_time", "arguments": {}}}]),
        _msg(content="", done=True),
    )
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=[{"type": "function", "function": {"name": "get_time"}}],
    )]

    tcd = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tcd) == 1
    assert tcd[0]["calls"][0]["function"]["name"] == "get_time"
    assert tcd[0]["calls"][0]["function"]["arguments"] == {}
    assert tcd[0]["calls"][0]["id"].startswith("call_")


@pytest.mark.asyncio
async def test_native_tool_call_string_args_coerced_to_dict(monkeypatch):
    """If a model emits arguments as a JSON string, it's parsed to a dict."""
    lines = _ndjson(
        _msg(tool_calls=[{"function": {"name": "web_search", "arguments": '{"query":"news"}'}}]),
        _msg(content="", done=True),
    )
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=[{"type": "function", "function": {"name": "web_search"}}],
    )]

    call = [e for e in events if e["type"] == "tool_calls_done"][0]["calls"][0]
    assert call["function"]["arguments"] == {"query": "news"}


@pytest.mark.asyncio
async def test_native_eval_counters_yielded_as_terminal_stream_stats(monkeypatch):
    """Native carries prompt_eval_count/eval_count on the terminal done chunk."""
    lines = _ndjson(
        _msg(content="ok"),
        _msg(content="", done=True, prompt_eval_count=12, eval_count=3,
             prompt_eval_duration=45, eval_duration=30),
    )
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    )]

    stats_events = [e for e in events if e["type"] == "stream_stats"]
    assert len(stats_events) == 1
    assert stats_events[0]["stats"]["prompt_eval_count"] == 12
    assert stats_events[0]["stats"]["eval_count"] == 3
    assert events[-1] == stats_events[0]


@pytest.mark.asyncio
async def test_online_toggle_puts_web_search_on_wire(monkeypatch):
    """web_search=True → a real web_search tool (with `query`) in the native tools list."""
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    allowed = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search_enabled=True)
    tools = _format_tools_for_model(allowed)
    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=tools,
    ):
        pass

    assert "tools" in captured
    ws = next(t for t in captured["tools"] if t["function"]["name"] == "web_search")
    assert ws["function"]["parameters"]["required"] == ["query"]


@pytest.mark.asyncio
async def test_online_toggle_off_omits_web_search(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_content_stream("ok"), captured))

    allowed = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search_enabled=False)
    tools = _format_tools_for_model(allowed)
    async for _ in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tools=tools,
    ):
        pass

    names = [t["function"]["name"] for t in captured.get("tools", [])]
    assert "web_search" not in names
    assert "calculator" in names


# ── OpenAI-compat path (non-ollama runtimes) still works ─────────────────────


@pytest.mark.asyncio
async def test_non_ollama_does_not_send_reasoning_controls(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_sse({"choices": [{"delta": {"content": "ok"}}]}), captured))

    async for _ in chat_completion_stream(
        _non_ollama_config(), [{"role": "user", "content": "hi"}],
        model="gpt-mini", think=True,
    ):
        pass

    assert captured["__url__"].endswith("/v1/chat/completions")
    assert "reasoning_effort" not in captured
    assert "think" not in captured
    assert "options" not in captured


@pytest.mark.asyncio
async def test_non_ollama_message_form_reasoning_emits_thinking_delta(monkeypatch):
    lines = _sse({"choices": [{"message": {"reasoning_content": "full reasoning"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _non_ollama_config(), [{"role": "user", "content": "hi"}], model="gpt-mini", think=True,
    )]

    assert events[0] == {"type": "thinking_delta", "content": "full reasoning"}


@pytest.mark.asyncio
async def test_non_ollama_tool_call_arguments_split_across_chunks(monkeypatch):
    """OpenAI-compat path accumulates function.arguments across SSE deltas."""
    def _tc_delta(index, **function_fields):
        func = {"name": "", "arguments": ""}
        func.update(function_fields)
        return {"tool_calls": [{"index": index, "id": "call_1", "type": "function", "function": func}]}

    chunk1 = {"choices": [{"delta": _tc_delta(0, name="web_search", arguments='{"quer')}]}
    chunk2 = {"choices": [{"delta": _tc_delta(0, arguments='y":"news this week"}')}]}
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_sse(chunk1, chunk2, chunk3), {}))

    events = [e async for e in chat_completion_stream(
        _non_ollama_config(), [{"role": "user", "content": "hi"}],
        model="gpt-mini", tools=[{"type": "function", "function": {"name": "web_search"}}],
    )]

    assert events[-1]["type"] == "tool_calls_done"
    call = events[-1]["calls"][0]
    assert call["function"]["name"] == "web_search"
    assert call["function"]["arguments"] == {"query": "news this week"}


# ── Prompt-JSON tool-call adapter (native content path) ──────────────────────


@pytest.mark.asyncio
async def test_prompt_json_envelope_synthesizes_tool_call(monkeypatch):
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    lines = _ndjson(_msg(content="Let me check. " + envelope), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Let me check. " in tokens
    assert "tool_call" not in tokens
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    call = tc[0]["calls"][0]
    assert call["function"]["name"] == "get_time"
    assert call["function"]["arguments"] == {}
    assert call["id"].startswith("call_")


@pytest.mark.asyncio
async def test_prompt_json_pretty_printed_envelope_synthesizes_tool_call(monkeypatch):
    """A model that PRETTY-PRINTS the envelope (newlines + indentation between
    `{` and `"action"`, like qwen2.5-coder) must still be detected as a tool
    call, not leaked as text. This was the "agent can't create files / test
    repo stays empty" bug: the literal `{"action"` marker missed `{\\n  "action"`.
    Streamed one char at a time to exercise the tail-holdback path too."""
    envelope = (
        "{\n"
        '    "action": "tool_call",\n'
        '    "tool": "codebase_write_file",\n'
        '    "arguments": {\n'
        '        "path": "tic_tac_toe.py",\n'
        '        "content": "print(1)"\n'
        "    }\n"
        "}"
    )
    full = "Let me create the file.\n\n" + envelope
    # One character per NDJSON chunk — the realistic streaming shape.
    lines = _ndjson(*[_msg(content=c) for c in full], _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "make tic tac toe"}],
        model="qwen2.5-coder:14b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Let me create the file." in tokens
    assert '"action"' not in tokens, "the pretty-printed envelope must NOT leak as text"
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1, "the pretty-printed tool call must be detected and executed"
    call = tc[0]["calls"][0]
    assert call["function"]["name"] == "codebase_write_file"
    assert call["function"]["arguments"]["path"] == "tic_tac_toe.py"


def test_lenient_prompt_json_repairs_single_quote_escapes():
    """Models writing code stuff single-quoted strings into the JSON content and
    escape them as \\' — which is invalid JSON and blew the whole write into the
    malformed→skeleton fallback. The lenient parser must recover it."""
    from app.model_runtime.streaming import _loads_prompt_json_lenient
    import json as _json
    bad = _json.dumps({"action": "tool_call", "tool": "codebase_write_file",
                       "arguments": {"path": "x.py", "content": "PLACEHOLDER"}})
    # Inject the invalid \' escape a model would produce for print('x').
    bad = bad.replace('"PLACEHOLDER"', r'"print(\'x\')"')
    assert _loads_prompt_json_lenient(bad)["arguments"]["content"] == "print('x')"
    # Strict-valid input is unchanged.
    good = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    assert _loads_prompt_json_lenient(good) == {"action": "tool_call", "tool": "get_time", "arguments": {}}
    # Truly broken input still returns None (→ caller marks malformed).
    assert _loads_prompt_json_lenient('{"action": broken') is None


@pytest.mark.asyncio
async def test_prompt_json_direct_action_web_search_synthesizes_tool_call(monkeypatch):
    envelope = '{"action":"web_search","query":"what year is it","max_results":5}'
    lines = _ndjson(_msg(content=envelope), _msg(content="", done=True))
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
    assert call["function"]["arguments"] == {"query": "what year is it", "max_results": 5}


@pytest.mark.asyncio
async def test_prompt_json_plural_envelope_synthesizes_multiple_calls(monkeypatch):
    envelope = (
        '{"action":"tool_calls","calls":['
        '{"tool":"get_time","arguments":{}},'
        '{"tool":"web_search","arguments":{"query":"weather today","max_results":3}}'
        ']}'
    )
    lines = _ndjson(_msg(content="Checking. " + envelope), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "time then weather"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Checking. " in tokens
    assert "tool_calls" not in tokens
    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    calls = tc[0]["calls"]
    assert len(calls) == 2
    assert calls[0]["function"]["name"] == "get_time"
    assert calls[1]["function"]["name"] == "web_search"
    assert calls[1]["function"]["arguments"] == {"query": "weather today", "max_results": 3}
    assert len({c["id"] for c in calls}) == 2


@pytest.mark.asyncio
async def test_prompt_json_plural_envelope_malformed_falls_through_to_text(monkeypatch):
    envelope = '{"action":"tool_calls","calls":[]}'
    lines = _ndjson(_msg(content=envelope), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]
    assert not any(e["type"] == "tool_calls_done" for e in events)
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "tool_calls" in tokens


@pytest.mark.asyncio
async def test_prompt_json_envelope_split_across_chunks(monkeypatch):
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    parts = ["Sure. ", envelope[:7], envelope[7:18], envelope[18:]]
    chunks = [_msg(content=p) for p in parts]
    chunks.append(_msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(_ndjson(*chunks), {}))

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
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    lines = _ndjson(_msg(content="text " + envelope), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}], model="qwen3:8b",
    )]  # default tool_call_mode = openai_native → no envelope scanning

    assert not any(e["type"] == "tool_calls_done" for e in events)
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert envelope in tokens


@pytest.mark.asyncio
async def test_prompt_json_envelope_in_markdown_fence(monkeypatch):
    envelope = '{"action":"tool_call","tool":"get_time","arguments":{}}'
    content = "```json\n" + envelope + "\n```"
    lines = _ndjson(_msg(content=content), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tc = [e for e in events if e["type"] == "tool_calls_done"]
    assert len(tc) == 1
    assert tc[0]["calls"][0]["function"]["name"] == "get_time"
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "```" not in tokens
    assert "tool_call" not in tokens


@pytest.mark.asyncio
async def test_prompt_json_envelope_never_closes_emits_malformed_not_text(monkeypatch):
    """A large edit cut off before the closing brace must surface as
    tool_call_malformed, never leak the raw unbalanced JSON as a token."""
    content = (
        'Let me fix this: {"action":"tool_call","tool":"codebase_edit_file",'
        '"arguments":{"new_string":"this never closes'
    )
    lines = _ndjson(_msg(content=content), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "Let me fix this: "
    assert "action" not in tokens
    malformed = [e for e in events if e["type"] == "tool_call_malformed"]
    assert len(malformed) == 1
    assert not any(e["type"] == "tool_calls_done" for e in events)


@pytest.mark.asyncio
async def test_prompt_json_envelope_invalid_json_emits_malformed_not_text(monkeypatch):
    envelope = '{"action":"tool_call","tool":"codebase_edit_file","arguments":{},}'
    lines = _ndjson(_msg(content=envelope), _msg(content="", done=True))
    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_client(lines, {}))

    events = [e async for e in chat_completion_stream(
        _ollama_config(), [{"role": "user", "content": "hi"}],
        model="qwen3:8b", tool_call_mode="prompt_json",
    )]

    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "action" not in tokens
    malformed = [e for e in events if e["type"] == "tool_call_malformed"]
    assert len(malformed) == 1
    assert not any(e["type"] == "tool_calls_done" for e in events)
