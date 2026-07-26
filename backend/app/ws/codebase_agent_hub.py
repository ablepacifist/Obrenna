"""In-memory registry of live codebase-agent WebSocket connections.

Mirrors MCPClientManager's role (backend/app/mcp/client.py) but for the
inbound side: agents dial into Obrenna and hold the connection open; this hub
tracks the live connections and correlates outbound commands with their
eventual replies via per-request futures (not sequential-blocking, since
read-only codebase tool calls can be dispatched concurrently within a single
turn -- see runtime.py's _is_gather_eligible/asyncio.gather).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0


class DeviceConnection:
    def __init__(self, device_id: str, websocket: WebSocket):
        self.device_id = device_id
        self.websocket = websocket
        self._pending: dict[str, asyncio.Future] = {}

    async def send_command(
        self, op: str, params: dict[str, Any], timeout: float = DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        try:
            await self.websocket.send_text(json.dumps({"id": request_id, "op": op, "params": params}))
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise ConnectionError(f"Failed to send command to device: {exc}") from exc
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device did not respond in time for '{op}'")
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, payload: dict[str, Any]) -> None:
        fut = self._pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(payload)

    def fail_all(self, error: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(error)
        self._pending.clear()


class CodebaseAgentHub:
    def __init__(self) -> None:
        self._connections: dict[str, DeviceConnection] = {}

    def get(self, device_id: str) -> DeviceConnection | None:
        return self._connections.get(device_id)

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connections

    async def register(self, device_id: str, websocket: WebSocket) -> DeviceConnection:
        existing = self._connections.get(device_id)
        if existing is not None:
            logger.warning("Replacing existing connection for device %s (last-connect-wins)", device_id)
            existing.fail_all(ConnectionError("Superseded by a new connection from the same device"))
            try:
                await existing.websocket.close()
            except Exception:
                pass
        conn = DeviceConnection(device_id, websocket)
        self._connections[device_id] = conn
        return conn

    def unregister(self, device_id: str, connection: DeviceConnection) -> None:
        # Only remove if this is still the most-recent registration -- avoids a
        # stale disconnect handler clobbering a newer connection for the same device.
        if self._connections.get(device_id) is connection:
            connection.fail_all(ConnectionError("Device disconnected"))
            del self._connections[device_id]


_hub = CodebaseAgentHub()


def get_codebase_agent_hub() -> CodebaseAgentHub:
    return _hub
