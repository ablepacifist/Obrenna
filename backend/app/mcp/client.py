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
