"""Tests for the persistent MCP client manager (Fix #6)."""
import asyncio
import json

import pytest

from app.mcp.client import (
    InMemoryTransport,
    MCPClient,
    MCPClientManager,
)


class _CountingTransport(InMemoryTransport):
    """In-memory transport that counts tools/list sends."""

    def __init__(self):
        super().__init__()
        self.tools_list_calls = 0
        self.connect_calls = 0

    async def connect(self):
        self.connect_calls += 1
        return await super().connect()

    async def send(self, request):
        if request.get("method") == "tools/list":
            self.tools_list_calls += 1
        return await super().send(request)


def _factory_for(transport: _CountingTransport):
    return lambda: transport


@pytest.mark.asyncio
async def test_connect_is_idempotent_reuses_same_client():
    mgr = MCPClientManager()
    transport = _CountingTransport()
    transport.register_handler("tools/list", lambda p: {"tools": [{"name": "get_time"}]})
    factory = _factory_for(transport)

    a = await mgr.connect("obrenna-mcp", factory)
    b = await mgr.connect("obrenna-mcp", factory)

    assert a is b, "second connect() must return the cached client"
    # Only one initialize handshake (one connect + one tools/list during init).
    assert transport.connect_calls == 1


@pytest.mark.asyncio
async def test_get_tools_returns_cache_without_resending_tools_list():
    mgr = MCPClientManager()
    transport = _CountingTransport()
    transport.register_handler("tools/list", lambda p: {"tools": [{"name": "calculator"}]})
    factory = _factory_for(transport)

    await mgr.connect("obrenna-mcp", factory)
    after_init = transport.tools_list_calls
    assert after_init >= 1, "initialize must send tools/list once"

    tools = await mgr.get_tools("obrenna-mcp")
    assert tools and tools[0]["name"] == "calculator"
    # get_tools must NOT issue another tools/list.
    assert transport.tools_list_calls == after_init


@pytest.mark.asyncio
async def test_invalidate_drops_cache_so_next_connect_rebuilds():
    mgr = MCPClientManager()
    transport = _CountingTransport()
    transport.register_handler("tools/list", lambda p: {"tools": [{"name": "get_time"}]})
    factory = _factory_for(transport)

    first = await mgr.connect("obrenna-mcp", factory)
    await mgr.invalidate("obrenna-mcp")
    second = await mgr.connect("obrenna-mcp", factory)

    assert first is not second, "invalidate must force a fresh client"
    # The first client's transport was connected again after invalidate.
    assert transport.connect_calls == 2


@pytest.mark.asyncio
async def test_get_tools_unknown_server_returns_empty():
    mgr = MCPClientManager()
    assert await mgr.get_tools("no-such-server") == []


@pytest.mark.asyncio
async def test_shutdown_closes_clients_and_is_idempotent():
    mgr = MCPClientManager()
    transport = _CountingTransport()
    transport.register_handler("tools/list", lambda p: {"tools": []})
    await mgr.connect("obrenna-mcp", _factory_for(transport))

    await mgr.shutdown()
    await mgr.shutdown()  # must not raise
    assert mgr._clients == {}


@pytest.mark.asyncio
async def test_reconnects_when_transport_reports_disconnected():
    # Simulate a dropped TCP connection: the cached client's transport reports
    # is_connected() False, so connect() must rebuild a fresh client.
    mgr = MCPClientManager()

    class _DropAfterFirstUse(_CountingTransport):
        def __init__(self):
            super().__init__()
            self._dropped = False

        def is_connected(self):
            return not self._dropped

        def drop(self):
            self._dropped = True

    transport = _DropAfterFirstUse()
    transport.register_handler("tools/list", lambda p: {"tools": []})
    factory = _factory_for(transport)

    first = await mgr.connect("obrenna-mcp", factory)
    transport.drop()  # simulate the broker closing the connection
    second = await mgr.connect("obrenna-mcp", factory)

    assert first is not second
    assert transport.connect_calls == 2, "a dropped transport must trigger a reconnect handshake"