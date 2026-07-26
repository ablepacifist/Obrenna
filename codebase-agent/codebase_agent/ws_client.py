"""WebSocket client: dials into Obrenna and dispatches incoming commands.

The agent initiates this connection -- Obrenna is reachable at a stable
address, this machine usually isn't. Reconnects with backoff on drop.

Inbound command frames are each handled in their own task (not awaited
inline in the receive loop) and the actual filesystem work runs via
asyncio.to_thread, so one slow operation never blocks Obrenna's other,
concurrent requests to this same device.
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

from .auth import default_device_name, get_or_create_device_id
from .dispatch import dispatch

logger = logging.getLogger(__name__)

RECONNECT_BACKOFF = [1, 2, 5, 10, 15, 30]


def _ws_url(server: str) -> str:
    server = server.strip()
    if server.startswith("https://"):
        server = "wss://" + server[len("https://"):]
    elif server.startswith("http://"):
        server = "ws://" + server[len("http://"):]
    elif not server.startswith(("ws://", "wss://")):
        server = "ws://" + server
    return server.rstrip("/") + "/api/codebase-agent/connect"


async def _handle_command(ws, raw: str, send_lock: asyncio.Lock) -> None:
    try:
        msg = json.loads(raw)
    except ValueError:
        return
    request_id = msg.get("id")
    op = msg.get("op")
    if not request_id or not op:
        return
    result = await asyncio.to_thread(dispatch, op, msg.get("params", {}))
    # Nested, not spread: a result dict (e.g. register_project's) can itself
    # contain an "id" key, which would silently clobber the correlation id
    # above if merged flat into the same envelope.
    payload = json.dumps({"id": request_id, "result": result})
    async with send_lock:
        await ws.send(payload)


async def _run_once(server: str, device_id: str, device_name: str) -> None:
    url = _ws_url(server)
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": device_id, "device_name": device_name}))
        ack = json.loads(await ws.recv())
        if ack.get("approved"):
            print(f"Connected to {server} -- approved and ready.")
        else:
            print(f"Connected to {server} -- waiting for approval in Obrenna's settings (device: {device_name}).")

        send_lock = asyncio.Lock()
        async for raw in ws:
            asyncio.create_task(_handle_command(ws, raw, send_lock))


async def run(server: str, name: str | None = None) -> None:
    device_id = get_or_create_device_id()
    device_name = name or default_device_name()
    print(f"Codebase agent starting. Device: {device_name} ({device_id})")

    attempt = 0
    while True:
        try:
            await _run_once(server, device_id, device_name)
            attempt = 0  # clean session before the drop resets backoff
        except (websockets.exceptions.WebSocketException, OSError) as exc:
            logger.warning("Connection to %s lost/failed: %s", server, exc)
        delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
        attempt += 1
        print(f"Reconnecting in {delay}s...")
        await asyncio.sleep(delay)
