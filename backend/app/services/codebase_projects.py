"""CRUD for codebase-agent project pairings.

Obrenna is a thin registry here -- the connected companion agent is the
actual authority on path validation and write-enablement, so every
create/update round-trips to it over its live WebSocket connection (see
app/ws/codebase_agent_hub.py) rather than trusting a locally-cached copy.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..models import CodebaseAgentDevice, CodebaseProject
from ..ws.codebase_agent_hub import get_codebase_agent_hub

logger = logging.getLogger(__name__)


def _get_connected_approved_device(db, device_id: str) -> tuple[Optional[CodebaseAgentDevice], Optional[str]]:
    device = db.query(CodebaseAgentDevice).filter(CodebaseAgentDevice.device_id == device_id).first()
    if device is None:
        return None, "Device not found"
    if not device.approved or not device.enabled:
        return None, "Device is not approved yet -- approve it first."
    conn = get_codebase_agent_hub().get(device_id)
    if conn is None:
        return None, "This device is not currently connected."
    return device, None


def list_codebase_projects(db) -> list[CodebaseProject]:
    return db.query(CodebaseProject).order_by(CodebaseProject.created_at.desc()).all()


async def create_codebase_project(db, payload: dict[str, Any]) -> tuple[Optional[CodebaseProject], Optional[str]]:
    name = payload["name"]
    device_id = payload["device_id"]

    if db.query(CodebaseProject).filter(CodebaseProject.name == name).first() is not None:
        return None, f"A project named '{name}' already exists"

    device, error = _get_connected_approved_device(db, device_id)
    if device is None:
        return None, error

    conn = get_codebase_agent_hub().get(device_id)
    try:
        remote = await conn.send_command(
            "register_project",
            {"name": name, "root_path": payload["root_path"], "write_enabled": payload.get("write_enabled", False)},
        )
    except ConnectionError as exc:
        return None, f"Could not reach the codebase agent: {exc}"

    if remote.get("error"):
        return None, str(remote.get("message", remote))

    project = CodebaseProject(
        name=name,
        device_id=device_id,
        root_path=remote["root_path"],
        remote_project_id=remote["id"],
        write_enabled=remote["write_enabled"],
        enabled=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project, None


async def update_codebase_project(db, project_id: str, payload: dict[str, Any]) -> tuple[Optional[CodebaseProject], Optional[str]]:
    project = db.get(CodebaseProject, project_id)
    if not project:
        return None, "Codebase project not found"

    remote_updates: dict[str, Any] = {}
    if payload.get("name") is not None:
        remote_updates["name"] = payload["name"]
    if payload.get("write_enabled") is not None:
        remote_updates["write_enabled"] = payload["write_enabled"]

    if remote_updates:
        conn = get_codebase_agent_hub().get(project.device_id)
        if conn is None:
            return None, "This device is not currently connected."
        try:
            remote = await conn.send_command(
                "update_project", {"project_id": project.remote_project_id, **remote_updates}
            )
        except ConnectionError as exc:
            return None, f"Could not reach the codebase agent: {exc}"
        if remote.get("error"):
            return None, str(remote.get("message", remote))

    if "name" in remote_updates:
        project.name = remote_updates["name"]
    if "write_enabled" in remote_updates:
        project.write_enabled = remote_updates["write_enabled"]
    if payload.get("enabled") is not None:
        project.enabled = payload["enabled"]

    db.commit()
    db.refresh(project)
    return project, None


async def delete_codebase_project(db, project_id: str) -> bool:
    project = db.get(CodebaseProject, project_id)
    if not project:
        return False

    conn = get_codebase_agent_hub().get(project.device_id)
    if conn is not None:
        try:
            await conn.send_command("delete_project", {"project_id": project.remote_project_id})
        except ConnectionError:
            logger.warning("Could not unregister project on device %s (removing locally anyway)", project.device_id)

    db.delete(project)
    db.commit()
    return True
