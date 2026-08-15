"""run_command: execute a shell command inside a project's working directory.

This is the capability that turns a file editor into a coding agent — the agent
can install dependencies, run a script, run tests, or build a project, then read
the real output and fix what's broken. It is deliberately powerful: it runs REAL
commands on the machine the agent is installed on. It is bounded, not sandboxed:

  * only for write-enabled projects (same trust level as editing),
  * the working directory is confined to the project root (resolve_safe_path),
  * a wall-clock timeout kills runaway/hung commands,
  * stdout/stderr are captured and truncated to a cap before feed-back.

Commands also receive the project's own .env/.Renviron (see project_env), so a
script that reads its credentials the way the project already reads them works
here as it does in the user's own shell.

It does NOT try to whitelist commands or block "dangerous" ones — that is a
false sense of security on a shell, and Claude Code (the model this emulates)
runs real commands too. The real guardrails are device approval + write_enabled
+ the confined cwd + the timeout.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .fs_tools import FsError
from .pathsafety import resolve_safe_path
from .project_env import build_command_env

OUTPUT_CHAR_CAP = 20_000
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600


@dataclass
class CommandResult:
    command: str
    cwd: str
    exit_code: int | None  # None when the command timed out
    stdout: str
    stderr: str
    timed_out: bool


def _cap(text: str) -> str:
    """Keep head + tail so both the start of a build log and the final error
    survive truncation (the two parts a model most needs)."""
    if text is None:
        return ""
    if len(text) <= OUTPUT_CHAR_CAP:
        return text
    half = OUTPUT_CHAR_CAP // 2
    return f"{text[:half]}\n... [truncated {len(text) - OUTPUT_CHAR_CAP} chars] ...\n{text[-half:]}"


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def run_command(root: Path, command: str, *, cwd: str = ".", timeout: int | None = None) -> CommandResult:
    if not command or not command.strip():
        raise FsError("command must not be empty")

    work_dir = resolve_safe_path(root, cwd or ".")
    if not work_dir.is_dir():
        raise FsError(f"cwd is not a directory: {cwd}")

    t = DEFAULT_TIMEOUT if timeout is None else max(1, min(int(timeout), MAX_TIMEOUT))

    try:
        proc = subprocess.run(
            command,
            shell=True,               # honor normal command lines: "python x.py", "npm test"
            cwd=str(work_dir),
            capture_output=True,
            # No inherited stdin: an interactive command gets EOF immediately
            # instead of hanging until the timeout, and we never duplicate the
            # agent's own stdin handle (which is a pipe/closed in the Tauri
            # sidecar — inheriting it fails outright on Windows).
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=t,
            encoding="utf-8",
            errors="replace",
            # The project's own .env/.Renviron, so its connection helpers work
            # here exactly as they do when the user runs them by hand. The
            # values never leave this process's child - see project_env.
            env=build_command_env(root),
        )
        return CommandResult(
            command=command, cwd=cwd or ".", exit_code=proc.returncode,
            stdout=_cap(proc.stdout), stderr=_cap(proc.stderr), timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        err = _decode(exc.stderr)
        return CommandResult(
            command=command, cwd=cwd or ".", exit_code=None,
            stdout=_cap(_decode(exc.stdout)),
            stderr=_cap(f"{err}\n[command timed out after {t}s and was terminated]"),
            timed_out=True,
        )
