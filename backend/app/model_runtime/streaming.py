"""Streaming model runtime client.

Provides async streaming generation for the agent runtime.
Wraps the existing OpenAI-compatible endpoint with a role-based
streaming interface that supports token-by-token delivery.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import httpx

from .client import _run
from .config import RuntimeConfig

logger = logging.getLogger(__name__)

DEFAULT_STREAM_TIMEOUT = 60.0


async def chat_completion_stream(
    config: RuntimeConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    role: str = "main_reasoner",
    temperature: float = 0.2,
    timeout: float = DEFAULT_STREAM_TIMEOUT,
    stop: list[str] | None = None,
) -> AsyncIterator[str]:
    """Stream tokens from an OpenAI-compatible endpoint.

    Yields text tokens as they arrive from the server.
    Never yields CoT/thinking content — the caller is expected
    to filter <think> blocks before passing messages to the model.
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

    logger.info("STREAMING REQUEST: model=%s url=%s messages_count=%d temperature=%.1f", chosen, config.url("chat/completions"), len(messages), temperature)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            config.url("chat/completions"),
            headers=config.headers,
            json=payload,
        ) as resp:
            resp.raise_for_status()
            logger.info("STREAMING RESPONSE: status=%d", resp.status_code)
            buffer = ""
            async for line in resp.aiter_lines():
                if not line or line == "data: [DONE]":
                    continue
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]  # strip "data: " prefix
                if not data_str.strip():
                    continue
                try:
                    import json
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    logger.warning("Failed to parse SSE chunk: %s", data_str[:100])
                    continue


# ── Sync wrapper for use from sync contexts ──────────────────────────────────


async def _collect_stream(config, messages, *, model=None, role="main_reasoner",
                          temperature=0.2, timeout=DEFAULT_STREAM_TIMEOUT):
    """Collect all tokens from the stream into a single string."""
    chunks = []
    async for token in chat_completion_stream(
        config, messages, model=model, role=role,
        temperature=temperature, timeout=timeout,
    ):
        chunks.append(token)
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
