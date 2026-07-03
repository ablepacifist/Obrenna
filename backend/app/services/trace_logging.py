"""Opt-in full trace logging for orchestrator debugging.

This module intentionally logs raw prompts, worker prompts, tool arguments,
tool results, and model responses only when OBRENNA_TRACE_LOGS=1. Normal INFO
logs stay private-by-default.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.trace")


def trace_enabled() -> bool:
    return os.getenv("OBRENNA_TRACE_LOGS") == "1"


def _logs_dir() -> Path:
    data_dir = os.getenv("OBRENNA_DATA_DIR") or os.getenv("GREBGLOB_DATA_DIR")
    if data_dir:
        return Path(data_dir).resolve() / "logs"
    return Path(__file__).resolve().parents[2] / "data" / "logs"


def trace_log_path() -> Path:
    return _logs_dir() / "orchestrator_trace.jsonl"


def _json_default(value: Any) -> str:
    return str(value)


def trace_event(event: str, **payload: Any) -> None:
    if not trace_enabled():
        return

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    line = json.dumps(record, ensure_ascii=False, default=_json_default)

    try:
        path = trace_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # pragma: no cover - diagnostics must never break chat
        logger.debug("Failed to write orchestrator trace log: %s", exc)

    logger.info("TRACE %s", line)
