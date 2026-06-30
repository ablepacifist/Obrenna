"""Initial MCP tools implementation.

Five tools: get_time, calculator, file_read, web_search, get_location.
Each tool is a standalone function that can be called by the MCP server process.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFS = [
    {
        "name": "get_time",
        "description": "Return the current local system time and timezone offset.",
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
    now = datetime.datetime.now()
    utc_offset = now.astimezone().strftime("%z")
    return {
        "time": now.isoformat(),
        "timezone_offset": utc_offset,
        "unix_timestamp": int(now.timestamp()),
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

    def parse_power() -> float:
        base = parse_unary()
        if pos[0] < len(tokens) and tokens[pos[0]] == '**':
            pos[0] += 1
            exp = parse_unary()
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

    return parse_expr()


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


def tool_web_search(args: dict[str, Any]) -> dict[str, Any]:
    """Web search — returns snippets and URLs only."""
    query = args.get("query", "")
    max_results = args.get("max_results", 5)

    if not query:
        return {"error": True, "message": "Query is required."}

    # Phase 1: Return placeholder results
    # Full web search integration comes later
    return {
        "results": [
            {
                "title": f"Search results for: {query}",
                "snippet": f"Web search for '{query}' will be available in a future update.",
                "url": f"https://www.google.com/search?q={query.replace(' ', '+')}",
            }
        ],
        "query": query,
        "count": 1,
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


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool by name with the given arguments."""
    handler = TOOLS.get(name)
    if not handler:
        return {"error": True, "message": f"Unknown tool: {name}"}

    try:
        result = handler(args)
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
