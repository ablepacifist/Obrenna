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
import time
from typing import Any

from .events import StreamEvent, EVENT_TYPE_TOKEN, token_event

logger = logging.getLogger(__name__)

# Thread lock for stdout writes
_emitter_lock = threading.Lock()


# ── Token coalescing (Fix #5) ────────────────────────────────────────────────
# Per-token stdout writes (one IPC message per token) dominate sidecar IPC for
# long answers. The coalescer merges consecutive ``token`` events into fewer,
# larger token envelopes so the Rust supervisor relays ~16x fewer Tauri events
# while preserving streaming UX. The first token of a turn is emitted
# immediately (TTFT); afterwards tokens flush as one combined envelope when the
# buffer reaches ``_COALESCE_MAX_TOKENS`` or ``_COALESCE_MAX_INTERVAL_S`` of
# wall-clock elapses. ANY non-token event is a boundary: it flushes pending
# tokens first, then passes through unchanged — different event types are never
# merged. The coalesced token envelope is structurally identical to a single
# token envelope (same ``token`` type + ``payload.text``), so the Rust
# supervisor's typed-envelope validation is unaffected.
_COALESCE_MAX_TOKENS = 16
_COALESCE_MAX_INTERVAL_S = 0.030


class TokenCoalescer:
    """Coalesce consecutive token events into fewer, larger token envelopes.

    Wraps an ``EventEmitter`` (or anything exposing ``.emit(StreamEvent)``).
    Driven from a single-threaded async loop, so the accumulator needs no extra
    lock; the flush path serializes through ``emit()`` which holds
    ``_emitter_lock``.
    """

    def __init__(self, emitter: "EventEmitter", chat_id: str = "", message_id: str = ""):
        self._emitter = emitter
        self._chat_id = chat_id
        self._message_id = message_id
        self._buf: list[str] = []
        self._count = 0
        self._started = False  # first token of the turn emitted immediately (TTFT)
        self._last_flush = time.perf_counter()

    def _flush(self) -> None:
        if not self._buf:
            self._last_flush = time.perf_counter()
            return
        text = "".join(self._buf)
        self._buf = []
        self._count = 0
        self._last_flush = time.perf_counter()
        if text:
            self._emitter.emit(token_event(self._chat_id, text, self._message_id))

    def feed(self, event: StreamEvent) -> None:
        """Route a stream event through the coalescer."""
        # Lazily capture chat/message ids from the first event seen so callers
        # can construct the coalescer before the ids are known.
        if not self._chat_id:
            self._chat_id = event.chat_id
        if not self._message_id:
            self._message_id = event.message_id

        if event.type == EVENT_TYPE_TOKEN:
            text = event.payload.get("text", "")
            if not self._started:
                # TTFT: the first token of a burst streams immediately. An empty
                # token doesn't consume the TTFT slot — leave it for the next
                # real token.
                if not text:
                    return
                self._started = True
                self._last_flush = time.perf_counter()
                self._emitter.emit(token_event(self._chat_id, text, self._message_id))
                return
            if text:
                self._buf.append(text)
                self._count += 1
            if (self._count >= _COALESCE_MAX_TOKENS
                    or (time.perf_counter() - self._last_flush) >= _COALESCE_MAX_INTERVAL_S):
                self._flush()
            return

        # Boundary event: flush any pending tokens, then pass through unchanged.
        # A boundary also ends the current burst so the next token gets its own
        # TTFT (the first word after a phase/tool boundary streams immediately).
        self._flush()
        self._started = False
        self._emitter.emit(event)

    def flush(self) -> None:
        """Flush any buffered tokens (call at end of stream if no done event)."""
        self._flush()


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
