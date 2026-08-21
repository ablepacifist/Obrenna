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

# Ops that have existed since the first released agent. An agent whose hello
# carries no op list predates capability reporting, so this is what it can be
# assumed to support.
LEGACY_OPS = frozenset({
    "register_project", "update_project", "delete_project",
    "list_directory", "read_file", "search",
    "edit_file", "write_file", "delete_file", "move_file",
    "run_command", "list_changes", "revert_change",
})


class DeviceConnection:
    def __init__(self, device_id: str, websocket: WebSocket):
        self.device_id = device_id
        self.websocket = websocket
        self._pending: dict[str, asyncio.Future] = {}
        # Requests we stopped waiting for. Kept so a late reply is recognised as
        # late rather than silently dropped as unknown.
        self._abandoned: set[str] = set()
        # Ops this agent build can perform, from its hello frame. None means an
        # agent too old to say, which is treated as "only the original ops".
        self.supported_ops: set[str] | None = None
        # "windows", "linux", "darwin", or None from an agent too old to say.
        self.platform: str | None = None

    def shell_hint(self) -> str:
        """One line telling the model which shell its commands land in.

        A model with no idea reaches for POSIX tools by default and burns a
        round each on `wc`, `grep`, and `Get-ChildItem` before finding
        something that exists.
        """
        if self.platform == "windows":
            return (
                " THIS MACHINE IS WINDOWS and commands run through cmd.exe, not bash or "
                "PowerShell. For anything that counts, filters or aggregates, write a "
                "`python -c \"...\"` one-liner and let it do the work — that is the reliable "
                "route and it returns the finished answer, not a list for you to tally by "
                "hand. POSIX tools (wc, grep, sed, head, which, unix find) and PowerShell "
                "cmdlets (Get-ChildItem) do NOT exist here; dir, findstr and where do."
            )
        if self.platform in ("linux", "darwin"):
            return " Commands run through /bin/sh on a Unix machine."
        return ""

    def supports(self, op: str) -> bool:
        """Whether this device can perform ``op``.

        Unknown (an agent predating capability reporting) is answered from the
        set every released agent has always had, so a stale agent silently
        loses only the new tools instead of erroring on them mid-turn.
        """
        if self.supported_ops is None:
            return op in LEGACY_OPS
        return op in self.supported_ops

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
            self._abandoned.add(request_id)
            # Say what actually happened. The command was delivered and is very
            # likely still running on the user's machine -- calling that "no
            # response" invites the model to run a mutating command a second
            # time while the first one is mid-flight.
            raise ConnectionError(
                f"No reply from the device within {timeout:.0f}s for '{op}'. The command was "
                "delivered and may still be running there. Do not simply repeat it -- check "
                "whether it already took effect, or run it again with a longer timeout."
            )
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, payload: dict[str, Any]) -> None:
        fut = self._pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(payload)
        elif request_id in self._abandoned:
            # The reply arrived after we gave up. Nothing can consume it now,
            # but it must not vanish without trace: this is the signature of a
            # timeout set too tight, and the only place it is observable.
            self._abandoned.discard(request_id)
            logger.warning(
                "codebase-agent %s replied to request %s after it timed out; "
                "the command completed but its output was discarded",
                self.device_id, request_id,
            )

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
