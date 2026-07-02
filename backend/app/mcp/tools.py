"""Initial MCP tools implementation.

Five tools: get_time, calculator, file_read, web_search, get_location.
Each tool is a standalone function that can be called by the MCP server process.
Supports both sync and async handlers.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "get_time",
        "description": (
            "Return the current local system date and time, including year, "
            "ISO date/datetime, weekday, timezone, and timezone offset."
        ),
        "is_read_only": True,
        "depends_on": [],
        "requires_user_prompt": False,
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "calculator",
        "description": (
            "Evaluate a sandboxed arithmetic expression. "
            "Supports +, -, *, /, **, %, parentheses, and decimal numbers. "
            "Never uses eval, exec, or code execution."
        ),
        "is_read_only": True,
        "depends_on": [],
        "requires_user_prompt": False,
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic expression to evaluate.",
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "file_read",
        "description": (
            "Read file contents by resolved file ID or allowlisted path. "
            "Rejects arbitrary absolute paths. Only accepts file IDs from the "
            "File table or paths in the user-surfaced allowlist."
        ),
        "is_read_only": True,
        "depends_on": [],
        "requires_user_prompt": False,
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The file ID from the File table.",
                },
                "path": {
                    "type": "string",
                    "description": "An allowlisted file path (alternative to file_id).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Return web search snippets with source URLs only. "
            "No full-page fetch. Returns an array of result objects."
        ),
        "is_read_only": True,
        "depends_on": [],
        "requires_user_prompt": False,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_location",
        "description": (
            "Return the current geographic location. "
            "Routes through Rust permission broker. "
            "Returns granted/denied/unavailable."
        ),
        # Sensitive + broker-routed → never gathered in parallel. The broker is
        # not actually wired today, so ``is_read_only=False`` plus the hard name
        # exclusion in handle_tool_calls keeps this strictly serial.
        "is_read_only": False,
        "depends_on": [],
        "requires_user_prompt": False,
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ── Tool implementations ─────────────────────────────────────────────────────


def tool_get_time(args: dict[str, Any]) -> dict[str, Any]:
    """Get local system time."""
    now = datetime.datetime.now().astimezone()
    utc_offset = now.strftime("%z")
    utc_offset_iso = utc_offset
    if len(utc_offset) == 5:
        utc_offset_iso = f"{utc_offset[:3]}:{utc_offset[3:]}"

    iso_datetime = now.isoformat()

    return {
        # Backward-compatible fields
        "time": iso_datetime,
        "timezone_offset": utc_offset,
        "unix_timestamp": int(now.timestamp()),
        # Extended dynamic fields for small-model grounding/tool responses
        "iso_datetime": iso_datetime,
        "human_readable": now.strftime("%A, %B %d, %Y at %I:%M %p"),
        "date": now.strftime("%Y-%m-%d"),
        "local_time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "year": now.year,
        "timezone": now.tzname() or "Local",
        "utc_offset": utc_offset_iso,
    }


def tool_calculator(args: dict[str, Any]) -> dict[str, Any]:
    """Sandboxed expression evaluator. No eval, exec, or AST."""
    expression = args.get("expression", "").strip()

    # Strict whitelist: only digits, operators, parentheses, decimals, whitespace
    if not re.match(r'^[\d\s\+\-\*\/\%\.\(\)]+$', expression):
        return {
            "error": True,
            "message": "Expression contains disallowed characters. Only numbers, +, -, *, /, %, parentheses, and dots are allowed.",
        }

    try:
        # Safe evaluation using only allowed operations
        result = _safe_eval_expression(expression)
        return {"result": result, "expression": expression}
    except ZeroDivisionError:
        return {"error": True, "message": "Division by zero"}
    except Exception as exc:
        return {"error": True, "message": f"Evaluation error: {exc}"}


def _safe_eval_expression(expr: str) -> float:
    """Safely evaluate an arithmetic expression without eval."""
    # Tokenize and parse using a simple recursive descent parser
    tokens = _tokenize(expr)
    pos = [0]  # mutable position tracker

    def parse_expr() -> float:
        result = parse_term()
        while pos[0] < len(tokens) and tokens[pos[0]] in ('+', '-'):
            op = tokens[pos[0]]
            pos[0] += 1
            right = parse_term()
            if op == '+':
                result += right
            else:
                result -= right
        return result

    def parse_term() -> float:
        result = parse_power()
        while pos[0] < len(tokens) and tokens[pos[0]] in ('*', '/', '%'):
            op = tokens[pos[0]]
            pos[0] += 1
            right = parse_power()
            if op == '*':
                result *= right
            elif op == '/':
                result /= right
            else:
                result %= right
        return result

    _MAX_EXPONENT = 1000  # generous for legitimate use, small enough to never hang/allocate

    def parse_power() -> float:
        base = parse_unary()
        if pos[0] < len(tokens) and tokens[pos[0]] == '**':
            pos[0] += 1
            exp = parse_unary()
            if abs(exp) > _MAX_EXPONENT:
                raise ValueError(f"Exponent magnitude too large (max {_MAX_EXPONENT})")
            return base ** exp
        return base

    def parse_unary() -> float:
        if pos[0] < len(tokens) and tokens[pos[0]] == '-':
            pos[0] += 1
            return -parse_unary()
        if pos[0] < len(tokens) and tokens[pos[0]] == '+':
            pos[0] += 1
            return parse_unary()
        return parse_primary()

    def parse_primary() -> float:
        if pos[0] >= len(tokens):
            raise ValueError("Unexpected end of expression")
        token = tokens[pos[0]]
        if token == '(':
            pos[0] += 1
            result = parse_expr()
            if pos[0] >= len(tokens) or tokens[pos[0]] != ')':
                raise ValueError("Mismatched parentheses")
            pos[0] += 1
            return result
        if isinstance(token, (int, float)):
            pos[0] += 1
            return float(token)
        raise ValueError(f"Unexpected token: {token}")

    result = parse_expr()
    if pos[0] != len(tokens):
        raise ValueError(f"Unexpected trailing token: {tokens[pos[0]]!r}")
    return result


def _tokenize(expr: str) -> list:
    """Tokenize arithmetic expression into numbers and operators."""
    tokens = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in '+-*/%()':
            tokens.append(ch)
            i += 1
        elif ch.isdigit() or ch == '.':
            start = i
            has_dot = ch == '.'
            i += 1
            while i < len(expr) and (expr[i].isdigit() or (expr[i] == '.' and not has_dot)):
                if expr[i] == '.':
                    has_dot = True
                i += 1
            num_str = expr[start:i]
            tokens.append(float(num_str) if has_dot else int(num_str))
        else:
            raise ValueError(f"Invalid character: {ch}")
    # Combine adjacent * into **
    result = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and tokens[i] == '*' and tokens[i + 1] == '*':
            result.append('**')
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result


def tool_file_read(args: dict[str, Any]) -> dict[str, Any]:
    """Read file by ID or allowlisted path."""
    file_id = args.get("file_id")
    path = args.get("path")

    if not file_id and not path:
        return {"error": True, "message": "Provide file_id or path."}

    if file_id:
        # Look up file in the database
        try:
            from ..app.db import get_db_session
            from ..app.models import File
            session = get_db_session()
            file_record = session.query(File).filter_by(id=file_id).first()
            if not file_record:
                session.close()
                return {"error": True, "message": f"File ID not found: {file_id}"}
            stored_path = file_record.stored_path
            session.close()
        except Exception as exc:
            logger.warning("File lookup failed: %s", exc)
            return {"error": True, "message": f"Database lookup failed: {exc}"}
    elif path:
        # Only allow paths in a configured allowlist
        allowlist = _get_path_allowlist()
        if path not in allowlist:
            return {
                "error": True,
                "message": f"Path not in allowlist: {path}",
            }
        stored_path = path
    else:
        return {"error": True, "message": "No file_id or path provided."}

    try:
        with open(stored_path, "r", errors="replace") as f:
            content = f.read(50_000)  # Cap at 50KB
        return {"content": content, "path": stored_path}
    except FileNotFoundError:
        return {"error": True, "message": f"File not found: {stored_path}"}
    except Exception as exc:
        return {"error": True, "message": f"Read error: {exc}"}


def _get_path_allowlist() -> list[str]:
    """Return the list of allowlisted file paths.

    In production, this would come from a config file or database.
    Phase 1: empty allowlist — only file_id lookups work.
    """
    return []


# ── Cached search provider singleton ─────────────────────────────────────────


_search_provider: Any = None


def _get_search_provider() -> Any:
    """Get (or create) the cached search provider singleton."""
    global _search_provider
    if _search_provider is None:
        try:
            from ..services.search import create_search_provider
            from ..services.architecture_config import get_services_config
            services_config = get_services_config()
            web_search_config = services_config.get("web_search", {})
            if not web_search_config:
                web_search_config = {
                    "provider": "duckduckgo",
                    "timeout_seconds": 10,
                    "cache_ttl_seconds": 300,
                }
            _search_provider = create_search_provider(web_search_config)
        except Exception as exc:
            logger.warning("Failed to initialize search provider: %s", exc)
            _search_provider = None
    return _search_provider


async def tool_web_search(args: dict[str, Any]) -> dict[str, Any]:
    """Web search — returns snippets and URLs only.

    Uses the configured search provider (DuckDuckGo by default).
    Supports Brave and SerpAPI via API keys.
    """
    query = args.get("query", "")
    max_results = min(args.get("max_results", 5), 10)  # capped

    if not query:
        return {"error": True, "message": "Query is required."}

    provider = _get_search_provider()
    if provider is None:
        return {
            "error": True,
            "message": "Search provider not initialized.",
            "results": [],
            "query": query,
            "count": 0,
        }

    try:
        result = await provider.search(query, max_results)
    except Exception as exc:
        logger.error("Web search failed: %s", exc)
        return {"error": True, "message": f"Search failed: {exc}", "results": [], "query": query, "count": 0}

    if result.error:
        return {"error": True, "message": result.error, "results": [], "query": query, "count": 0}

    return {
        "results": [
            {"title": r.title, "snippet": r.snippet, "url": r.url}
            for r in result.results
        ],
        "query": query,
        "count": len(result.results),
    }


def tool_get_location(args: dict[str, Any]) -> dict[str, Any]:
    """Get current location — routes through Rust permission broker.

    Phase 1: Returns denied/unavailable since we don't have
    full geo-location integration yet.
    """
    # In production, this would call the Rust permission broker
    # For phase 1, return unavailable
    return {
        "status": "unavailable",
        "message": "Location service not available in phase 1.",
        "latitude": None,
        "longitude": None,
    }


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS: dict[str, Any] = {
    "get_time": tool_get_time,
    "calculator": tool_calculator,
    "file_read": tool_file_read,
    "web_search": tool_web_search,
    "get_location": tool_get_location,
}


def list_tools() -> list[dict[str, Any]]:
    """Return the list of available tool definitions."""
    return TOOL_DEFS


# Index of TOOL_DEFS by name — built once at import time.
_TOOL_DEF_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOL_DEFS}


def tool_def_by_name(name: str) -> dict[str, Any] | None:
    """Return the canonical tool definition for ``name``, or ``None`` if unknown.

    ``TOOL_DEFS`` is the single source of truth for tool schemas (including
    ``inputSchema``). Callers building model-facing tool definitions must merge
    schemas through this helper rather than trusting allowlist entries (which
    intentionally carry only name/description/category).
    """
    return _TOOL_DEF_BY_NAME.get(name)


def tool_names() -> list[str]:
    """Return the sorted list of canonical tool names."""
    return sorted(_TOOL_DEF_BY_NAME)


def _validate_tool_args(name: str, args: Any) -> dict[str, Any] | None:
    """Validate ``args`` against the canonical TOOL_DEFS schema for ``name``.

    Returns ``None`` when valid, or a clean retryable error dict when the
    arguments don't match the schema (missing required, wrong type, etc.).
    This is especially important for prompt-JSON models, which may emit
    malformed arguments; a clear error lets the runtime ask the model to retry
    instead of crashing the tool call. Schemas are sourced from TOOL_DEFS via
    :func:`tool_def_by_name`.
    """
    canonical = tool_def_by_name(name)
    if canonical is None:
        return None  # no canonical schema — let the handler decide
    schema = canonical.get("inputSchema")
    if not schema:
        return None
    if not isinstance(args, dict):
        return {
            "error": True,
            "message": f"Tool '{name}' expects a JSON object of arguments.",
            "retryable": True,
        }
    required = schema.get("required", []) or []
    missing = [r for r in required if r not in args or args.get(r) is None]
    if missing:
        return {
            "error": True,
            "message": f"Missing required argument(s) for {name}: {', '.join(missing)}",
            "retryable": True,
        }
    try:
        import jsonschema
        jsonschema.validate(args, schema)
    except jsonschema.ValidationError as exc:
        return {
            "error": True,
            "message": f"Invalid arguments for {name}: {exc.message}",
            "retryable": True,
        }
    return None


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool by name with the given arguments (sync only).

    For async tools, this runs the event loop to completion.
    Prefer ``acall_tool`` for use inside async contexts.
    """
    handler = TOOLS.get(name)
    if not handler:
        return {"error": True, "message": f"Unknown tool: {name}"}

    schema_err = _validate_tool_args(name, args)
    if schema_err:
        return schema_err

    try:
        result = handler(args)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result
    except Exception as exc:
        logger.error("Tool '%s' failed: %s", name, exc)
        return {"error": True, "message": f"Tool execution error: {exc}"}


