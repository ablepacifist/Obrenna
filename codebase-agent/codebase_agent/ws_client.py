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
import os
import sys

import websockets

from .auth import default_device_name, get_or_create_device_id
from .dispatch import dispatch, supported_ops

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


async def _run_once(server: str, device_id: str, device_name: str, token: str = "") -> None:
    url = _ws_url(server)
    # Sent as a header, never in the URL: a token in the query string ends up
    # in access logs, proxy logs and shell history. Harmless when connecting
    # straight to the backend (nothing reads it there); required when the
    # public gateway is in the path, since it is what stands in for the
    # browser login cookie the agent cannot obtain.
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with websockets.connect(url, additional_headers=headers) as ws:
        # The op list travels with the hello so the backend never offers the
        # model a tool this agent cannot perform. Without it, an agent older
        # than the backend answers a new tool with "Unknown operation: X" --
        # which the model reads as the task being impossible, not as a version
        # skew, and abandons the approach.
        await ws.send(json.dumps({
            "type": "hello",
            "device_id": device_id,
            "device_name": device_name,
            "ops": supported_ops(),
            # So the backend can tell the model which shell its commands land
            # in. Without it a model on a Windows device spends rounds
            # discovering that wc, grep and Get-ChildItem are not there.
            "platform": "windows" if os.name == "nt" else sys.platform,
        }))
        ack = json.loads(await ws.recv())
        if ack.get("approved"):
            print(f"Connected to {server} -- approved and ready.")
        else:
            print(f"Connected to {server} -- waiting for approval in Obrenna's settings (device: {device_name}).")

        send_lock = asyncio.Lock()
        async for raw in ws:
            asyncio.create_task(_handle_command(ws, raw, send_lock))


def _explain_rejection(exc: Exception, server: str, has_token: bool) -> str | None:
    """Turn an auth rejection into something actionable.

    A 401 from the gateway surfaces as a bare handshake error, which reads like
    a network fault and sends people looking at firewalls. It is almost always
    a token problem, so say so.
    """
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status not in (401, 403):
        return None
    if not has_token:
        return (
            f"{server} refused the connection ({status}): it is behind the login "
            "gateway, which needs a token.\n"
            "  Pass --token <secret> (or set OBRENNA_AGENT_TOKEN) with the value "
            "of OBRENNA_AGENT_TOKEN on the machine running Obrenna.\n"
            "  Connecting straight to the backend instead (LAN/localhost) needs "
            "no token."
        )
    return (
        f"{server} rejected the token ({status}). It must match OBRENNA_AGENT_TOKEN "
        "on the machine running Obrenna exactly.\n"
        "  If that variable is unset or under 32 characters there, the gateway "
        "refuses every agent by design -- check the gateway's logs."
    )


async def run(server: str, name: str | None = None, token: str = "") -> None:
    device_id = get_or_create_device_id()
    device_name = name or default_device_name()
    print(f"Codebase agent starting. Device: {device_name} ({device_id})")

    attempt = 0
    while True:
        try:
            await _run_once(server, device_id, device_name, token)
            attempt = 0  # clean session before the drop resets backoff
        except (websockets.exceptions.WebSocketException, OSError) as exc:
            hint = _explain_rejection(exc, server, bool(token))
            if hint:
                # Config error, not a transient drop -- printed every attempt
                # so it can't scroll past unnoticed in a reconnect loop.
                print(f"\n{hint}\n")
            else:
                logger.warning("Connection to %s lost/failed: %s", server, exc)
        delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
        attempt += 1
        print(f"Reconnecting in {delay}s...")
        await asyncio.sleep(delay)
