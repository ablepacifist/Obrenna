"""list_directory / read_file / write_file -- the read-side and new-file primitives.

edit_file (existing-file modification) lives in edit.py alongside the backup
mechanism, since every write there needs a backup; write_file here is
new-file-only and simpler.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .excludes import is_excluded_dir, is_excluded_file
from .pathsafety import PathSafetyError, resolve_safe_path

READ_BYTE_CAP = 250_000
WRITE_BYTE_CAP = 250_000


class FsError(Exception):
    pass


@dataclass
class DirEntry:
    name: str
    path: str
    type: str  # "file" | "dir"
    size: Optional[int] = None


def is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def list_directory(root: Path, relative_path: str, *, recursive: bool = False, max_entries: int = 200) -> list[DirEntry]:
    target = resolve_safe_path(root, relative_path)
    if not target.is_dir():
        raise FsError(f"Not a directory: {relative_path}")

    entries: list[DirEntry] = []

    def _walk(dir_path: Path, rel_prefix: str) -> None:
        if len(entries) >= max_entries:
            return
        try:
            children = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for child in children:
            if len(entries) >= max_entries:
                return
            rel = f"{rel_prefix}{child.name}"
            if child.is_dir():
                if is_excluded_dir(child.name):
                    continue
                entries.append(DirEntry(name=child.name, path=rel, type="dir"))
                if recursive:
                    _walk(child, rel + "/")
            else:
                if is_excluded_file(child.name):
                    continue
                try:
                    size = child.stat().st_size
                except OSError:
                    size = None
                entries.append(DirEntry(name=child.name, path=rel, type="file", size=size))

    _walk(target, "")
    return entries


@dataclass
class ReadResult:
    content: str
    total_lines: int
    truncated: bool
    content_hash: str


def read_file(root: Path, relative_path: str, *, offset: int = 0, limit: Optional[int] = None) -> ReadResult:
    import hashlib

    target = resolve_safe_path(root, relative_path)
    if not target.is_file():
        raise FsError(f"Not a file: {relative_path}")

    raw = target.read_bytes()
    if is_binary(raw[:8000]):
        raise FsError(f"Refusing to read binary file: {relative_path}")

    content_hash = hashlib.sha256(raw).hexdigest()

    truncated = False
    if len(raw) > READ_BYTE_CAP:
        raw = raw[:READ_BYTE_CAP]
        truncated = True

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    if offset or limit:
        end = offset + limit if limit else None
        selected = lines[offset:end]
        if end is not None and end < total_lines:
            truncated = True
    else:
        selected = lines

    numbered = "\n".join(f"{i + 1 + offset}\t{line}" for i, line in enumerate(selected))
    return ReadResult(content=numbered, total_lines=total_lines, truncated=truncated, content_hash=content_hash)


def write_new_file(root: Path, relative_path: str, content: str) -> str:
    """Create a brand-new file. Errors if the path already exists -- use edit_file to modify."""
    import hashlib

    target = resolve_safe_path(root, relative_path, for_write=True)
    if target.exists():
        raise FsError(f"File already exists, use edit_file to modify it: {relative_path}")

    data = content.encode("utf-8")
    if len(data) > WRITE_BYTE_CAP:
        raise FsError(f"Content too large ({len(data)} bytes, cap is {WRITE_BYTE_CAP})")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def delete_file(root: Path, relative_path: str) -> str:
    """Delete a file, snapshotting its bytes first so revert_change can restore it.

    Returns the change_id of the backup record. Directories are refused --
    deleting a tree is never something the orchestrator should do in one call.
    """
    from .backups import record_backup

    target = resolve_safe_path(root, relative_path, for_write=True)
    if target.is_dir():
        raise FsError(f"Not a file (directories cannot be deleted): {relative_path}")
    if not target.is_file():
        raise FsError(f"Not a file: {relative_path}")

    change_id = record_backup(root, target, relative_path)
    target.unlink()
    return change_id


def move_file(root: Path, relative_path: str, new_relative_path: str) -> tuple[str, str]:
    """Move/rename a file within the project. Never overwrites the destination.

    The source bytes are snapshotted first (reverting the change restores the
    source; the copy at the destination is left for the user to inspect).
    Returns (change_id, content_hash of the moved bytes).
    """
    import hashlib

    from .backups import record_backup

    source = resolve_safe_path(root, relative_path, for_write=True)
    dest = resolve_safe_path(root, new_relative_path, for_write=True)
    if not source.is_file():
        raise FsError(f"Not a file: {relative_path}")
    if dest.exists():
        raise FsError(f"Destination already exists, refusing to overwrite: {new_relative_path}")

    data = source.read_bytes()
    change_id = record_backup(root, source, relative_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    source.rename(dest)
    return change_id, hashlib.sha256(data).hexdigest()