async def acall_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool by name with the given arguments (async).

    Handles both sync and async tool handlers.
    """
    handler = TOOLS.get(name)
    if not handler:
        return {"error": True, "message": f"Unknown tool: {name}"}

    schema_err = _validate_tool_args(name, args)
    if schema_err:
        return schema_err

    try:
        result = handler(args)
        if asyncio.iscoroutine(result):
            return await result
        # Sync handler — wrap in asyncio.to_thread for non-blocking
        if asyncio.iscoroutinefunction(handler):
            return await result
        return result
    except Exception as exc:
        logger.error("Tool '%s' failed: %s", name, exc)
        return {"error": True, "message": f"Tool execution error: {exc}"}


# ── MCP stdio server (for Rust-spawned process) ──────────────────────────────


def run_stdio_server() -> None:
    """Run the MCP tool server over stdio.

    Reads JSON-RPC requests from stdin, writes responses to stdout.
    This is the entry point when the MCP server is spawned as a separate process.
    """
    import sys

    def read_json_line() -> dict[str, Any] | None:
        line = sys.stdin.readline()
        if not line:
            return None
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            return None

    def write_response(obj: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    while True:
        request = read_json_line()
        if request is None:
            break

        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        try:
            if method == "initialize":
                write_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "obrenna-mcp", "version": "0.1.0"},
                    },
                })
            elif method == "tools/list":
                write_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": list_tools()},
                })
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                result = call_tool(tool_name, tool_args)
                content = [{"type": "text", "text": json.dumps(result)}]
                write_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": content, "isError": result.get("error", False)},
                })
            else:
                write_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })
        except Exception as exc:
            write_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            })


if __name__ == "__main__":
    run_stdio_server()
