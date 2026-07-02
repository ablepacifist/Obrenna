"""Configuration helpers for local knowledge packs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..architecture_config import get_services_config
from .registry import installed_pack_paths


def _split_paths(raw: str) -> list[Path]:
    paths: list[Path] = []
    for chunk in raw.split(os.pathsep):
        candidate = chunk.strip()
        if candidate:
            paths.append(Path(candidate))
    return paths


def resolve_pack_paths(config: dict[str, Any] | None = None) -> list[Path]:
    """Resolve active knowledge-pack SQLite files.

    Precedence:
    1. `OBRENNA_KNOWLEDGE_PACKS` env var with os.pathsep-separated paths
    2. `services.knowledge_packs.paths` from architecture_config.json
    3. `data/packs/*.sqlite` and `data/packs/**/*.sqlite` under the repo root
    """

    env_value = os.environ.get("OBRENNA_KNOWLEDGE_PACKS", "").strip()
    if env_value:
        return [path for path in _split_paths(env_value) if path.exists()]

    installed = installed_pack_paths()
    if installed:
        return installed

    services = config or get_services_config()
    pack_cfg = services.get("knowledge_packs", {}) if isinstance(services, dict) else {}
    configured_paths = pack_cfg.get("paths", []) if isinstance(pack_cfg, dict) else []
    resolved: list[Path] = []
    for item in configured_paths:
        path = Path(str(item))
        if path.exists():
            resolved.append(path)

    if resolved:
        return resolved

    repo_root = Path(__file__).resolve().parents[4]
    data_dir = repo_root / "data" / "packs"
    if not data_dir.exists():
        return []

    discovered = sorted(data_dir.glob("*.sqlite")) + sorted(data_dir.glob("**/*.sqlite"))
    unique: list[Path] = []
    for path in discovered:
        if path not in unique:
            unique.append(path)
    return unique
