"""Local knowledge-pack registry and install helpers.

This keeps v1 pack management local-first:
- install copies a validated pack into the managed packs directory
- uninstall removes the managed copy and registry entry
- discovery reads from the registry plus the installed directory
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...config import DATA_DIR
from .builder import checksum_matches, validate_pack_file

PACKS_DIR = DATA_DIR / "packs"
INSTALLED_DIR = PACKS_DIR / "installed"
REGISTRY_PATH = PACKS_DIR / "registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    INSTALLED_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class PackRegistryEntry:
    pack_id: str
    name: str
    version: str
    installed_at: str
    source_path: str
    pack_path: str
    checksum_ok: bool
    status: str = "installed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "name": self.name,
            "version": self.version,
            "installed_at": self.installed_at,
            "source_path": self.source_path,
            "pack_path": self.pack_path,
            "checksum_ok": self.checksum_ok,
            "status": self.status,
        }


def _read_registry() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    except json.JSONDecodeError:
        pass
    return []


def _write_registry(rows: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    REGISTRY_PATH.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def list_installed_packs() -> list[dict[str, Any]]:
    """Return registry entries for installed packs."""

    return _read_registry()


def _pack_identity(pack_path: Path) -> tuple[str, str, str]:
    with sqlite3.connect(pack_path) as conn:
        rows = dict(conn.execute("SELECT key, value FROM pack_metadata").fetchall())
    pack_id = str(rows.get("pack_id") or pack_path.stem)
    version = str(rows.get("version") or "0.0.0")
    name = str(rows.get("name") or pack_id)
    return pack_id, version, name


def install_pack(pack_path: str | Path, *, replace: bool = True) -> PackRegistryEntry:
    """Install a validated pack into the managed packs directory."""

    source = Path(pack_path)
    if not source.exists():
        raise FileNotFoundError(f"Pack not found: {source}")

    issues = validate_pack_file(source)
    errors = [issue.message for issue in issues if issue.level == "error"]
    if errors:
        raise ValueError("Pack validation failed:\n- " + "\n- ".join(errors))

    if not checksum_matches(source):
        raise ValueError("Pack checksum missing or invalid")

    pack_id, version, name = _pack_identity(source)
    destination_dir = INSTALLED_DIR / pack_id / version
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists() and not replace:
        raise FileExistsError(f"Pack already installed: {destination}")

    shutil.copy2(source, destination)
    checksum_src = source.with_suffix(source.suffix + ".sha256")
    if checksum_src.exists():
        shutil.copy2(checksum_src, destination.with_suffix(destination.suffix + ".sha256"))

    registry = [row for row in _read_registry() if row.get("pack_id") != pack_id]
    entry = PackRegistryEntry(
        pack_id=pack_id,
        name=name,
        version=version,
        installed_at=_now(),
        source_path=str(source),
        pack_path=str(destination),
        checksum_ok=True,
    )
    registry.append(entry.as_dict())
    _write_registry(registry)
    return entry


def uninstall_pack(pack_id: str) -> bool:
    """Remove an installed pack and its registry entry."""

    registry = _read_registry()
    remaining: list[dict[str, Any]] = []
    removed = False
    for row in registry:
        if row.get("pack_id") == pack_id:
            removed = True
            pack_path = Path(str(row.get("pack_path") or ""))
            checksum_path = pack_path.with_suffix(pack_path.suffix + ".sha256")
            if pack_path.exists():
                pack_path.unlink()
            if checksum_path.exists():
                checksum_path.unlink()
            continue
        remaining.append(row)

    if removed:
        _write_registry(remaining)
    return removed


def installed_pack_paths() -> list[Path]:
    """Return pack SQLite files recorded in the registry."""

    paths: list[Path] = []
    for row in _read_registry():
        pack_path = row.get("pack_path")
        if pack_path:
            candidate = Path(str(pack_path))
            if candidate.exists():
                paths.append(candidate)
    return paths
