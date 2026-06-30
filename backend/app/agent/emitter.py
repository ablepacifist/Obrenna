"""Emit typed streaming events from Python to the Rust sidecar.

Python writes JSON event envelopes to stdout. Rust reads them line-by-line
and emits them as Tauri events to the webview.

This module provides a singleton event emitter that is thread-safe and
only writes valid JSON to stdout.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any

from .events import StreamEvent

logger = logging.getLogger(__name__)

# Thread lock for stdout writes
_emitter_lock = threading.Lock()


class EventEmitter:
    """Thread-safe event emitter for agent streaming events.

    Writes JSON event envelopes to stdout for the Rust sidecar to read
    and relay to the webview via Tauri events.
    """

    def emit(self, event: StreamEvent) -> None:
        """Emit a stream event to stdout."""
        with _emitter_lock:
            try:
                line = event.to_json_line()
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except Exception as exc:
                logger.error("Failed to emit event: %s", exc)

    def emit_raw(self, data: dict[str, Any]) -> None:
        """Emit a raw JSON line to stdout (bypasses envelope format).

        Used for non-streaming log/info messages that should not
        be confused with typed agent events.
        """
        with _emitter_lock:
            try:
                line = json.dumps(data)
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except Exception as exc:
                logger.error("Failed to emit raw data: %s", exc)


# Module-level singleton
_emitter: EventEmitter | None = None


def get_emitter() -> EventEmitter:
    """Get the module-level event emitter singleton."""
    global _emitter
    if _emitter is None:
        _emitter = EventEmitter()
    return _emitter


def emit_token(chat_id: str, text: str, message_id: str = "") -> None:
    """Convenience function to emit a token event."""
    from .events import token_event
    get_emitter().emit(token_event(chat_id, text, message_id))


def emit_done(chat_id: str, message_id: str = "", summary: str = "") -> None:
    """Convenience function to emit a done event."""
    from .events import done_event
    get_emitter().emit(done_event(chat_id, message_id, summary))


def emit_error(chat_id: str, error_code: str = "internal_error",
               message: str = "", recoverable: bool = True) -> None:
    """Convenience function to emit an error event."""
    from .events import error_event
    get_emitter().emit(error_event(chat_id, error_code, message, recoverable))
