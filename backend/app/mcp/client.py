"""MCP client boundary in Python.

Provides a transport-agnostic MCP client that:
- Currently connects to Rust's loopback TCP proxy (stdio relay)
- Can later support direct stdio or HTTP/SSE registrations

Exposes list_tools() and call_tool(name, args) to the agent runtime only.
Does NOT expose worker spawning as an MCP tool.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPTransport:
    """Abstract transport for MCP JSON-RPC communication.

    Currently supports loopback TCP (Rust proxy).
    Can be extended for direct stdio or HTTP/SSE later.
    """

    async def connect(self) -> bool:
        """Establish the underlying connection, if any. Returns True on success.

        Default no-op for transports (like InMemoryTransport) that need no
        connection setup. Transports requiring a real connection (TCP) must
        override this and actually establish it before ``send`` is usable.
        """
        return True

    async def send(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send an MCP JSON-RPC request and return the response."""
        raise NotImplementedError

    def is_connected(self) -> bool:
        """Whether the underlying connection is currently usable.

        Default True for connectionless transports (e.g. InMemoryTransport).
        Transports owning a real socket must override this so the
        ``MCPClientManager`` can decide whether to reuse or reconnect.
        """
        return True

    async def close(self) -> None:
        """Close the transport connection."""
        pass


