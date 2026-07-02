"""Shared pytest fixtures for the backend test suite."""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_shared_singletons(monkeypatch):
    """Reset process-wide singletons and disable local-file sinks per test.

    - Disable the per-turn telemetry JSONL sink so the suite never pollutes
      ``backend/telemetry/``. Tests that exercise the sink opt back in by
      setting ``OBRENNA_TELEMETRY=on`` (plus a temp ``OBRENNA_TELEMETRY_DIR``).
    - Reset the shared model-runtime httpx client pool (Fix #3). Many streaming
      tests monkeypatch ``httpx.AsyncClient``; without a reset, the first test's
      fake client (with its exhausted SSE lines) would be cached and reused by
      later tests.
    """
    monkeypatch.setenv("OBRENNA_TELEMETRY", "off")
    from app.model_runtime import client_pool
    client_pool.reset_model_clients()
    # Reset the persistent MCP client manager (Fix #6) so a transport built in
    # one test (which may close over a test-local stubbed ``acall_tool``) is never
    # reused by a later test with different stubs.
    from app.mcp import client as mcp_client_mod
    mcp_client_mod.reset_mcp_manager()
    # Reset the version-keyed memory cache and the long-lived knowledge-pack
    # retriever singleton (Fix #7) so a cached MemoryContext or pooled sqlite3
    # connection from one test never leaks into another (different DB, different
    # pack set, different embedded vectors).
    from app.services import memory_cache, memory
    memory_cache.reset()
    memory.reset_knowledge_retriever()
