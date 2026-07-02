"""Tests for MCP transport connection lifecycle.

Covers CRIT-002: TCPSocketTransport.connect() was defined but never called by
MCPClient.initialize(), so every production tool call (which goes through the
Rust TCP proxy) raised "Not connected to MCP proxy" and was silently caught,
leaving MCPClient permanently uninitialized.
"""
from __future__ import annotations

import asyncio

import pytest

from app.mcp.client import (
    InMemoryTransport,
    MCPClient,
    MCPTransport,
    TCPSocketTransport,
    create_mcp_client,
)


class TestTransportConnectContract:
    """The abstract MCPTransport.connect() default and override contract."""

    @pytest.mark.asyncio
    async def test_base_transport_connect_defaults_to_true(self):
        transport = MCPTransport()
        assert await transport.connect() is True

    @pytest.mark.asyncio
    async def test_in_memory_transport_connect_is_noop_success(self):
        transport = InMemoryTransport()
        assert await transport.connect() is True


class TestMCPClientInitializeCallsConnect:
    """MCPClient.initialize() must call transport.connect() before send()."""

    @pytest.mark.asyncio
    async def test_initialize_calls_connect_on_transport(self):
        calls = []

        class TrackingTransport(InMemoryTransport):
            async def connect(self):
                calls.append("connect")
                return await super().connect()

        transport = TrackingTransport()
        transport.register_handler("tools/list", lambda p: {"tools": []})
        client = MCPClient(transport)

        result = await client.initialize()

        assert result is True
        assert calls == ["connect"], "initialize() must call connect() exactly once before send()"

    @pytest.mark.asyncio
    async def test_initialize_fails_cleanly_when_connect_fails(self):
        class FailingTransport(InMemoryTransport):
            async def connect(self):
                return False

        transport = FailingTransport()
        client = MCPClient(transport)

        result = await client.initialize()

        assert result is False
        # call_tool must refuse to run against an uninitialized client
        with pytest.raises(RuntimeError, match="not initialized"):
            await client.call_tool("get_time", {})


class TestTCPSocketTransportConnect:
    """Exercise the real TCP transport against a loopback echo server."""

    @pytest.mark.asyncio
    async def test_connect_and_round_trip_over_real_socket(self):
        import json

        async def handle_conn(reader, writer):
            line = await reader.readline()
            request = json.loads(line.decode("utf-8"))
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {"tools": [{"name": "get_time"}]},
            }
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle_conn, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        try:
            transport = TCPSocketTransport(host="127.0.0.1", port=port)
            connected = await transport.connect()
            assert connected is True

            response = await transport.send({"method": "tools/list"})
            assert response["result"]["tools"][0]["name"] == "get_time"
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_connect_fails_gracefully_when_nothing_listening(self):
        # Port 1 is a well-known privileged/unused port unlikely to have a
        # listener in test environments; connection should fail, not hang.
        transport = TCPSocketTransport(host="127.0.0.1", port=1)
        connected = await transport.connect()
        assert connected is False

    @pytest.mark.asyncio
    async def test_mcp_client_initialize_over_real_tcp_proxy(self):
        """Full MCPClient.initialize() against a real socket — the exact path
        production uses when OBRENNA_MCP_PROXY_URL is set."""
        import json

        async def handle_conn(reader, writer):
            try:
                for _ in range(3):  # initialize, tools/list (during init), tools/list (explicit)
                    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                    if not line:
                        break
                    request = json.loads(line.decode("utf-8"))
                    method = request.get("method")
                    if method == "initialize":
                        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}
                    elif method == "tools/list":
                        result = {"tools": [{"name": "calculator"}]}
                    else:
                        result = {}
                    response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
                    writer.write((json.dumps(response) + "\n").encode("utf-8"))
                    await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle_conn, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        try:
            client = create_mcp_client(f"tcp://127.0.0.1:{port}")
            result = await asyncio.wait_for(client.initialize(), timeout=10.0)
            assert result is True

            tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
            assert tools[0]["name"] == "calculator"
        finally:
            await client.close()
            server.close()
            await server.wait_closed()
