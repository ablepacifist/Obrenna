"""CRUD for user-defined custom API tools."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..mcp.tools import tool_names
from ..models import CustomTool

ALLOWED_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
READ_ONLY_METHODS = {"GET", "HEAD"}


def _validate(
    db: Session,
    *,
    name: str,
    http_method: str,
    params: list[dict[str, Any]],
    exclude_id: str | None = None,
) -> Optional[str]:
    """Return an error message, or None if valid."""
    method = http_method.upper()
    if method not in ALLOWED_METHODS:
        return f"Unsupported HTTP method: {http_method}"

    if method in READ_ONLY_METHODS and any(p.get("location") == "body" for p in params):
        return f"{method} requests cannot have body parameters"

    if name in tool_names():
        return f"'{name}' collides with a built-in tool name"

    query = db.query(CustomTool).filter(CustomTool.name == name)
    if exclude_id:
        query = query.filter(CustomTool.id != exclude_id)
    if query.first() is not None:
        return f"A custom tool named '{name}' already exists"

    return None


def list_custom_tools(db: Session) -> list[CustomTool]:
    return db.query(CustomTool).order_by(CustomTool.created_at.desc()).all()


def create_custom_tool(db: Session, payload: dict[str, Any]) -> tuple[Optional[CustomTool], Optional[str]]:
    error = _validate(
        db,
        name=payload["name"],
        http_method=payload.get("http_method", "GET"),
        params=payload.get("params", []),
    )
    if error:
        return None, error

    tool = CustomTool(
        name=payload["name"],
        description=payload["description"],
        base_url=payload["base_url"],
        http_method=payload.get("http_method", "GET").upper(),
        headers=payload.get("headers", {}),
        params=payload.get("params", []),
        enabled=payload.get("enabled", True),
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool, None


def update_custom_tool(
    db: Session, tool_id: str, payload: dict[str, Any]
) -> tuple[Optional[CustomTool], Optional[str]]:
    tool = db.get(CustomTool, tool_id)
    if not tool:
        return None, "Custom tool not found"

    name = payload.get("name", tool.name)
    http_method = payload.get("http_method", tool.http_method)
    params = payload.get("params", tool.params)

    error = _validate(db, name=name, http_method=http_method, params=params, exclude_id=tool_id)
    if error:
        return None, error

    tool.name = name
    tool.description = payload.get("description", tool.description)
    tool.base_url = payload.get("base_url", tool.base_url)
    tool.http_method = http_method.upper()
    tool.headers = payload.get("headers", tool.headers)
    tool.params = params
    tool.enabled = payload.get("enabled", tool.enabled)
    db.commit()
    db.refresh(tool)
    return tool, None


def delete_custom_tool(db: Session, tool_id: str) -> bool:
    tool = db.get(CustomTool, tool_id)
    if not tool:
        return False
    db.delete(tool)
    db.commit()
    return True
