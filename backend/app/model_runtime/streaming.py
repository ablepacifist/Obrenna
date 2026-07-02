"""Streaming model runtime client.

Provides async streaming generation for the agent runtime.
Wraps the existing OpenAI-compatible endpoint with a role-based
streaming interface that supports token-by-token delivery and tool call detection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

from .client import _run
from .client_pool import get_model_client
from .config import RuntimeConfig

logger = logging.getLogger(__name__)

DEFAULT_STREAM_TIMEOUT = 60.0


def _first_non_empty_str(*values: object) -> str:
    """Return the first non-empty string among ``values`` (else ``""``)."""
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


# ── SSE chunk type detection ─────────────────────────────────────────────────


def _is_tool_call_chunk(chunk: dict[str, Any]) -> bool:
    """Check if an SSE chunk contains tool_call deltas."""
    choices = chunk.get("choices", [])
    if not choices:
        return False
    delta = choices[0].get("delta", {})
    return bool(delta.get("tool_calls")) or delta.get("finish_reason") == "tool_calls"


# ── Prompt-JSON tool-call scanner ────────────────────────────────────────────
#
# For models that lack native OpenAI tool-call support (small distilled GGUF
# orchestrators), the runtime injects a tool contract into the prompt asking the
# model to emit a JSON envelope: {"action":"tool_call","tool":...,"arguments":...}.
# This scanner watches the streaming text, emits any text that is NOT part of an
# envelope as token events, and synthesizes a ``tool_calls_done`` event (matching
# the native path's shape) when a complete envelope arrives — suppressing the
# envelope itself from the token stream so it never reaches the UI as text.

_ENVELOPE_MARKER = '{"action"'
_DIRECT_ACTION_TOOL_NAMES = {"get_time", "calculator", "file_read", "web_search", "get_location"}
# Characters held back while a marker may be forming at the tail of the buffer.
# Must exceed len('{"action":"tool_call"') so a partial marker is never flushed.
_PROMPT_JSON_HOLDACK = 24
# A leading markdown code fence (```json / ```) immediately before the envelope.
# Small models often wrap the JSON in a fence; suppress it so it never streams.
_LEADING_FENCE_RE = re.compile(r"\s*```[a-zA-Z0-9.+\-]*\s*\n?\s*$")


def _find_json_object_end(buffer: str, start: int) -> int | None:
    """Return the exclusive end index of the JSON object starting at ``start``.

    Scans from the ``{`` at ``start``, tracking string literals and escapes, and
    returns the index just past the matching closing brace. Returns ``None`` if
    the object is not yet balanced (more chunks needed).
    """
    if start >= len(buffer) or buffer[start] != "{":
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(buffer)):
        ch = buffer[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


class PromptJsonToolScanner:
    """Scan a streaming text buffer for a prompt-JSON tool-call envelope."""

    def __init__(self) -> None:
        self._buffer: str = ""
        self._flushed: int = 0  # index up to which text has been emitted
        self._done: bool = False  # stop after one synthesized tool call

    def feed(self, content: str) -> tuple[str, dict[str, Any] | None]:
        """Accept new content; return (token_text, tool_calls_done_event|None)."""
        if self._done:
            return ("", None)
        if content:
            self._buffer += content
        return self._scan()

    def flush(self) -> str:
        """At stream end, emit any held-back text (no envelope pending)."""
        if self._done:
            return ""
        remaining = self._buffer[self._flushed:]
        self._flushed = len(self._buffer)
        return remaining

    def _scan(self) -> tuple[str, dict[str, Any] | None]:
        marker = self._buffer.find(_ENVELOPE_MARKER, self._flushed)
        if marker == -1:
            # No envelope yet — emit everything except a holdback tail in case a
            # marker is still forming at the end of the buffer.
            safe_to = max(self._flushed, len(self._buffer) - _PROMPT_JSON_HOLDACK)
            text = self._buffer[self._flushed:safe_to]
            self._flushed = safe_to
            return (text, None)

        # Emit any text that precedes the candidate envelope, stripping a
        # leading markdown code fence (```json / ```) so it doesn't leak as text.
        pre = self._buffer[self._flushed:marker]
        fence_match = _LEADING_FENCE_RE.search(pre)
        if fence_match:
            pre = pre[:fence_match.start()]
        self._flushed = marker

        end = _find_json_object_end(self._buffer, marker)
        if end is None:
            # JSON not yet closed — hold everything from the marker onward.
            return (pre, None)

        slice_ = self._buffer[marker:end]
        try:
            obj = json.loads(slice_)
        except json.JSONDecodeError:
            # Looked like a marker but isn't valid JSON — treat as plain text and
            # continue scanning after it.
            self._flushed = end
            return (pre + slice_, None)

        if not isinstance(obj, dict):
            # Valid JSON but not a tool call — emit as text, keep scanning.
            self._flushed = end
            return (pre + slice_, None)

        action = obj.get("action")
        if action == "tool_call":
            tool = obj.get("tool", "")
            args = obj.get("arguments", {})
        elif isinstance(action, str) and action in _DIRECT_ACTION_TOOL_NAMES:
            # Compatibility for small models that emit {"action":"web_search", ...}
            # instead of the canonical prompt-JSON tool_call envelope.
            tool = action
            args = {k: v for k, v in obj.items() if k != "action"}
        else:
            # Valid JSON but not a tool call — emit as text, keep scanning.
            self._flushed = end
            return (pre + slice_, None)

        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        call = {
            "id": "call_" + uuid.uuid4().hex[:12],
            "type": "function",
            "function": {"name": tool, "arguments": args},
        }
        self._flushed = end
        self._done = True
        return (pre, {"type": "tool_calls_done", "calls": [call]})


async def chat_completion_stream(
    config: RuntimeConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    role: str = "main_reasoner",
    temperature: float = 0.2,
    timeout: float = DEFAULT_STREAM_TIMEOUT,
    stop: list[str] | None = None,
    tools: list[dict] | None = None,
    think: bool = False,
    tool_call_mode: str = "openai_native",
    keep_alive: Any = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream tokens from an OpenAI-compatible endpoint.

    Yields dict events:
      {"type": "token", "content": "..."}  — for text tokens
      {"type": "thinking_delta", "content": "..."}  — for reasoning/thinking tokens
      {"type": "tool_calls_done", "calls": [...]}  — when model requests tool calls

    When `tools` is provided, includes tools/tool_choice in the request and
    parses delta.tool_calls from SSE chunks.

    When `think` is True and the runtime is Ollama, sends ``reasoning_effort`` to
    request a reasoning trace; reasoning chunks (``delta.reasoning_content`` /
    ``delta.reasoning`` / ``delta.thinking``) are yielded as ``thinking_delta``
    events. Non-Ollama runtimes send no reasoning controls.

    When `tools` is None, yields only token events (backward-compatible behavior).

    When `tool_call_mode` is ``"prompt_json"``, the model lacks native tool-call
    support: ``tools`` is expected to be None (no OpenAI tools field sent) and the
    streaming text is scanned for a ``{"action":"tool_call",...}`` envelope, which
    is synthesized into a ``tool_calls_done`` event (and suppressed from tokens).
    """
    chosen = model or config.model_for(role)
    if not chosen:
        raise ValueError("No model configured for this request.")

    payload: dict = {
        "model": chosen,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if stop:
        payload["stop"] = stop
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    # Ollama model residency. ``-1`` pins the model in VRAM/RAM for the whole
    # session (orchestrator); a duration string (e.g. ``"5m"``) keeps a lazy
    # role loaded briefly after its last call then evicts it. ``None`` = omit
    # the field entirely (preserve the runtime's default behaviour). The value
    # is sourced from hardware_catalog.json via the resolver — never hardcoded
    # in the runtime.
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    # Ollama OpenAI-compatible reasoning control. Never send native `think`/
    # `options.think` to /v1/chat/completions — only the OpenAI-style field.
    if config.runtime_kind == "ollama":
        payload["reasoning_effort"] = "medium" if think else "none"
        # Ask Ollama's OpenAI-compatible endpoint to emit a ``usage`` object (and
        # the non-standard top-level eval counters) in the final stream chunk so
        # the runtime can record prefill/decode telemetry. Harmless on non-Ollama
        # runtimes that ignore unknown fields; Ollama honours it.
        payload["stream_options"] = {"include_usage": True}

    logger.info("STREAMING REQUEST: model=%s url=%s messages_count=%d temperature=%.1f tools=%s",
                chosen, config.url("chat/completions"), len(messages), temperature,
                "yes" if tools else "no")

    # Ollama eval/usage counters. These appear at the top level of the terminal
    # stream chunk (sibling of ``choices``); capture whichever keys are present
    # and yield them once as a terminal ``stream_stats`` event for the runtime to
    # record. Non-Ollama runtimes leave this empty.
    _OLLAMA_STAT_KEYS = (
        "prompt_eval_count", "prompt_eval_duration",
        "eval_count", "eval_duration",
        "total_duration", "load_duration", "prompt_eval_rate",
    )
    stats: dict[str, Any] = {}

    client = get_model_client()
    async with client.stream(
        "POST",
        config.url("chat/completions"),
        headers=config.headers,
        json=payload,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        logger.info("STREAMING RESPONSE: status=%d", resp.status_code)

        # Track tool_calls by index across SSE chunks
        tool_calls_buffer: dict[int, dict[str, Any]] = {}
        # Prompt-JSON envelope scanner (only active for non-native models).
        prompt_json_scanner = PromptJsonToolScanner() if tool_call_mode == "prompt_json" else None

        async for line in resp.aiter_lines():
            if not line or line == "data: [DONE]":
                continue
            if not line.startswith("data: "):
                continue
            data_str = line[6:]  # strip "data: " prefix
            if not data_str.strip():
                continue
            try:
                chunk = json.loads(data_str)
                # Capture Ollama eval/usage counters. The terminal chunk
                # carries the totals; later values overwrite earlier ones so
                # the last-seen (final) value wins. ``usage`` is the
                # OpenAI-standard fallback when the raw eval keys are absent.
                for key in _OLLAMA_STAT_KEYS:
                    if key in chunk:
                        stats[key] = chunk[key]
                if isinstance(chunk.get("usage"), dict):
                    stats["usage"] = chunk["usage"]
                choices = chunk.get("choices", [])
                for choice in choices:
                    delta = choice.get("delta", {})
                    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}

                    # Reasoning / thinking (extracted before content so it
                    # streams into the ephemeral thinking pane, not the answer).
                    thinking = _first_non_empty_str(
                        delta.get("reasoning_content"),
                        delta.get("reasoning"),
                        delta.get("thinking"),
                        message.get("reasoning_content"),
                        message.get("reasoning"),
                        message.get("thinking"),
                    )
                    if thinking:
                        yield {"type": "thinking_delta", "content": thinking}
                        continue

                    # Text content
                    content = delta.get("content")
                    if content:
                        if prompt_json_scanner is not None:
                            text, tool_event = prompt_json_scanner.feed(content)
                            if text:
                                yield {"type": "token", "content": text}
                            if tool_event is not None:
                                yield tool_event
                        else:
                            yield {"type": "token", "content": content}

                    # Tool calls
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        for tc in tool_calls:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            tc_buf = tool_calls_buffer[idx]
                            if tc.get("id"):
                                tc_buf["id"] = tc["id"]
                            if tc.get("type"):
                                tc_buf["type"] = tc["type"]
                            func = tc.get("function")
                            if func:
                                if func.get("name"):
                                    tc_buf["function"]["name"] = func["name"]
                                if func.get("arguments"):
                                    tc_buf["function"]["arguments"] += func["arguments"]

                    # Finish detection
                    finish_reason = choice.get("finish_reason")
                    if finish_reason == "tool_calls" and tool_calls_buffer:
                        # Aggregate complete tool calls
                        calls = []
                        for idx in sorted(tool_calls_buffer.keys()):
                            tc = tool_calls_buffer[idx]
                            args = tc["function"]["arguments"]
                            try:
                                args_dict = json.loads(args)
                            except (json.JSONDecodeError, TypeError):
                                args_dict = args
                            calls.append({
                                "id": tc["id"],
                                "type": tc["type"],
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": args_dict,
                                },
                            })
                        tool_calls_buffer.clear()
                        yield {"type": "tool_calls_done", "calls": calls}
                    elif finish_reason == "stop":
                        # Stream ended without tool calls — drop any partial
                        # buffer. Do NOT clear on None: that is the value on
                        # intermediate chunks, and tool-call argument fragments
                        # must accumulate across chunks until finish_reason
                        # "tool_calls" flushes them.
                        tool_calls_buffer.clear()
                        if prompt_json_scanner is not None:
                            tail = prompt_json_scanner.flush()
                            if tail:
                                yield {"type": "token", "content": tail}

            except json.JSONDecodeError:
                logger.warning("Failed to parse SSE chunk: %s", data_str[:100])
                continue

        # Defensive final flush: some streams end with [DONE] and no explicit
        # finish_reason. Emit any text the prompt-JSON scanner is still holding.
        if prompt_json_scanner is not None:
            tail = prompt_json_scanner.flush()
            if tail:
                yield {"type": "token", "content": tail}

        # Yield the captured Ollama eval/usage counters as a single terminal
        # event. Empty on non-Ollama runtimes or when no counters were present.
        if stats:
            yield {"type": "stream_stats", "stats": stats}


# ── Sync wrapper for use from sync contexts ──────────────────────────────────


async def _collect_stream(config, messages, *, model=None, role="main_reasoner",
                          temperature=0.2, timeout=DEFAULT_STREAM_TIMEOUT):
    """Collect all tokens from the stream into a single string."""
    chunks = []
    async for event in chat_completion_stream(
        config, messages, model=model, role=role,
        temperature=temperature, timeout=timeout,
    ):
        if isinstance(event, dict) and event.get("type") == "token":
            chunks.append(event["content"])
        elif isinstance(event, str):
            chunks.append(event)
    return "".join(chunks)


def chat_completion_stream_sync(
    config: RuntimeConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    role: str = "main_reasoner",
    temperature: float = 0.2,
    timeout: float = DEFAULT_STREAM_TIMEOUT,
) -> str:
    """Synchronous wrapper: collect stream tokens into one string."""
    return _run(
        _collect_stream(config, messages, model=model, role=role,
                        temperature=temperature, timeout=timeout)
    )
