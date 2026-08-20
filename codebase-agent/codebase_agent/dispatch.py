"""Dispatch a command received over the WebSocket to the right local operation.

Ports the same logic that used to live in routers/{projects,fs,changes}.py --
this module returns plain dict envelopes ({"error": True, "message": ...} on
failure) instead of raising HTTPException, since there's no HTTP layer here
anymore. Called via asyncio.to_thread from ws_client.py so a slow filesystem
op on one command never blocks the receive loop from handling others.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import projects as projects_svc
from .backups import list_changes, revert_change
from .command_exec import run_command
from .edit import EditConflictError, EditNotFoundError, EditNotUniqueError, edit_file
from .fs_tools import (
    FsError,
    delete_file,
    find_by_basename,
    find_files,
    list_directory,
    move_file,
    read_file,
    write_new_file,
)
from .pathsafety import PathSafetyError
from .search import DEFAULT_CONTEXT_LINES, search_codebase


def _err(message: str) -> dict[str, Any]:
    return {"error": True, "message": message}


def _err_bad_path(root: Path, wanted: str, message: str) -> dict[str, Any]:
    """A path error that points at the recovery instead of dead-ending.

    "Not a file: DATABASE_SCHEMA_REFERENCE.md" is indistinguishable from "this
    project does not contain that file", and was reported to the user as
    exactly that -- while the file was sitting in docs/. The agent already
    knows the tree, so a wrong path should answer with the right one.

    Read paths only, deliberately. Suggesting a substitute path to a delete or
    move would invite destroying a file the caller never named.
    """
    try:
        candidates = find_by_basename(root, wanted)
    except OSError:
        candidates = []

    if candidates:
        hint = (
            f"{message}. A file with that name exists elsewhere in the project: "
            f"{', '.join(candidates)}. Retry with one of those exact paths."
        )
    else:
        hint = (
            f"{message}. No file with that name exists anywhere in the project. "
            "Do NOT conclude it is missing yet -- run codebase_search for part of "
            "the name, or codebase_list_directory on the folder you expect it in, "
            "to find what it is actually called."
        )
    out: dict[str, Any] = {"error": True, "retryable": True, "message": hint}
    if candidates:
        out["did_you_mean"] = candidates
    return out


def _get_project_root(project_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    project = projects_svc.get_project(project_id)
    if project is None:
        return None, _err("Project not found")
    return Path(project.root_path), None


def _require_write_enabled(project_id: str) -> tuple[Path | None, dict[str, Any] | None]:
    project = projects_svc.get_project(project_id)
    if project is None:
        return None, _err("Project not found")
    if not project.write_enabled:
        return None, _err("Writes are disabled for this project")
    return Path(project.root_path), None


def op_register_project(params: dict[str, Any]) -> dict[str, Any]:
    try:
        project = projects_svc.register_project(
            params["name"], params["root_path"], params.get("write_enabled", False)
        )
    except (PathSafetyError, ValueError) as exc:
        return _err(str(exc))
    return {"id": project.id, "root_path": project.root_path, "write_enabled": project.write_enabled}


def op_update_project(params: dict[str, Any]) -> dict[str, Any]:
    project = projects_svc.update_project(
        params["project_id"], name=params.get("name"), write_enabled=params.get("write_enabled")
    )
    if project is None:
        return _err("Project not found")
    return {"id": project.id, "root_path": project.root_path, "write_enabled": project.write_enabled}


def op_delete_project(params: dict[str, Any]) -> dict[str, Any]:
    ok = projects_svc.delete_project(params["project_id"])
    return {"deleted": ok}


_LIST_ENTRY_CAP = 200
_LIST_TRUNCATED_NOTE = (
    "Listing stopped at the entry limit -- this directory has more in it. "
    "List a subdirectory to see the rest; do not conclude a file is missing "
    "from this listing alone."
)


def op_list_directory(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _get_project_root(params["project_id"])
    if error:
        return error
    try:
        entries = list_directory(
            root,
            params.get("path", "."),
            recursive=bool(params.get("recursive", False)),
            max_entries=_LIST_ENTRY_CAP,
        )
    except (PathSafetyError, FsError) as exc:
        return _err(str(exc))
    # Hitting the cap used to be silent, which is another way a file that exists
    # reads as one that doesn't.
    truncated = len(entries) >= _LIST_ENTRY_CAP
    payload: dict[str, Any] = {
        "entries": [asdict(e) for e in entries],
        "entry_count": len(entries),
        "truncated": truncated,
    }
    if truncated:
        payload["note"] = _LIST_TRUNCATED_NOTE
    return payload


_FIND_FILES_CAP = 100
_NO_FILE_MATCH_NOTE = (
    "No filename matched. Try a shorter fragment ('schema' rather than "
    "'DATABASE_SCHEMA_REFERENCE.md'), or codebase_list_directory to see what is "
    "actually there. Do not report the file as missing on one attempt."
)


def op_find_files(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _get_project_root(params["project_id"])
    if error:
        return error
    try:
        paths = find_files(root, str(params.get("pattern", "")), limit=_FIND_FILES_CAP)
    except (PathSafetyError, FsError, ValueError) as exc:
        return _err(str(exc))
    payload: dict[str, Any] = {
        "paths": paths,
        "match_count": len(paths),
        "truncated": len(paths) >= _FIND_FILES_CAP,
    }
    if not paths:
        payload["note"] = _NO_FILE_MATCH_NOTE
    return payload


def op_read_file(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _get_project_root(params["project_id"])
    if error:
        return error
    try:
        result = read_file(root, params["path"], offset=params.get("offset", 0), limit=params.get("limit"))
    except PathSafetyError as exc:
        return _err(str(exc))
    except FsError as exc:
        return _err_bad_path(root, params["path"], str(exc))
    return {"path": params["path"], **asdict(result)}


_NO_MATCH_NOTE = (
    "No lines matched. This is NOT proof the symbol is absent from the project: "
    "try a shorter or partial pattern, a different casing, regex=false for a "
    "literal string, or list the directory you expect it in and read the file."
)
_TRUNCATED_NOTE = (
    "Result limit reached -- there are more matches than these. Narrow the "
    "pattern or search a subdirectory with 'path' to see the rest."
)


def op_search(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _get_project_root(params["project_id"])
    if error:
        return error
    try:
        outcome = search_codebase(
            root,
            params["pattern"],
            path=params.get("path", "."),
            regex=bool(params.get("regex", True)),
            context=int(params.get("context", DEFAULT_CONTEXT_LINES)),
        )
    except (PathSafetyError, ValueError) as exc:
        return _err(str(exc))

    # The counts travel with the matches so an empty list can be read as "looked
    # at 1400 files and found nothing" rather than as a bare, ambiguous [].
    payload: dict[str, Any] = {
        "matches": [asdict(m) for m in outcome.matches],
        "match_count": len(outcome.matches),
        "files_with_matches": outcome.files_with_matches,
        "backend": outcome.backend,
        "truncated": outcome.truncated,
    }
    # Omitted rather than reported as 0 when the backend cannot say: "scanned 0
    # files" is a much stronger claim than "don't know", and the wrong one.
    if outcome.files_scanned is not None:
        payload["files_scanned"] = outcome.files_scanned
    if outcome.files_skipped_large:
        payload["files_skipped_too_large"] = outcome.files_skipped_large
    if not outcome.matches:
        payload["note"] = _NO_MATCH_NOTE
    elif outcome.truncated:
        payload["note"] = _TRUNCATED_NOTE
    return payload


def op_edit_file(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _require_write_enabled(params["project_id"])
    if error:
        return error
    try:
        result = edit_file(
            root,
            params["path"],
            params["old_string"],
            params["new_string"],
            replace_all=bool(params.get("replace_all", False)),
            expected_content_hash=params.get("expected_content_hash"),
        )
    except EditConflictError as exc:
        return _err(str(exc))
    except (EditNotFoundError, EditNotUniqueError, PathSafetyError, FsError) as exc:
        return _err(str(exc))
    # Echo the acted-on path so the orchestrator reports locations from the
    # result instead of from its own (sometimes stale/hallucinated) memory.
    return {"path": params["path"], "edited": True, **asdict(result)}


def op_write_file(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _require_write_enabled(params["project_id"])
    if error:
        return error
    try:
        content_hash = write_new_file(root, params["path"], params.get("content", ""))
    except (PathSafetyError, FsError) as exc:
        return _err(str(exc))
    return {"path": params["path"], "created": True, "content_hash": content_hash}


def op_delete_file(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _require_write_enabled(params["project_id"])
    if error:
        return error
    try:
        change_id = delete_file(root, params["path"])
    except (PathSafetyError, FsError) as exc:
        return _err(str(exc))
    return {"path": params["path"], "deleted": True, "change_id": change_id}


def op_move_file(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _require_write_enabled(params["project_id"])
    if error:
        return error
    try:
        change_id, content_hash = move_file(root, params["path"], params["new_path"])
    except (PathSafetyError, FsError) as exc:
        return _err(str(exc))
    return {
        "path": params["path"],
        "new_path": params["new_path"],
        "moved": True,
        "change_id": change_id,
        "content_hash": content_hash,
    }


def op_run_command(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _require_write_enabled(params["project_id"])
    if error:
        return error
    try:
        result = run_command(
            root, params["command"],
            cwd=params.get("cwd", "."),
            timeout=params.get("timeout"),
        )
    except (PathSafetyError, FsError, ValueError) as exc:
        return _err(str(exc))
    return asdict(result)


def op_list_changes(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _get_project_root(params["project_id"])
    if error:
        return error
    changes = list_changes(root, limit=params.get("limit", 50))
    return {"changes": [asdict(c) for c in changes]}


def op_revert_change(params: dict[str, Any]) -> dict[str, Any]:
    root, error = _get_project_root(params["project_id"])
    if error:
        return error
    try:
        revert_change(root, params["change_id"])
    except ValueError as exc:
        return _err(str(exc))
    return {"reverted": True}


_OPS = {
    "register_project": op_register_project,
    "update_project": op_update_project,
    "delete_project": op_delete_project,
    "list_directory": op_list_directory,
    "read_file": op_read_file,
    "search": op_search,
    "find_files": op_find_files,
    "edit_file": op_edit_file,
    "write_file": op_write_file,
    "delete_file": op_delete_file,
    "move_file": op_move_file,
    "run_command": op_run_command,
    "list_changes": op_list_changes,
    "revert_change": op_revert_change,
}


def dispatch(op: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = _OPS.get(op)
    if handler is None:
        return _err(f"Unknown operation: {op}")
    try:
        return handler(params)
    except KeyError as exc:
        return _err(f"Missing required parameter: {exc}")
    except Exception as exc:  # noqa: BLE001 -- never let an unexpected error kill the connection
        return _err(f"Unexpected error handling '{op}': {exc}")


def supported_ops() -> list[str]:
    """Op names this agent build can actually perform.

    Reported at connect so the backend can avoid advertising a tool that would
    come back as "Unknown operation".
    """
    return sorted(_OPS)
