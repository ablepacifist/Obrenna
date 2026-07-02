"""Tests for the shared model-runtime httpx client pool (Fix #3)."""
import asyncio

import httpx
import pytest

from app.model_runtime.client import _run
from app.model_runtime import client_pool
from app.model_runtime.client_pool import close_model_client, get_model_client


@pytest.mark.asyncio
async def test_get_model_client_returns_singleton():
    # Reset to a known state (the autouse conftest fixture also does this).
    client_pool.reset_model_clients()
    a = get_model_client()
    b = get_model_client()
    assert a is b
    assert isinstance(a, httpx.AsyncClient)


@pytest.mark.asyncio
async def test_close_resets_singleton_so_next_call_is_new_instance():
    client_pool.reset_model_clients()
    first = get_model_client()
    await close_model_client()
    assert client_pool._model_client is None
    second = get_model_client()
    assert first is not second


@pytest.mark.asyncio
async def test_close_is_idempotent_when_no_client_exists():
    client_pool.reset_model_clients()
    # Closing when nothing is open must not raise.
    await close_model_client()
    await close_model_client()


@pytest.mark.asyncio
async def test_close_is_idempotent_after_real_close():
    client_pool.reset_model_clients()
    get_model_client()
    await close_model_client()
    # A second close after the real close must not raise.
    await close_model_client()
    assert client_pool._model_client is None


@pytest.mark.asyncio
async def test_model_client_is_event_loop_local(monkeypatch):
    """Async clients must never be shared across event loops."""
    client_pool.reset_model_clients()
    created = []

    class FakeAsyncClient:
        is_closed = False

        def __init__(self, *args, **kwargs):
            created.append(self)

        async def aclose(self):
            self.is_closed = True

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    main_loop_client = get_model_client()

    def create_on_other_loop():
        async def inner():
            return get_model_client()

        return asyncio.run(inner())

    other_loop_client = await asyncio.to_thread(create_on_other_loop)

    assert main_loop_client is not other_loop_client
    assert len(created) == 2
    await close_model_client()


def test_sync_run_reuses_stable_background_event_loop():
    async def current_loop_id():
        return id(asyncio.get_running_loop())

    first = _run(current_loop_id())
    second = _run(current_loop_id())

    assert first == second
