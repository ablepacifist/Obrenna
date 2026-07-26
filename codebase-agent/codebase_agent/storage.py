"""Where this agent's own state lives (device identity, registered projects)."""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path.home() / ".codebase-agent"
DEVICE_ID_FILE = DATA_DIR / "device_id.txt"
PROJECTS_FILE = DATA_DIR / "projects.json"
BACKUPS_DIRNAME = ".codebase-agent-backups"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
