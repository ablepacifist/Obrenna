"""WebSocket endpoint codebase-agent companions dial into.

The agent (not Obrenna) initiates this connection -- see docs/plan for why:
Obrenna is reachable at a stable address, the agent's machine usually isn't.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..db import SessionLocal
from ..models import CodebaseAgentDevice
from ..ws.codebase_agent_hub import get_codebase_agent_hub

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_PENDING_DEVICES = 20
PENDING_EXPIRY = timedelta(hours=24)


def _prune_stale_pending(db) -> None:
    cutoff = datetime.now(timezone.utc) - PENDING_EXPIRY
    stale = (
        db.query(CodebaseAgentDevice)
        .filter(CodebaseAgentDevice.approved.is_(False), CodebaseAgentDevice.last_seen_at < cutoff)
        .all()
    )
    for row in stale:
        db.delete(row)
    if stale:
        db.commit()


def _upsert_device(db, device_id: str, name: str) -> tuple[CodebaseAgentDevice | None, str | None]:
    """Returns (device, error). error is set (device is None) if the pending cap is hit."""
    _prune_stale_pending(db)

    existing = db.query(CodebaseAgentDevice).filter(CodebaseAgentDevice.device_id == device_id).first()
    if existing is not None:
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.name = name or existing.name
        db.commit()
        db.refresh(existing)
        return existing, None

    pending_count = db.query(CodebaseAgentDevice).filter(CodebaseAgentDevice.approved.is_(False)).count()
    if pending_count >= MAX_PENDING_DEVICES:
        return None, "Too many devices awaiting approval -- try again later or approve/deny existing ones."

    device = CodebaseAgentDevice(device_id=device_id, name=name or "Unnamed device")
    db.add(device)
    db.commit()
    db.refresh(device)
    return device, None


@router.websocket("/api/codebase-agent/connect")
async def codebase_agent_connect(websocket: WebSocket):
    await websocket.accept()
    hub = get_codebase_agent_hub()

    try:
        raw = await websocket.receive_text()
        hello = json.loads(raw)
    except (WebSocketDisconnect, ValueError):
        await websocket.close(code=1002, reason="Expected a hello frame")
        return

    device_id = hello.get("device_id")
    device_name = hello.get("device_name", "")
    if hello.get("type") != "hello" or not device_id:
        await websocket.close(code=1002, reason="Invalid hello frame")
        return

    db = SessionLocal()
    try:
        device, error = _upsert_device(db, device_id, device_name)
    finally:
        db.close()

    if device is None:
        await websocket.send_text(json.dumps({"type": "hello_ack", "error": error}))
        await websocket.close(code=1013, reason=error)
        return

    conn = await hub.register(device_id, websocket)
    # An agent older than the backend sends no op list. Recorded as None, which
    # means "unknown" — the tool layer then offers only the ops every version
    # has ever had, rather than advertising one that comes back as
    # "Unknown operation" and reads to the model as an impossible task.
    ops = hello.get("ops")
    conn.supported_ops = set(ops) if isinstance(ops, list) else None
    await websocket.send_text(json.dumps({"type": "hello_ack", "approved": device.approved}))
    logger.info("codebase-agent device connected: %s (%s), approved=%s", device_name, device_id, device.approved)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            request_id = msg.get("id")
            if request_id:
                conn.resolve(request_id, msg.get("result", {}))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(device_id, conn)
        logger.info("codebase-agent device disconnected: %s (%s)", device_name, device_id)
