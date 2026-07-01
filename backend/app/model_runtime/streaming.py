"""Streaming model runtime client.

Provides async streaming generation for the agent runtime.
Wraps the existing OpenAI-compatible endpoint with a role-based
streaming interface that supports token-by-token delivery and tool call detection.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from .client import _run
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
    # Ollama OpenAI-compatible reasoning control. Never send native `think`/
    # `options.think` to /v1/chat/completions — only the OpenAI-style field.
    if config.runtime_kind == "ollama":
        payload["reasoning_effort"] = "medium" if think else "none"

    logger.info("STREAMING REQUEST: model=%s url=%s messages_count=%d temperature=%.1f tools=%s",
                chosen, config.url("chat/completions"), len(messages), temperature,
                "yes" if tools else "no")

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            config.url("chat/completions"),
            headers=config.headers,
            json=payload,
        ) as resp:
            resp.raise_for_status()
            logger.info("STREAMING RESPONSE: status=%d", resp.status_code)

            # Track tool_calls by index across SSE chunks
            tool_calls_buffer: dict[int, dict[str, Any]] = {}

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
                        elif finish_reason in ("stop", None):
                            # Reset buffer if stream ends without tool calls
                            tool_calls_buffer.clear()

                except json.JSONDecodeError:
                    logger.warning("Failed to parse SSE chunk: %s", data_str[:100])
                    continue


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
