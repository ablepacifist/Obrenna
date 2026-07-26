"""Automatic backup-before-write, and revert.

Every successful edit/write is preceded by a snapshot of the prior bytes (or
a "didn't exist" sentinel for brand-new files) so it can always be undone --
independent of whether the project root happens to be a git repo.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .storage import BACKUPS_DIRNAME

_NEW_FILE_SENTINEL = "__NEW_FILE__"


@dataclass
class ChangeRecord:
    id: str
    relative_path: str
    backup_file: Optional[str]  # relative to the backups dir; None means the file was newly created
    timestamp: float


def _backups_dir(root: Path) -> Path:
    d = root / BACKUPS_DIRNAME
    d.mkdir(exist_ok=True)
    return d


def _changelog_path(root: Path) -> Path:
    return _backups_dir(root) / "_changelog.json"


def _load_changelog(root: Path) -> list[ChangeRecord]:
    path = _changelog_path(root)
    if not path.exists():
        return []
    raw = json.loads(path.read_text() or "[]")
    return [ChangeRecord(**r) for r in raw]


def _save_changelog(root: Path, records: list[ChangeRecord]) -> None:
    _changelog_path(root).write_text(json.dumps([asdict(r) for r in records], indent=2))


def record_backup(root: Path, target: Path, relative_path: str) -> str:
    """Snapshot target's current bytes (if it exists) before it's overwritten."""
    backups_dir = _backups_dir(root)
    change_id = uuid.uuid4().hex
    ts = time.time()

    if target.exists():
        backup_subdir = backups_dir / relative_path.replace("/", "__")
        backup_subdir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_subdir / f"{int(ts * 1000)}.bak"
        backup_file.write_bytes(target.read_bytes())
        backup_relpath = str(backup_file.relative_to(backups_dir))
    else:
        backup_relpath = None

    records = _load_changelog(root)
    records.append(ChangeRecord(id=change_id, relative_path=relative_path, backup_file=backup_relpath, timestamp=ts))
    _save_changelog(root, records)
    return change_id


def list_changes(root: Path, limit: int = 50) -> list[ChangeRecord]:
    records = _load_changelog(root)
    return sorted(records, key=lambda r: r.timestamp, reverse=True)[:limit]


def revert_change(root: Path, change_id: str) -> None:
    records = _load_changelog(root)
    record = next((r for r in records if r.id == change_id), None)
    if record is None:
        raise ValueError(f"No such change: {change_id}")

    target = root / record.relative_path
    if record.backup_file is None:
        # The file didn't exist before this change -- reverting means removing it.
        if target.exists():
            target.unlink()
    else:
        backup_path = _backups_dir(root) / record.backup_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(backup_path.read_bytes())
