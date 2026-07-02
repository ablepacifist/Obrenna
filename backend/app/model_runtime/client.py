"""Thin httpx client for any OpenAI-compatible endpoint (Ollama, LM Studio, llama.cpp, vLLM).

We never hardcode a cloud provider. The base_url comes from user settings and points
at a local server.
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import logging
import threading
import time

from .client_pool import get_model_client
from .config import RuntimeConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class _SyncAsyncRunner:
    """Run sync-entry async work on one long-lived event loop.

    Sync FastAPI routes previously used ``asyncio.run`` per request, creating a
    fresh event loop for each chat turn. That conflicts with long-lived async
    resources such as httpx pools and MCP locks. A single background loop gives
    sync callers stable loop ownership without nesting inside Uvicorn's loop.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def run(self, coro):
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._thread_main,
                name="obrenna-async-runtime",
                daemon=True,
            )
            self._thread.start()
            self._ready.wait(timeout=5.0)
            if self._loop is None or not self._loop.is_running():
                raise RuntimeError("Async runtime loop failed to start")
            return self._loop

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    def stop(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        from .client_pool import close_model_client

        close_future = asyncio.run_coroutine_threadsafe(close_model_client(), loop)
        try:
            close_future.result(timeout=5.0)
        except Exception:
            logger.debug("Async runtime client close failed", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None


_sync_async_runner = _SyncAsyncRunner()
atexit.register(_sync_async_runner.stop)


def _run(coro):
    """Run an async coroutine from sync code on the shared runtime loop."""
    try:
        asyncio.get_running_loop()
        running = True
    except RuntimeError:
        running = False

    if not running:
        return _sync_async_runner.run(coro)

    # Already inside a running loop — block in a worker thread to avoid nesting
    # while still using the same shared runtime loop underneath.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_sync_async_runner.run, coro)
        return future.result()


async def list_models(config: RuntimeConfig, timeout: float = 10.0) -> list[str]:
    client = get_model_client()
    resp = await client.get(config.url("models"), headers=config.headers, timeout=timeout)
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
    client = get_model_client()
    resp = await client.post(
        config.url("chat/completions"), headers=config.headers, json=payload, timeout=timeout
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    # DEBUG, not INFO: model response content is private local content.
    logger.debug("SYNC RESPONSE: status=%d content=%r", resp.status_code, content)
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
