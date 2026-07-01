"""Tests for the streaming model runtime: reasoning_effort payload + thinking parsing."""
import httpx
import pytest

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