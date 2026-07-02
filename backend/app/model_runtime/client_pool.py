"""App-scoped shared ``httpx.AsyncClient`` for model runtime HTTP calls.

Fix #3: previously every model call opened a fresh ``httpx.AsyncClient`` inside
its function body (``async with httpx.AsyncClient(...)``), paying a full
connection-pool + TLS handshake per request. This module holds one process-wide
client singleton that all call sites reuse.

Lifecycle:
- The client is created lazily on first use (so importing this module is cheap
  and never opens a connection at import time).
- It must be closed on shutdown. ``close_model_client()`` is registered in BOTH
  the FastAPI lifespan (``backend/main.py``) AND the Python stdout sidecar's
  ``finally`` block — the agent runtime runs as a sidecar with no FastAPI
  lifespan, so the sidecar entry point must tear it down itself.

Per-request timeouts are honoured by passing ``timeout=`` to ``.post()`` /
``.stream()`` (httpx accepts per-request overrides); the client itself is
constructed with a generous default timeout so a forgotten per-request value
never hangs forever.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# A generous default so a call site that forgets to pass ``timeout=`` does not
# hang indefinitely; per-request ``timeout=`` overrides this where needed.
_DEFAULT_CLIENT_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)

_model_client: Optional[httpx.AsyncClient] = None  # legacy alias for tests/diagnostics
_model_clients: dict[int, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def get_model_client() -> httpx.AsyncClient:
    """Return the shared async HTTP client for the current event loop.

    ``httpx.AsyncClient`` owns asyncio primitives inside its transport/pool. It
    is therefore not safe to create it on Uvicorn's loop (for async status
    polling) and later reuse it on the chat orchestration loop. Keep one client
    per running loop instead of one process-global client.
    """
    global _model_client
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    existing = _model_clients.get(loop_id)
    if existing is not None:
        _loop, client = existing
        if not getattr(client, "is_closed", False):
            _model_client = client
            return client

    # ``getattr`` default keeps this robust to test fakes that don't expose
    # ``is_closed`` (the real httpx.AsyncClient does).
    client = httpx.AsyncClient(
        timeout=_DEFAULT_CLIENT_TIMEOUT,
        limits=_DEFAULT_LIMITS,
    )
    _model_clients[loop_id] = (loop, client)
    _model_client = client
    logger.debug("Created model httpx.AsyncClient for event loop %s", loop_id)
    return _model_client


async def close_model_client() -> None:
    """Close all loop-owned clients if open. Safe to call multiple times."""
    global _model_client
    current_loop = asyncio.get_running_loop()
    pending = []
    for loop_id, (loop, client) in list(_model_clients.items()):
        if getattr(client, "is_closed", False):
            continue
        if loop is current_loop:
            pending.append(client.aclose())
        elif loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(client.aclose(), loop)
            pending.append(asyncio.wrap_future(fut))
        else:
            logger.debug("Dropping model client for non-running event loop %s", loop_id)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    _model_clients.clear()
    _model_client = None


def reset_model_clients() -> None:
    """Reset client registry for tests after they close/replace event loops."""
    global _model_client
    _model_clients.clear()
    _model_client = None
