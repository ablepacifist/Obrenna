"""Dynamic dispatch for user-defined custom API tools.

Unlike the built-in tools in mcp/tools.py, custom tools are DB-backed and are
dispatched directly from runtime.py's handle_tool_calls, before it would
otherwise reach mcp_client.call_tool() — the packaged app's Rust MCP binary
has no database access, so wiring this in at the mcp/tools.py layer would
silently no-op there. See runtime.py's handle_tool_calls for the interception
point.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..db import SessionLocal
from ..models import CustomTool

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_CHARS = 50_000


def _input_schema_from_params(params: list[dict[str, Any]]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in params or []:
        properties[p["name"]] = {
            "type": p.get("type", "string"),
            "description": p.get("description", ""),
        }
        if p.get("required"):
            required.append(p["name"])
    return {"type": "object", "properties": properties, "required": required}


def list_enabled_custom_tool_defs() -> list[dict[str, Any]]:
    """Build TOOL_DEFS-shaped entries for every enabled custom tool.

    Uses a fresh session rather than a request-scoped one — the request's db
    session is deliberately rolled back before this point in orchestrate_turn
    so SQLite doesn't hold a lock during generation.
    """
    db = SessionLocal()
    try:
        rows = db.query(CustomTool).filter(CustomTool.enabled.is_(True)).all()
        return [
            {
                "name": row.name,
                "description": row.description,
                "is_read_only": row.http_method.upper() in ("GET", "HEAD"),
                "depends_on": [],
                "requires_user_prompt": False,
                "inputSchema": _input_schema_from_params(row.params or []),
            }
            for row in rows
        ]
    finally:
        db.close()


def get_custom_tool_by_name(name: str) -> CustomTool | None:
    db = SessionLocal()
    try:
        return (
            db.query(CustomTool)
            .filter(CustomTool.name == name, CustomTool.enabled.is_(True))
            .first()
        )
    finally:
        db.close()


def _missing_required(params: list[dict[str, Any]], args: dict[str, Any]) -> list[str]:
    return [p["name"] for p in params if p.get("required") and p["name"] not in args]


async def call_custom_tool(tool: CustomTool, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a custom API tool call.

    Never includes tool.headers in the returned dict (success or error path)
    — trace_logging logs this return value verbatim, and headers may carry
    configured API keys.
    """
    params: list[dict[str, Any]] = tool.params or []
    args = args or {}

    missing = _missing_required(params, args)
    if missing:
        return {
            "error": True,
            "message": f"Missing required parameter(s): {', '.join(missing)}",
            "retryable": True,
        }

    known_names = {p["name"] for p in params}
    query_params: dict[str, Any] = {}
    body: dict[str, Any] = {}
    for p in params:
        if p["name"] in args:
            target = body if p.get("location") == "body" else query_params
            target[p["name"]] = args[p["name"]]
    # Extra args the model supplied but weren't declared default to query.
    for key, value in args.items():
        if key not in known_names:
            query_params[key] = value

    try:
        async with httpx.AsyncClient(timeout=TOOL_TIMEOUT_SECONDS) as client:
            resp = await client.request(
                tool.http_method.upper(),
                tool.base_url,
                params=query_params or None,
                json=body or None,
                headers=tool.headers or None,
            )
    except httpx.HTTPError as exc:
        return {"error": True, "message": f"Request failed: {exc}"}

    try:
        content = json.dumps(resp.json())
    except ValueError:
        content = resp.text
    if len(content) > MAX_RESPONSE_CHARS:
        content = content[:MAX_RESPONSE_CHARS] + "... [truncated]"

    if resp.status_code >= 400:
        return {"error": True, "message": f"Request failed with status {resp.status_code}", "body": content}
    return {"result": content}
