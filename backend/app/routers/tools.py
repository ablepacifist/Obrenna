"""MCP tools discovery endpoint.

Returns the list of allowed tool definitions from the architecture config.
The frontend uses this to render tool-specific UI elements.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter

from ..mcp.tools import list_tools, TOOLS
from ..services.architecture_config import get_mcp_tools_config, get_services_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp-tools"])


@router.get("/tools")
def get_tools() -> list[dict]:
    """Return the list of allowed tool definitions from config."""
    config = get_mcp_tools_config()
    allowed = config.get("allowed", [])
    # Enrich with availability info
    result = []
    for t in allowed:
        name = t.get("name", "")
        tool_info = {
            "name": name,
            "description": t.get("description", ""),
            "category": t.get("category", "utility"),
            "requires_permission": t.get("requires_permission", False),
            "available": name in TOOLS,
        }
        # Check if web_search has a configured provider
        if name == "web_search":
            services = get_services_config()
            ws_config = services.get("web_search", {})
            provider = ws_config.get("provider", "duckduckgo")
            tool_info["provider"] = provider
            if provider == "brave" and not os.environ.get("BRAVE_SEARCH_API_KEY"):
                tool_info["available"] = False
                tool_info["error"] = "Brave Search API key not configured"
            elif provider == "serpapi" and not os.environ.get("SERPAPI_API_KEY"):
                tool_info["available"] = False
                tool_info["error"] = "SerpAPI key not configured"
        result.append(tool_info)
    return result


@router.get("/tools/{tool_name}/status")
def get_tool_status(tool_name: str) -> dict:
    """Check if a specific tool is available."""
    if tool_name not in TOOLS:
        return {"available": False, "error": f"Unknown tool: {tool_name}"}
    return {"available": True, "tool_name": tool_name}
