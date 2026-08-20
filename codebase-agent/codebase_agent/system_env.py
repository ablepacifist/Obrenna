"""Keep a long-running agent's PATH as current as a freshly opened shell's.

A process inherits its environment once, at launch. The codebase-agent runs for
days, so anything installed or added to PATH after it started is invisible to
every command it spawns -- while the same command works perfectly in the user's
own terminal.

That is not a hypothetical: a user installed R, added it to PATH, and asked the
agent to run `Rscript --version`. It came back "'Rscript' is not recognized as
an internal or external command" on every attempt. The model concluded R was
not installed and told the user so, listing the evidence, while R sat on the
PATH of every shell opened after the agent started.

On Windows the authoritative PATH lives in the registry (that is what a new
cmd.exe reads). Re-reading it per command costs microseconds and closes the
gap. Entries are only ever ADDED to the inherited PATH, never removed, so a
venv or launcher prefix the agent depends on keeps its precedence.
"""
from __future__ import annotations

import os

_WINDOWS_SYSTEM_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_WINDOWS_USER_ENV_KEY = "Environment"


def _read_registry_path() -> list[str]:
    """PATH entries a newly opened shell would see. Empty off Windows."""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows always has it
        return []

    entries: list[str] = []
    for root, sub in (
        (winreg.HKEY_LOCAL_MACHINE, _WINDOWS_SYSTEM_ENV_KEY),
        (winreg.HKEY_CURRENT_USER, _WINDOWS_USER_ENV_KEY),
    ):
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if isinstance(value, str):
            entries.extend(part for part in value.split(os.pathsep) if part.strip())
    return entries


def _normalise(entry: str) -> str:
    return os.path.expandvars(entry).rstrip("\\/").lower()


def refreshed_path(inherited: str, extra_entries: list[str] | None = None) -> str:
    """``inherited`` plus any PATH entry it is missing, appended in order.

    Append rather than prepend: the agent's own environment may deliberately
    put a virtualenv or a bundled toolchain first, and reordering that to pick
    up a newly installed program would be a different kind of surprise.
    """
    entries = _read_registry_path() if extra_entries is None else extra_entries
    if not entries:
        return inherited

    seen = {_normalise(p) for p in inherited.split(os.pathsep) if p.strip()}
    additions = []
    for entry in entries:
        key = _normalise(entry)
        if key and key not in seen:
            seen.add(key)
            additions.append(os.path.expandvars(entry))
    if not additions:
        return inherited
    return os.pathsep.join([inherited, *additions]) if inherited else os.pathsep.join(additions)


# Shells say this when a program is not on PATH. Matched so the failure can be
# explained instead of being read as "that program is not installed".
_NOT_FOUND_MARKERS = (
    "is not recognized as an internal or external command",
    "command not found",
    "no such file or directory",
)


def looks_like_missing_program(stderr: str, stdout: str = "") -> bool:
    blob = f"{stderr}\n{stdout}".lower()
    return any(marker in blob for marker in _NOT_FOUND_MARKERS)


def missing_program_hint(command: str) -> str:
    program = (command.strip().split() or [""])[0].strip('"\'')
    return (
        f"\n[obrenna] '{program}' was not found on this machine's PATH as the agent sees it. "
        "This does NOT mean it is not installed. The agent inherited its PATH when it "
        "started, so anything installed or added to PATH since then is invisible to it "
        "until the agent is restarted. Before concluding it is unavailable: try the full "
        "path to the executable, or ask the user to restart the codebase-agent."
    )
