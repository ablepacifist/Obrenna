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

# ── Literal <think> tag stream filter ────────────────────────────────────────
#
# Distilled orchestrators may emit literal <think>…</think> blocks in
# delta.content (separate from Ollama's structured reasoning fields, which are
# handled below). These must NEVER reach the user-visible answer: the filter
# splits streamed content into (visible, thinking) so think spans are emitted
# as thinking_delta events and stripped from token events.

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
# Hold back a possible partial tag forming at the buffer tail.
_THINK_HOLDBACK = max(len(_THINK_OPEN), len(_THINK_CLOSE)) - 1


class ThinkTagStreamFilter:
    """Split literal ``<think>…</think>`` spans out of streamed text."""

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, content: str) -> tuple[str, str]:
        """Accept new content; return (visible_text, thinking_text)."""
        self._buf += content
        return self._drain(hold_tail=True)

    def flush(self) -> tuple[str, str]:
        """At stream end, release everything (an unclosed tag stays thinking)."""
        return self._drain(hold_tail=False)

    def _drain(self, *, hold_tail: bool) -> tuple[str, str]:
        visible: list[str] = []
        thinking: list[str] = []
        while True:
            tag = _THINK_CLOSE if self._in_think else _THINK_OPEN
            idx = self._buf.find(tag)
            if idx == -1:
                keep = _THINK_HOLDBACK if hold_tail else 0
                emit_to = max(0, len(self._buf) - keep)
                # Never split mid-partial-tag: only emit up to the last char
                # that cannot begin a tag prefix still forming at the tail.
                chunk = self._buf[:emit_to]
                self._buf = self._buf[emit_to:]
                (thinking if self._in_think else visible).append(chunk)
                break
            span = self._buf[:idx]
            (thinking if self._in_think else visible).append(span)
            self._buf = self._buf[idx + len(tag):]
            self._in_think = not self._in_think
        return ("".join(visible), "".join(thinking))


_ENVELOPE_MARKER = '{"action"'
_DIRECT_ACTION_TOOL_NAMES = {"get_time", "calculator", "file_read", "web_search", "get_location"}
# Characters held back while a marker may be forming at the tail of the buffer.
# Must exceed len('{"action":"tool_call"') so a partial marker is never flushed.
_PROMPT_JSON_HOLDACK = 24
# A leading markdown code fence (```json / ```) immediately before the envelope.
# Small models often wrap the JSON in a fence; suppress it so it never streams.
_LEADING_FENCE_RE = re.compile(r"\s*```[a-zA-Z0-9.+\-]*\s*\n?\s*$")


def _coerce_args(args: Any) -> dict:
    """Normalize a tool-call ``arguments`` value to a dict.

    Some models emit arguments as a JSON string instead of an object; parse it
    when possible, else fall back to ``{}``. Shared by the singular and plural
    envelope parse paths so they coerce identically.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {}
    return args if isinstance(args, dict) else {}


def _make_call(tool: str, args: Any) -> dict | None:
    """Build one OpenAI-shaped tool-call dict from a tool name + arguments.

    Returns ``None`` when the tool name is empty (caller skips it). Used by both
    the singular (``tool_call``) and plural (``tool_calls``) envelope branches.
    """
    if not tool:
        return None
    return {
        "id": "call_" + uuid.uuid4().hex[:12],
        "type": "function",
        "function": {"name": tool, "arguments": _coerce_args(args)},
    }


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
        if action == "tool_calls":
            # Plural envelope: {"action":"tool_calls","calls":[{tool,arguments}, ...]}
            # Parse all entries into one multi-call tool_calls_done event, then stop.
            # Malformed (non-list / empty / no valid entries) falls through to text.
            calls_raw = obj.get("calls", [])
            if isinstance(calls_raw, list) and calls_raw:
                calls: list[dict] = []
                for entry in calls_raw:
                    if not isinstance(entry, dict):
                        continue
                    tool = entry.get("tool") or entry.get("name") or ""
                    call = _make_call(tool, entry.get("arguments", {}))
                    if call is not None:
                        calls.append(call)
                if calls:
                    self._flushed = end
                    self._done = True
                    return (pre, {"type": "tool_calls_done", "calls": calls})
            # Malformed plural envelope — emit as text, keep scanning.
            self._flushed = end
            return (pre + slice_, None)

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

        call = _make_call(tool, args)
        if call is None:
            # Empty tool name — emit as text, keep scanning.
            self._flushed = end
            return (pre + slice_, None)
        self._flushed = end
        self._done = True
        return (pre, {"type": "tool_calls_done", "calls": [call]})


_VALID_REASONING_EFFORTS = ("none", "low", "medium")


def _resolve_reasoning_effort(think: bool | str) -> str:
    """Normalize the ``think`` arg to an Ollama ``reasoning_effort`` level.

    Accepts a bool (True -> "medium", False -> "none") for backward compatibility,
    or an explicit level string ("none" | "low" | "medium") so callers can
    downshift reasoning on cheap continuation rounds without fully disabling it.
    Any unrecognized value falls back to "none" (safe — no reasoning requested).
    """
    if isinstance(think, str):
        return think if think in _VALID_REASONING_EFFORTS else "none"
    return "medium" if think else "none"


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
    think: bool | str = False,
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

    ``think`` controls the Ollama ``reasoning_effort`` field: a bool (True ->
    "medium", False -> "none", kept for backward compatibility) or an explicit
    level string ("none" | "low" | "medium") so callers can downshift reasoning
    on cheap continuation rounds without disabling it. Reasoning chunks
    (``delta.reasoning_content`` / ``delta.reasoning`` / ``delta.thinking``) are
    yielded as ``thinking_delta`` events whenever present. Non-Ollama runtimes
    send no reasoning controls.

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
        payload["reasoning_effort"] = _resolve_reasoning_effort(think)
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
        # Literal <think> tags in content must never reach the visible answer.
        think_filter = ThinkTagStreamFilter()

        def _content_events(text: str) -> list[dict[str, Any]]:
            """Route filtered content through the prompt-JSON scanner to events."""
            events: list[dict[str, Any]] = []
            if not text:
                return events
            if prompt_json_scanner is not None:
                token_text, tool_event = prompt_json_scanner.feed(text)
                if token_text:
                    events.append({"type": "token", "content": token_text})
                if tool_event is not None:
                    events.append(tool_event)
            else:
                events.append({"type": "token", "content": text})
            return events

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

                    # Text content — strip literal <think> spans first (they
                    # stream as thinking_delta, never as answer tokens), then
                    # scan what remains for prompt-JSON tool envelopes.
                    content = delta.get("content")
                    if content:
                        visible, think_text = think_filter.feed(content)
                        if think_text:
                            yield {"type": "thinking_delta", "content": think_text}
                        for ev in _content_events(visible):
                            yield ev

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
                        visible, think_text = think_filter.flush()
                        if think_text:
                            yield {"type": "thinking_delta", "content": think_text}
                        for ev in _content_events(visible):
                            yield ev
                        if prompt_json_scanner is not None:
                            tail = prompt_json_scanner.flush()
                            if tail:
                                yield {"type": "token", "content": tail}

            except json.JSONDecodeError:
                logger.warning("Failed to parse SSE chunk: %s", data_str[:100])
                continue

        # Defensive final flush: some streams end with [DONE] and no explicit
        # finish_reason. Emit anything the think filter and prompt-JSON scanner
        # are still holding.
        visible, think_text = think_filter.flush()
        if think_text:
            yield {"type": "thinking_delta", "content": think_text}
        for ev in _content_events(visible):
            yield ev
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
