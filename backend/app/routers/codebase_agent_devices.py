"""Approve/deny/list codebase-agent devices that have connected."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CodebaseAgentDevice
from ..schemas.api import CodebaseAgentDeviceDTO
from ..ws.codebase_agent_hub import get_codebase_agent_hub

router = APIRouter(prefix="/api/codebase-agent-devices", tags=["codebase-agent-devices"])
logger = logging.getLogger(__name__)


def _to_dto(device: CodebaseAgentDevice) -> CodebaseAgentDeviceDTO:
    return CodebaseAgentDeviceDTO(
        id=device.id,
        device_id=device.device_id,
        name=device.name,
        approved=device.approved,
        enabled=device.enabled,
        connected=get_codebase_agent_hub().is_connected(device.device_id),
        created_at=device.created_at.isoformat(),
        last_seen_at=device.last_seen_at.isoformat(),
    )


@router.get("", response_model=list[CodebaseAgentDeviceDTO])
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(CodebaseAgentDevice).order_by(CodebaseAgentDevice.created_at.desc()).all()
    return [_to_dto(d) for d in devices]


@router.post("/{device_row_id}/approve", response_model=CodebaseAgentDeviceDTO)
def approve_device(device_row_id: str, db: Session = Depends(get_db)):
    device = db.get(CodebaseAgentDevice, device_row_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.approved = True
    db.commit()
    db.refresh(device)
    return _to_dto(device)


@router.delete("/{device_row_id}")
async def delete_device(device_row_id: str, db: Session = Depends(get_db)):
    device = db.get(CodebaseAgentDevice, device_row_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    hub = get_codebase_agent_hub()
    conn = hub.get(device.device_id)
    if conn is not None:
        hub.unregister(device.device_id, conn)
        try:
            await conn.websocket.close()
        except Exception:
            logger.warning("Could not close socket for removed device %s", device.device_id)
    db.delete(device)
    db.commit()
    return {"deleted": True, "device_row_id": device_row_id}
