"""Per-turn structured telemetry sink.

Appends one JSON line per chat turn to a local JSONL file so that performance
changes (prompt-prefix caching, model residency, parallel tool calls, retrieval
caching, streaming coalescing) can be proven with a before/after baseline.

This is a local-only sink: nothing is sent to any remote endpoint. The output
path defaults to ``backend/telemetry/turns.jsonl`` and can be overridden with the
``OBRENNA_TELEMETRY_DIR`` environment variable. Set ``OBRENNA_TELEMETRY=off`` to
disable writing entirely (useful in tests).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DIR_NAME = "telemetry"
_DEFAULT_FILE_NAME = "turns.jsonl"

_write_lock = threading.Lock()
# Resolved once on first write so env changes during tests are honoured lazily.
_dir_cache: str | None = None


def _telemetry_dir() -> Path:
    """Resolve the telemetry directory, preferring OBRENNA_TELEMETRY_DIR."""
    global _dir_cache
    override = os.getenv("OBRENNA_TELEMETRY_DIR")
    if override:
        path = Path(override)
    else:
        # Default to <repo>/backend/telemetry relative to this file.
        path = Path(__file__).resolve().parents[2] / _DEFAULT_DIR_NAME
    _dir_cache = str(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _telemetry_file() -> Path:
    return _telemetry_dir() / _DEFAULT_FILE_NAME


def telemetry_enabled() -> bool:
    """Whether writing turn telemetry is enabled (default: on)."""
    return os.getenv("OBRENNA_TELEMETRY", "on").lower() not in {"off", "0", "false", "no"}


def write_turn_telemetry(chat_id: str, telemetry: dict[str, Any]) -> None:
    """Append one structured JSON line for a completed chat turn.

    ``telemetry`` is the serialisable summary dict produced by ``TurnTelemetry``
    (plus any per-round Ollama stats the runtime recorded). Writes are append-only
    and serialised under a lock so concurrent turns never interleave lines.
    """
    if not telemetry_enabled():
        return
    record = {
        "chat_id": chat_id,
        "telemetry": telemetry,
    }
    line = json.dumps(record, separators=(",", ":"), default=str)
    try:
        with _write_lock:
            with _telemetry_file().open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError as exc:
        # Telemetry must never break a turn — log and move on.
        logger.debug("Failed to write turn telemetry: %s", exc)