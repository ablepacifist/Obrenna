"""Dynamic dispatch for codebase-agent tools, scoped to whichever
CodebaseProject is bound to the current chat.

Like custom_tool_dispatch.py, these are DB-backed and dispatched directly
from runtime.py's handle_tool_calls rather than through mcp_client.call_tool
-- the packaged app's Rust MCP binary has no network/DB access, so wiring
this in at the mcp/tools.py layer would silently no-op there.

Commands are sent over the live WebSocket connection the agent dialed in
with (see app/ws/codebase_agent_hub.py) -- Obrenna never calls out to the
agent. Device approval is re-checked fresh from the DB on every dispatch,
never cached, so revoking a device takes effect immediately.

Read-before-write is enforced HERE, not by the model and not by the
companion agent: an in-memory ledger (chat_id, path) -> content_hash is
populated on every successful read, and edit_file calls fail with a
retryable error if there's no ledger entry -- so a confused model
self-corrects in the existing tool-call retry loop instead of blindly
overwriting a file it never looked at.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Optional

from ..db import SessionLocal
from ..models import Chat, CodebaseAgentDevice, CodebaseProject
from ..ws.codebase_agent_hub import DeviceConnection, get_codebase_agent_hub

logger = logging.getLogger(__name__)

# (chat_id, project_id, relative_path) -> content_hash. In-memory only --
# resets on backend restart, which just means "read it again first", never
# a safety hole.
_read_ledger: dict[tuple[str, str, str], str] = {}
_ledger_lock = threading.Lock()

_OP_BY_TOOL_NAME = {
    "codebase_list_directory": "list_directory",
    "codebase_read_file": "read_file",
    "codebase_search": "search",
    "codebase_edit_file": "edit_file",
    "codebase_write_file": "write_file",
    "codebase_delete_file": "delete_file",
    "codebase_move_file": "move_file",
    "codebase_run_command": "run_command",
}

# Tools that can change the user's files. These are what "manual" mode gates
# behind per-call approval and what "plan" mode refuses outright.
# ``run_command`` is included because a shell command can do anything a write
# tool can (and more), so exempting it would make manual mode meaningless.
MUTATING_CODEBASE_TOOLS = frozenset({
    "codebase_edit_file",
    "codebase_write_file",
    "codebase_delete_file",
    "codebase_move_file",
    "codebase_run_command",
})


def is_mutating_tool(tool_name: str) -> bool:
    """True if ``tool_name`` can modify the connected project."""
    return tool_name in MUTATING_CODEBASE_TOOLS


def get_active_codebase_project(chat_id: str) -> Optional[CodebaseProject]:
    db = SessionLocal()
    try:
        chat = db.get(Chat, chat_id)
        if not chat or not chat.active_codebase_project_id:
            return None
        project = db.get(CodebaseProject, chat.active_codebase_project_id)
        if not project or not project.enabled:
            return None
        return project
    finally:
        db.close()


def _coerce_int(value: Any, *, default: int, low: int, high: int) -> int:
    """Clamp a model-supplied number, never raise.

    A model that passes timeout="fast" used to raise ValueError from outside the
    guarded block, so the turn's tool result became a bare "Tool error: invalid
    literal for int()" string -- unparseable, and therefore invisible to the
    failure detection that would otherwise stop it retrying.
    """
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def list_enabled_codebase_tool_defs(chat_id: str) -> list[dict[str, Any]]:
    project = get_active_codebase_project(chat_id)
    if project is None:
        return []

    defs = [
        {
            "name": "codebase_list_directory",
            "description": (
                f"List files and subdirectories in the '{project.name}' codebase. "
                "Common dependency/build directories (node_modules, .git, venv, "
                "__pycache__, dist, build) are already excluded."
            ),
            "is_read_only": True,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to the project root. Defaults to the root.", "default": "."},
                    "recursive": {"type": "boolean", "description": "List subdirectories recursively.", "default": False},
                },
                "required": [],
            },
        },
        {
            "name": "codebase_read_file",
            "description": (
                f"Read a file from the '{project.name}' codebase, with line numbers. "
                "You must read a file with this tool before you can edit it."
            ),
            "is_read_only": True,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the project root."},
                    "offset": {"type": "integer", "description": "Line number to start reading from (0-indexed).", "default": 0},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read."},
                },
                "required": ["path"],
            },
        },
        {
            "name": "codebase_search",
            "description": (
                f"Search every file in the '{project.name}' codebase for a pattern. This is how "
                "you find where something is defined or used. Matches are case-insensitive and "
                "come back with the file path, the line number, and a few lines of surrounding "
                "code so you can tell a definition from a call site. Hidden and gitignored files "
                "(including .env) are searched too. Up to 100 matches are returned; the result "
                "says how many files were looked at and whether it hit that limit. "
                "IMPORTANT: an empty result does NOT mean the thing does not exist. Before you "
                "say something is missing, search again for a shorter or partial name (search "
                "'get_db_conn', not 'get_db_connection(conn, opts)'), try regex=false to match "
                "the text literally, and list or read the directory you expect it in. Say which "
                "of those you tried."
            ),
            "is_read_only": True,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text or regular expression to search for. Prefer a short distinctive fragment (a function name) over a long exact line."},
                    "path": {"type": "string", "description": "Directory to search within, relative to the project root.", "default": "."},
                    "regex": {"type": "boolean", "description": "Treat pattern as a regular expression. Set false to match the text literally, which is what you want for patterns containing ( ) [ ] . $ or |.", "default": True},
                    "context": {"type": "integer", "description": "Lines of surrounding code to include with each match.", "default": 2},
                },
                "required": ["pattern"],
            },
        },
    ]

    if project.write_enabled:
        defs.append({
            "name": "codebase_edit_file",
            "description": (
                f"Edit an existing file in the '{project.name}' codebase by replacing an exact "
                "snippet of text (old_string) with new text (new_string). old_string must match "
                "EXACTLY ONE location in the file -- include enough surrounding context to make "
                "it unique, or set replace_all=true to replace every occurrence. You must have "
                "read this file with codebase_read_file first in this conversation. There is no "
                "whole-file overwrite tool -- for a large rewrite, do NOT pass the entire old "
                "file as old_string and the entire new file as new_string in one call; that "
                "argument is too large to reliably format and will fail. Instead make several "
                "smaller, targeted edit_file calls, one section/paragraph at a time, each with "
                "just enough surrounding context to be unique."
            ),
            "is_read_only": False,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the project root."},
                    "old_string": {"type": "string", "description": "The exact text to replace."},
                    "new_string": {"type": "string", "description": "The text to replace it with."},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence instead of requiring a unique match.", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        })
        defs.append({
            "name": "codebase_write_file",
            "description": (
                f"Create a brand-new file in the '{project.name}' codebase. Fails if the file "
                "already exists -- use codebase_edit_file to modify an existing file. "
                "A path with no directory (e.g. 'README.md') creates the file at the project root. "
                "Keep the content CONCISE on the first write; you can extend the file afterwards "
                "with codebase_edit_file. Very long content is likely to fail to format."
            ),
            "is_read_only": False,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the project root."},
                    "content": {"type": "string", "description": "The full content of the new file."},
                },
                "required": ["path", "content"],
            },
        })
        defs.append({
            "name": "codebase_delete_file",
            "description": (
                f"Delete a single file from the '{project.name}' codebase (a backup is kept, so "
                "it can be reverted). Use this to remove a file that is duplicated, misplaced, "
                "or no longer needed. This is the ONLY way to delete a file -- do not try to "
                "empty a file with codebase_edit_file instead."
            ),
            "is_read_only": False,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the project root."},
                },
                "required": ["path"],
            },
        })
        defs.append({
            "name": "codebase_move_file",
            "description": (
                f"Move or rename a file within the '{project.name}' codebase. Fails if the "
                "destination already exists. Use this to relocate a file instead of copying "
                "its content with write_file and deleting the original."
            ),
            "is_read_only": False,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Current file path relative to the project root."},
                    "new_path": {"type": "string", "description": "New file path relative to the project root."},
                },
                "required": ["path", "new_path"],
            },
        })
        defs.append({
            "name": "codebase_run_command",
            "description": (
                f"Run a shell command inside the '{project.name}' project on the connected "
                "machine — install dependencies, run a script, run tests, build. Returns "
                "exit_code, stdout, and stderr. This is how you BUILD and RUN code: after "
                "writing files, actually run them to prove they work, then read the output "
                "and fix any error before telling the user it's done. exit_code 0 means "
                "success; a non-zero exit_code or content in stderr means it failed — do not "
                "claim success in that case. Use non-interactive commands that exit on their "
                "own (e.g. 'python main.py', 'npm test', 'npm run build'); never start a "
                "long-running server or a command that waits for input, as it will just time "
                "out. Commands run from the project root unless you set cwd. "
                "The project's own .env / .Renviron is ALREADY loaded into the environment, so "
                "its database credentials and hostnames are present: call the project's existing "
                "connection helper (e.g. Rscript -e \"source('shared/db_helpers.R'); "
                "con <- get_db_connection(); ...\" or python -c \"import db; ...\") and it will "
                "connect. Never invent a connection string, never ask the user for a password, "
                "and never print credentials to stdout."
            ),
            "is_read_only": False,
            "depends_on": [],
            "requires_user_prompt": False,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run, e.g. 'python main.py' or 'npm install'."},
                    "cwd": {"type": "string", "description": "Directory to run in, relative to the project root. Defaults to the root.", "default": "."},
                    "timeout": {"type": "integer", "description": "Max seconds to allow before the command is killed (default 120, max 600).", "default": 120},
                },
                "required": ["command"],
            },
        })

    return defs


def _ledger_key(chat_id: str, project_id: str, path: str) -> tuple[str, str, str]:
    return (chat_id, project_id, path)


# A markdown code fence wrapping the ENTIRE content: ```lang\n...\n``` . Models
# habitually wrap code in fences even when asked to write a raw file, which then
# gets written literally into the .py/.js/etc. file and breaks it (a created
# tic_tac_toe.py started with a literal "```python" line -> SyntaxError). Strip
# a fence ONLY when it wraps the whole string, so a real markdown file (prose +
# multiple embedded blocks) is never touched.
_WRAPPING_FENCE_RE = re.compile(r'^\s*```[^\n]*\r?\n(.*?)\r?\n?```\s*$', re.DOTALL)


def _strip_wrapping_code_fence(content: str) -> str:
    if not isinstance(content, str):
        return content
    m = _WRAPPING_FENCE_RE.match(content)
    return m.group(1) if m else content


def _get_connected_approved_device(device_id: str) -> tuple[Optional[DeviceConnection], Optional[str]]:
    """Fresh DB check every call -- a revoked device stops working immediately."""
    db = SessionLocal()
    try:
        device = db.query(CodebaseAgentDevice).filter(CodebaseAgentDevice.device_id == device_id).first()
    finally:
        db.close()

    if device is None or not device.approved or not device.enabled:
        return None, "This device is no longer approved. Re-pair it in Obrenna's settings."

    conn = get_codebase_agent_hub().get(device_id)
    if conn is None:
        return None, "The codebase agent for this project is not currently connected."
    return conn, None


async def call_codebase_tool(chat_id: str, project: CodebaseProject, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    op = _OP_BY_TOOL_NAME.get(tool_name)
    if op is None:
        return {"error": True, "message": f"Unknown codebase tool: {tool_name}"}

    conn, error = _get_connected_approved_device(project.device_id)
    if conn is None:
        return {"error": True, "message": error}

    # Treat an empty/missing path as the project root. Models very commonly call
    # list_directory/search with path="" to mean "the whole project"; the agent
    # rejects "" as "Invalid path", which fails their first exploratory call and
    # derails the turn. ``or "."`` normalizes ""/None → root. (read/edit/write
    # always carry a real path; an empty one there still fails meaningfully.)
    path = args.get("path") or "."
    params: dict[str, Any] = {"project_id": project.remote_project_id}

    if op == "list_directory":
        params.update(path=path, recursive=bool(args.get("recursive", False)))

    elif op == "read_file":
        params.update(path=path, offset=args.get("offset", 0))
        if args.get("limit") is not None:
            params["limit"] = args["limit"]

    elif op == "search":
        params.update(pattern=args["pattern"], path=path, regex=bool(args.get("regex", True)))
        if args.get("context") is not None:
            params["context"] = _coerce_int(args.get("context"), default=2, low=0, high=10)

    elif op == "edit_file":
        if not project.write_enabled:
            return {"error": True, "message": "Writes are disabled for this project."}
        if not args.get("old_string"):
            # Fail fast with the correct recovery path -- a confused model once
            # used old_string="" + replace_all to fake a file deletion.
            return {
                "error": True,
                "retryable": True,
                "message": (
                    "old_string cannot be empty. To remove a section, pass that section's "
                    "exact text as old_string with an empty new_string. To delete a whole "
                    "file, call codebase_delete_file instead."
                ),
            }
        key = _ledger_key(chat_id, project.id, path)
        with _ledger_lock:
            expected_hash = _read_ledger.get(key)
        if expected_hash is None:
            return {
                "error": True,
                "retryable": True,
                "message": f"You must call codebase_read_file on '{path}' before editing it.",
            }
        params.update(
            path=path,
            old_string=args["old_string"],
            new_string=args["new_string"],
            replace_all=bool(args.get("replace_all", False)),
            expected_content_hash=expected_hash,
        )

    elif op == "write_file":
        if not project.write_enabled:
            return {"error": True, "message": "Writes are disabled for this project."}
        params.update(path=path, content=_strip_wrapping_code_fence(args.get("content", "")))

    elif op == "delete_file":
        if not project.write_enabled:
            return {"error": True, "message": "Writes are disabled for this project."}
        # Same read-before-write gate as edit_file: the model must have seen the
        # file's content this conversation (a read OR a write/edit it made
        # itself) before it may destroy it -- blind deletes by a confused model
        # self-correct through the retry loop instead of removing data.
        key = _ledger_key(chat_id, project.id, path)
        with _ledger_lock:
            known = key in _read_ledger
        if not known:
            return {
                "error": True,
                "retryable": True,
                "message": f"You must call codebase_read_file on '{path}' before deleting it.",
            }
        params.update(path=path)

    elif op == "move_file":
        if not project.write_enabled:
            return {"error": True, "message": "Writes are disabled for this project."}
        new_path = args.get("new_path") or ""
        if not new_path:
            return {
                "error": True,
                "retryable": True,
                "message": "new_path is required: the destination path relative to the project root.",
            }
        params.update(path=path, new_path=new_path)

    elif op == "run_command":
        # Command execution is trusted at the same level as editing: a project
        # the model may edit is one it may build/run.
        if not project.write_enabled:
            return {"error": True, "message": "Command execution is disabled for this project."}
        command = (args.get("command") or "").strip()
        if not command:
            return {
                "error": True,
                "retryable": True,
                "message": "command is required: the shell command to run, e.g. 'python main.py'.",
            }
        params.update(command=command, cwd=args.get("cwd") or ".")
        if args.get("timeout") is not None:
            params["timeout"] = _coerce_int(args.get("timeout"), default=120, low=1, high=600)

    try:
        if op == "run_command":
            # A build/test can take much longer than the 20s default WS timeout.
            # Give the socket the command's own timeout plus margin so the agent
            # gets to finish and report, rather than the hub timing out first.
            cmd_timeout = _coerce_int(args.get("timeout"), default=120, low=1, high=600)
            result = await conn.send_command(op, params, timeout=float(cmd_timeout + 20))
        else:
            result = await conn.send_command(op, params)
    except ConnectionError as exc:
        return {"error": True, "message": str(exc)}

    if not result.get("error"):
        if op in ("read_file", "edit_file", "write_file") and "content_hash" in result:
            with _ledger_lock:
                _read_ledger[_ledger_key(chat_id, project.id, path)] = result["content_hash"]
        elif op == "delete_file":
            with _ledger_lock:
                _read_ledger.pop(_ledger_key(chat_id, project.id, path), None)
        elif op == "move_file":
            # The bytes are unchanged, only the path moved: carry the ledger
            # entry to the new path so an immediate edit there doesn't force a
            # pointless re-read, and drop the stale source entry.
            with _ledger_lock:
                moved_hash = _read_ledger.pop(_ledger_key(chat_id, project.id, path), None)
                new_hash = result.get("content_hash") or moved_hash
                if new_hash:
                    _read_ledger[_ledger_key(chat_id, project.id, result.get("new_path", ""))] = new_hash

    return result
