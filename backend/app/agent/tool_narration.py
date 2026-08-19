"""Helper-model narration of tool calls.

Produces a short, human-readable description of what a tool is doing right now
(e.g. "Searching the web for …", "Running the calculation …") so the chat UI
can show the agent's process at a glance instead of raw JSON args.

Reuses the same one-shot helper-model pattern as `services/memory.py`:
the small `utility` (or `summarizer`) role via `chat_completion`, with a short
prompt, low temperature, a bounded timeout, and a graceful fallback so a failed
or slow narration never blocks the turn.
"""
from __future__ import annotations

import asyncio
import json
import logging

from ..mcp.tools import tool_def_by_name
from ..model_runtime.client import chat_completion
from ..model_runtime.config import RuntimeConfig

logger = logging.getLogger(__name__)

# Static per-tool fallback used when the helper model is unavailable, returns
# nothing, or times out. Keeps every card legible even with the endpoint down.
FALLBACK_NARRATION: dict[str, str] = {
    "web_search": "Searching the web",
    "calculator": "Running a calculation",
    "get_time": "Looking up the current time",
    "file_read": "Reading a file",
    "get_location": "Finding your location",
    # The codebase tools had no entries at all, so on a setup with no utility
    # model every one of them rendered as a bare tool name with no text under
    # it -- which is most of what the user sees during a coding turn.
    "codebase_list_directory": "Listing the project",
    "codebase_read_file": "Reading a project file",
    "codebase_search": "Searching the codebase",
    "codebase_find_files": "Looking for files by name",
    "codebase_edit_file": "Editing a project file",
    "codebase_write_file": "Writing a project file",
    "codebase_delete_file": "Deleting a project file",
    "codebase_move_file": "Moving a project file",
    "codebase_run_command": "Running a command in the project",
    "ask_user": "Asking you a question",
}

# Bounded so a slow helper model can never stall the turn. Narration runs
# concurrently with tool execution, so in the common case it finishes well
# before this timeout.
NARRATION_TIMEOUT = 8.0


def _build_prompt(tool_name: str, purpose: str, args_json: str) -> str:
    return (
        "You narrate what an AI assistant's tool is doing right now, for a user "
        "watching a live chat UI. Write ONE short, friendly sentence in the "
        "present progressive tense (e.g. \"Searching the web for …\", \"Running "
        "the calculation 47 * 83\"), max ~12 words. Address the user naturally. "
        "Do NOT mention JSON, argument names, the word \"tool\", or \"calling\". "
        "Output only the sentence, no quotes.\n\n"
        f"Tool: {tool_name}\n"
        f"Purpose: {purpose}\n"
        f"Inputs: {args_json}"
    )


async def narrate_tool_call(
    config: RuntimeConfig, tool_name: str, arguments: dict
) -> str | None:
    """Return a one-line human narration of a tool call, or None on any failure."""
    chosen = config.model_for("utility") or config.model_for("summarizer")
    if not chosen:
        return FALLBACK_NARRATION.get(tool_name)
    # tool_def_by_name only knows the built-in TOOL_DEFS; the codebase_* tools
    # are assembled per-project, so the static line is the only purpose hint
    # available for them.
    purpose = (
        (tool_def_by_name(tool_name) or {}).get("description", "")
        or FALLBACK_NARRATION.get(tool_name, "")
    )
    try:
        args_json = json.dumps(arguments, default=str)[:300]
    except (TypeError, ValueError):
        args_json = ""
    prompt = _build_prompt(tool_name, purpose, args_json)
    try:
        text = await chat_completion(
            config,
            [{"role": "user", "content": prompt}],
            model=chosen,
            role="utility",
            temperature=0.1,
            timeout=NARRATION_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - narration is best-effort
        logger.debug("tool narration failed for %s: %s", tool_name, exc)
        return FALLBACK_NARRATION.get(tool_name)
    cleaned = (text or "").strip().strip('"').strip()
    return cleaned[:140] or FALLBACK_NARRATION.get(tool_name)


def _call_name(tc: dict) -> str:
    return tc.get("function", {}).get("name", "") if isinstance(tc, dict) else ""


def _call_args(tc: dict) -> dict:
    if not isinstance(tc, dict):
        return {}
    a = tc.get("function", {}).get("arguments", {})
    return a if isinstance(a, dict) else {}


async def gather_narrations(
    config: RuntimeConfig, calls: list[dict]
) -> list[str | None]:
    """Run narration for every call concurrently. Per-item exceptions -> None."""
    coros = [narrate_tool_call(config, _call_name(c), _call_args(c)) for c in calls]
    return await asyncio.gather(*coros, return_exceptions=True)


def narration_desc(narration: object, tool_name: str) -> str | None:
    """Pick the model narration, or the static fallback, or None."""
    if isinstance(narration, str):
        return narration
    return FALLBACK_NARRATION.get(tool_name)