class TCPSocketTransport(MCPTransport):
    """Loopback TCP transport for Rust MCP proxy."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._next_id: int = 1

    async def connect(self) -> bool:
        """Connect to the MCP proxy. Returns True on success."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5.0,
            )
            return True
        except Exception as exc:
            logger.warning("MCP proxy connection failed at %s:%d: %s", self.host, self.port, exc)
            return False

    async def send(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request over TCP and await response."""
        if not self._writer or not self._reader:
            raise RuntimeError("Not connected to MCP proxy")

        request["jsonrpc"] = "2.0"
        request["id"] = self._next_id
        req_id = self._next_id
        self._next_id += 1

        payload = json.dumps(request) + "\n"
        self._writer.write(payload.encode("utf-8"))
        await self._writer.drain()

        # Read response line
        try:
            response_line = await asyncio.wait_for(
                self._reader.readline(), timeout=30.0
            )
            if not response_line:
                raise RuntimeError("MCP proxy closed connection")
            response = json.loads(response_line.decode("utf-8"))
            return response
        except asyncio.TimeoutError:
            raise RuntimeError("MCP proxy request timed out")

    def is_connected(self) -> bool:
        # A TCP transport is usable only while the writer is open and not
        # already closing. ``_writer`` is None after close() or before a
        # successful connect().
        return self._writer is not None and not self._writer.is_closing()

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None


class InMemoryTransport(MCPTransport):
    """In-memory transport for testing without a real MCP server.

    Routes calls to registered handler functions.
    Supports both sync and async handlers.
    """

    def __init__(self):
        self._handlers: dict[str, Any] = {}
        self._next_id: int = 1

    def register_handler(self, method: str, handler: Any) -> None:
        """Register a handler for an MCP method."""
        self._handlers[method] = handler

    async def send(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request.get("method", "")
        handler = self._handlers.get(method)
        if handler:
            params = request.get("params", {})
            result = handler(params)
            if asyncio.iscoroutine(result):
                result = await result
            elif asyncio.iscoroutinefunction(handler):
                result = await result
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}


class MCPClient:
    """MCP client with transport abstraction.

    Usage:
        client = MCPClient(transport)
        await client.initialize()
        tools = await client.list_tools()
        result = await client.call_tool("calculator", {"expression": "2+2"})
    """

    def __init__(self, transport: MCPTransport):
        self.transport = transport
        self._initialized = False
        self._tool_names: list[str] = []

    async def initialize(self) -> bool:
        """Initialize the MCP connection."""
        try:
            connected = await self.transport.connect()
            if not connected:
                logger.warning("MCP transport connect() failed; not initializing.")
                return False
            response = await self.transport.send({
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                },
            })
            self._initialized = True
            # Discover tools
            await self._notify_tools_list_changed()
            return True
        except Exception as exc:
            logger.warning("MCP initialization failed: %s", exc)
            return False

    async def _notify_tools_list_changed(self) -> None:
        """Request tool list after initialization."""
        try:
            resp = await self.transport.send({
                "method": "tools/list",
            })
            tools_data = resp.get("result", {}).get("tools", [])
            self._tool_names = [t.get("name", "") for t in tools_data if t.get("name")]
        except Exception:
            pass

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available MCP tools."""
        try:
            response = await self.transport.send({"method": "tools/list"})
            return response.get("result", {}).get("tools", [])
        except Exception as exc:
            logger.warning("MCP list_tools failed: %s", exc)
            return []

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Call an MCP tool by name.

        Args:
            name: Tool name (e.g. "calculator", "file_read").
            args: Tool arguments dict.

        Returns:
            Tool result (parsed from MCP response).
        """
        if not self._initialized:
            raise RuntimeError("MCP client not initialized. Call initialize() first.")

        try:
            response = await self.transport.send({
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": args or {},
                },
            })
            content = response.get("result", {}).get("content", [])
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict):
                    return first.get("text", str(content))
                return str(content)
            return content
        except Exception as exc:
            raise RuntimeError(f"MCP tool call failed: {exc}") from exc

    async def close(self) -> None:
        """Close the MCP transport."""
        await self.transport.close()


def create_mcp_client(proxy_url: str | None = None) -> MCPClient:
    """Create an MCP client with the appropriate transport.

    Uses loopback TCP transport when proxy_url is provided,
    or in-memory transport for testing.
    """
    if proxy_url:
        import re
        match = re.match(r"(?:tcp://)?(127\.0\.0\.1|localhost):(\d+)", proxy_url)
        if match:
            host = match.group(1)
            port = int(match.group(2))
            transport = TCPSocketTransport(host=host, port=port)
            return MCPClient(transport)

    # Fallback: in-memory transport for testing/dev
    return MCPClient(InMemoryTransport())


def make_tcp_transport_factory(proxy_url: str):
    """Return a zero-arg factory building a TCP transport for ``proxy_url``.

    Used by ``MCPClientManager`` so it can (re)build a fresh transport on
    reconnect without the caller having to re-parse the proxy URL each turn.
    """
    import re

    def _factory() -> MCPTransport:
        match = re.match(r"(?:tcp://)?(127\.0\.0\.1|localhost):(\d+)", proxy_url)
        if match:
            host = match.group(1)
            port = int(match.group(2))
            return TCPSocketTransport(host=host, port=port)
        return InMemoryTransport()

    return _factory


class MCPClientManager:
    """Process-wide manager of persistent MCP client connections (Fix #6).

    Previously the runtime built a fresh ``MCPClient`` and ran the full
    ``initialize()`` handshake (which sends ``initialize`` + ``tools/list``)
    every chat turn. This manager holds one client per ``server_id`` for the
    process lifetime, so the handshake happens once and ``tools/list`` is
    cached. On a dropped connection it transparently reconnects (with limited
    backoff) using the transport factory supplied at first connect.

    Only one MCP server exists today (the Rust-spawned ``obrenna-mcp``), so the
    default ``server_id`` is ``"obrenna-mcp"``. Multi-server routing is a
    future concern; the dict-keyed design accommodates it without change.

    Boundary: this manager owns connection lifecycle and capability discovery
    only. It contains no orchestration logic.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tools_cache: dict[str, list[dict[str, Any]]] = {}
        self._factories: dict[str, Any] = {}  # server_id -> transport factory
        self._lock = asyncio.Lock()

    async def connect(
        self,
        server_id: str,
        transport_factory: Any,
        *,
        max_retries: int = 3,
    ) -> MCPClient:
        """Return a healthy, initialised client for ``server_id``.

        Reuses the existing client when its transport is still connected;
        otherwise (re)builds via ``transport_factory`` and runs the handshake.
        On handshake failure, retries with bounded backoff before giving up.
        """
        async with self._lock:
            existing = self._clients.get(server_id)
            if existing is not None and existing.transport.is_connected():
                return existing

            # Drop any stale client before (re)building.
            if existing is not None:
                try:
                    await existing.close()
                except Exception:
                    pass
                self._clients.pop(server_id, None)
                self._tools_cache.pop(server_id, None)

            self._factories[server_id] = transport_factory
            client = await self._build_with_retry(
                server_id, transport_factory, max_retries
            )
            self._clients[server_id] = client
            # Cache the tool list once so callers never re-send tools/list.
            try:
                self._tools_cache[server_id] = await client.list_tools()
            except Exception as exc:
                logger.warning("MCP initial tools/list failed for %s: %s", server_id, exc)
                self._tools_cache[server_id] = []
            return client

    async def _build_with_retry(
        self, server_id: str, transport_factory: Any, max_retries: int
    ) -> MCPClient:
        delays = [0.0, 0.2, 0.5, 1.0]  # bounded backoff (seconds)
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            transport = transport_factory()
            client = MCPClient(transport)
            try:
                ok = await client.initialize()
                if ok:
                    return client
                last_exc = RuntimeError("MCP initialize() returned False")
            except Exception as exc:  # noqa: BLE001 - reconnect on any failure
                last_exc = exc
                try:
                    await client.close()
                except Exception:
                    pass
            if attempt < max_retries:
                delay = delays[min(attempt + 1, len(delays) - 1)]
                if delay:
                    await asyncio.sleep(delay)
        raise RuntimeError(
            f"MCP client for {server_id} failed to connect after "
            f"{max_retries + 1} attempts: {last_exc}"
        )

    async def get_tools(self, server_id: str) -> list[dict[str, Any]]:
        """Return the cached tool list for ``server_id`` (no wire round trip)."""
        if server_id in self._tools_cache:
            return self._tools_cache[server_id]
        client = self._clients.get(server_id)
        if client is None:
            return []
        tools = await client.list_tools()
        self._tools_cache[server_id] = tools
        return tools

    async def invalidate(self, server_id: str) -> None:
        """Drop the cached client + tool list; next ``connect()`` rebuilds."""
        async with self._lock:
            self._tools_cache.pop(server_id, None)
            client = self._clients.pop(server_id, None)
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass

    async def shutdown(self) -> None:
        """Close every managed client. Safe to call multiple times."""
        async with self._lock:
            for client in self._clients.values():
                try:
                    await client.close()
                except Exception:
                    pass
            self._clients.clear()
            self._tools_cache.clear()
            self._factories.clear()


# Module-level singleton.
_mcp_manager: MCPClientManager | None = None


def get_mcp_manager() -> MCPClientManager:
    """Return the process-wide MCP client manager singleton."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPClientManager()
    return _mcp_manager


def reset_mcp_manager() -> None:
    """Drop the singleton (tests only). Does not close clients."""
    global _mcp_manager
    _mcp_manager = None
