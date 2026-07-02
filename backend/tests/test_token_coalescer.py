"""Tests for the token coalescer (Fix #5).

The coalescer merges consecutive ``token`` events into fewer, larger token
envelopes so the Rust sidecar relays ~16x fewer Tauri events for long answers.
The first token of a turn emits immediately (TTFT); afterwards tokens flush as
one combined envelope at 16 tokens or 30ms. Any non-token event is a boundary:
it flushes pending tokens first, then passes through unchanged — different
event types are never merged.
"""
from __future__ import annotations

import time

from app.agent.emitter import TokenCoalescer
from app.agent.events import (
    StreamEvent,
    token_event,
    done_event,
    phase_event,
    thinking_delta_event,
)


class _RecordingEmitter:
    """Captures every emitted StreamEvent instead of writing to stdout."""

    def __init__(self):
        self.events: list[StreamEvent] = []

    def emit(self, event: StreamEvent) -> None:
        self.events.append(event)


def _token_envelopes(rec: _RecordingEmitter) -> list[StreamEvent]:
    return [e for e in rec.events if e.type == "token"]


class TestBatching:
    def test_first_token_emits_immediately_then_batches(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        for i in range(20):
            c.feed(token_event("c1", f"t{i} ", "m1"))
        envs = _token_envelopes(rec)
        # 1 immediate (TTFT) + 1 batch of 16; the trailing 3 stay buffered.
        assert len(envs) == 2, f"expected 2 token envelopes, got {len(envs)}"
        # First envelope is the single first token.
        assert envs[0].payload["text"] == "t0 "
        # Second envelope is the 16-token batch (t1..t16).
        assert envs[1].payload["text"] == " ".join(f"t{i}" for i in range(1, 17)) + " "
        # chat/message ids propagate onto coalesced envelopes.
        assert envs[0].chat_id == "c1"
        assert envs[0].message_id == "m1"

    def test_flush_emits_buffered_tail(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        for i in range(20):
            c.feed(token_event("c1", f"t{i} ", "m1"))
        assert len(_token_envelopes(rec)) == 2  # before flush
        c.flush()
        envs = _token_envelopes(rec)
        assert len(envs) == 3  # trailing 3 flushed as a 3rd envelope
        assert envs[2].payload["text"] == "t17 t18 t19 "

    def test_interval_flush(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        c.feed(token_event("c1", "first", "m1"))  # immediate (TTFT)
        # After the first token, a 30ms+ gap forces an interval flush on the
        # next token even though the count threshold (16) is far off.
        time.sleep(0.035)
        c.feed(token_event("c1", "second", "m1"))
        envs = _token_envelopes(rec)
        assert len(envs) == 2  # immediate + interval-flushed single token
        assert envs[1].payload["text"] == "second"


class TestBoundaries:
    def test_done_flushes_pending_then_passes_through(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        # 20 tokens then done: immediate + batch(16) + tail(3) flushed by done,
        # then the done event itself is emitted unchanged.
        for i in range(20):
            c.feed(token_event("c1", f"t{i} ", "m1"))
        c.feed(done_event("c1", "m1"))
        envs = _token_envelopes(rec)
        assert len(envs) == 3  # 1 + 16 + tail 3
        done = [e for e in rec.events if e.type == "done"]
        assert len(done) == 1
        # done comes AFTER the flushed tail envelope.
        assert rec.events.index(envs[2]) < rec.events.index(done[0])

    def test_single_token_then_done(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        c.feed(token_event("c1", "hello", "m1"))
        c.feed(done_event("c1", "m1"))
        envs = _token_envelopes(rec)
        assert len(envs) == 1
        assert envs[0].payload["text"] == "hello"
        assert [e.type for e in rec.events] == ["token", "done"]

    def test_phase_event_flushes_then_passes_unchanged(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        # First token immediate.
        c.feed(token_event("c1", "a", "m1"))
        # A few buffered tokens (below the 16 threshold).
        for ch in "bcd":
            c.feed(token_event("c1", ch, "m1"))
        # Boundary phase event flushes "bcd", then emits phase unchanged.
        c.feed(phase_event("c1", "m1", "workers", "Preparing"))
        envs = _token_envelopes(rec)
        assert len(envs) == 2  # "a" immediate + "bcd" flushed by the boundary
        assert envs[1].payload["text"] == "bcd"
        phase = [e for e in rec.events if e.type == "phase"]
        assert len(phase) == 1
        assert phase[0].payload.get("phase") == "workers"

    def test_different_event_types_are_never_merged(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        c.feed(token_event("c1", "a", "m1"))   # immediate token
        c.feed(thinking_delta_event("c1", "reason", "m1"))  # boundary
        c.feed(token_event("c1", "b", "m1"))   # first token of new burst → immediate
        types = [e.type for e in rec.events]
        # thinking_delta stays its own envelope, never merged with tokens.
        assert types == ["token", "thinking_delta", "token"]
        assert rec.events[1].payload.get("text") == "reason"


class TestEmptyAndIds:
    def test_empty_token_text_is_skipped(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec, chat_id="c1", message_id="m1")
        c.feed(token_event("c1", "", "m1"))  # first, but empty → no envelope
        c.feed(token_event("c1", "x", "m1"))  # first non-empty → immediate
        envs = _token_envelopes(rec)
        assert len(envs) == 1
        assert envs[0].payload["text"] == "x"

    def test_ids_captured_lazily_from_first_event(self):
        rec = _RecordingEmitter()
        c = TokenCoalescer(rec)  # no ids at construction
        c.feed(token_event("late_id_chat", "hi", "late_id_msg"))
        envs = _token_envelopes(rec)
        assert envs[0].chat_id == "late_id_chat"
        assert envs[0].message_id == "late_id_msg"