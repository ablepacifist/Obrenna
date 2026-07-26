"""Registered project roots -- persisted to a small JSON file."""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .pathsafety import validate_new_root
from .storage import PROJECTS_FILE, ensure_data_dir

_lock = threading.Lock()


@dataclass
class Project:
    id: str
    name: str
    root_path: str
    write_enabled: bool
    created_at: str


def _load() -> list[Project]:
    ensure_data_dir()
    if not PROJECTS_FILE.exists():
        return []
    raw = json.loads(PROJECTS_FILE.read_text() or "[]")
    return [Project(**p) for p in raw]


def _save(projects: list[Project]) -> None:
    ensure_data_dir()
    PROJECTS_FILE.write_text(json.dumps([asdict(p) for p in projects], indent=2))


def list_projects() -> list[Project]:
    with _lock:
        return _load()


def get_project(project_id: str) -> Optional[Project]:
    with _lock:
        return next((p for p in _load() if p.id == project_id), None)


def register_project(name: str, root_path: str, write_enabled: bool = False) -> Project:
    validated_root = validate_new_root(Path(root_path))
    with _lock:
        projects = _load()
        if any(p.root_path == str(validated_root) for p in projects):
            raise ValueError("This root is already registered as a project")
        project = Project(
            id=uuid.uuid4().hex,
            name=name,
            root_path=str(validated_root),
            write_enabled=write_enabled,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        projects.append(project)
        _save(projects)
        return project


def update_project(project_id: str, *, name: Optional[str] = None, write_enabled: Optional[bool] = None) -> Optional[Project]:
    with _lock:
        projects = _load()
        for p in projects:
            if p.id == project_id:
                if name is not None:
                    p.name = name
                if write_enabled is not None:
                    p.write_enabled = write_enabled
                _save(projects)
                return p
        return None


def delete_project(project_id: str) -> bool:
    with _lock:
        projects = _load()
        remaining = [p for p in projects if p.id != project_id]
        if len(remaining) == len(projects):
            return False
        _save(remaining)
        return True
