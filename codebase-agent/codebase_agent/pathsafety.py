"""Path safety: the single seam every filesystem operation must go through.

Resolves a user-supplied relative path against a registered project root,
rejecting anything that would escape the root -- including via '..', an
absolute-path reset, or a symlink inside the root pointing outside it.

Resolve-then-check ordering matters: checking an unresolved path lets a
symlink inside the root escape a naive prefix check. Always resolve fully
(dereferencing symlinks), then compare against the freshly-resolved root.
"""
from __future__ import annotations

import os
from pathlib import Path

VCS_DIRS = {".git", ".hg", ".svn"}


class PathSafetyError(Exception):
    pass


def resolve_safe_path(root: Path, relative_path: str, *, for_write: bool = False) -> Path:
    if not relative_path or "\x00" in relative_path:
        raise PathSafetyError("Invalid path")

    normalized_input = relative_path.replace("\\", "/")
    if normalized_input.startswith("/"):
        raise PathSafetyError("Path must be relative to the project root, not absolute")
    if len(normalized_input) >= 2 and normalized_input[1] == ":":
        raise PathSafetyError("Path must be relative to the project root, not absolute")

    root_resolved = root.resolve(strict=True)
    candidate = (root_resolved / relative_path).resolve(strict=False)

    root_str = os.path.normcase(str(root_resolved))
    candidate_str = os.path.normcase(str(candidate))
    if candidate_str != root_str and not candidate_str.startswith(root_str + os.sep):
        raise PathSafetyError("Path escapes the project root")

    if for_write:
        remainder = candidate_str[len(root_str):].strip(os.sep)
        segments = remainder.split(os.sep) if remainder else []
        if any(seg in VCS_DIRS for seg in segments):
            raise PathSafetyError("Cannot write inside a VCS metadata directory")

    return candidate


def validate_new_root(path: Path) -> Path:
    """Guard against registering an unreasonably broad directory as a project root."""
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise PathSafetyError("Root must be an existing directory")

    if resolved.parent == resolved:
        raise PathSafetyError("Refusing to register a filesystem drive/root as a project")

    blocked = {Path.home().resolve()}
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot")
        if system_root:
            blocked.add(Path(system_root).resolve())
    else:
        blocked.update(Path(p) for p in ("/etc", "/root", "/usr", "/bin", "/sbin", "/var") if Path(p).exists())

    if resolved in blocked:
        raise PathSafetyError(f"Refusing to register '{resolved}' -- too broad for a project root")

    return resolved
