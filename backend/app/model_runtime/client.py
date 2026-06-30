"""Thin httpx client for any OpenAI-compatible endpoint (Ollama, LM Studio, llama.cpp, vLLM).

We never hardcode a cloud provider. The base_url comes from user settings and points
at a local server.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .config import RuntimeConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


def _run(coro):
    """Run an async coroutine in a fresh event loop (safe for sync callers)."""
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False

    if not running:
        return asyncio.run(coro)

    # Already inside a running loop — run in a worker thread to avoid nesting.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


async def list_models(config: RuntimeConfig, timeout: float = 10.0) -> list[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(config.url("models"), headers=config.headers)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    out: list[str] = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(it.get("id") or it.get("name") or "")
        elif isinstance(it, str):
            out.append(it)
    return [m for m in out if m]


async def test_connection(config: RuntimeConfig) -> dict:
    """Return {ok, models, latency_ms, error}. Never raises."""
    start = time.perf_counter()
    try:
        models = await list_models(config)
        latency = int((time.perf_counter() - start) * 1000)
        return {"ok": True, "models": models, "latency_ms": latency, "error": None}
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
        latency = int((time.perf_counter() - start) * 1000)
        return {"ok": False, "models": [], "latency_ms": latency, "error": str(exc)}


async def chat_completion(
    config: RuntimeConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    role: str = "main_reasoner",
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    chosen = model or config.model_for(role)
    if not chosen:
        raise ValueError("No model configured for this request.")
    payload = {"model": chosen, "messages": messages, "temperature": temperature}
    logger.info("SYNC REQUEST: model=%s url=%s messages_count=%d temperature=%.1f", chosen, config.url("chat/completions"), len(messages), temperature)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            config.url("chat/completions"), headers=config.headers, json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        logger.info("SYNC RESPONSE: status=%d content=%r", resp.status_code, content)
    return content


# ── sync wrappers for use from sync FastAPI routes ─────────────────────────────


def chat_completion_sync(
    config: RuntimeConfig,
    messages: list[dict],
    *,
    model: str | None = None,
    role: str = "main_reasoner",
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Synchronous wrapper around chat_completion for use in sync routes."""
    return _run(
        chat_completion(
            config, messages, model=model, role=role,
            temperature=temperature, timeout=timeout,
        )
    )


def test_connection_sync(config: RuntimeConfig) -> dict:
    """Synchronous wrapper around test_connection for use in sync routes."""
    return _run(test_connection(config))
