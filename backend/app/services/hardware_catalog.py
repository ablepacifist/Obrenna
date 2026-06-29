"""Loader for hardware_catalog.json."""
from __future__ import annotations

import json
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parent / "hardware_catalog.json"


def load_catalog(path: str | Path | None = None) -> dict:
    """Load the hardware catalog from its JSON file.

    Args:
        path: Optional override path. Defaults to the bundled file.

    Returns:
        The parsed catalog dict.
    """
    target = Path(path) if path else _CATALOG_PATH
    with open(target) as f:
        return json.load(f)
