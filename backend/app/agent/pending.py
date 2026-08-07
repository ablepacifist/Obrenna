"""Cross-loop rendezvous for suspending a turn on user input.

Two features need the same thing: a running turn stops, the user is asked
something, and the turn resumes with their response. Manual-mode write approval
needs it (approve/reject); the ``ask_user`` tool needs it (a free-text answer).
The mechanism is identical and it is the subtle part, so it lives here once
rather than being reimplemented per feature.

CROSS-LOOP BY CONSTRUCTION -- the reason this module looks the way it does: the
turn does not run on the request loop. Sync endpoints hand the coroutine to
``model_runtime.client._run``, which drives it on a dedicated background event
loop (``_SyncAsyncRunner``, its own thread). FastAPI's handlers run on uvicorn's
main loop. So the waiter and the resolver are on *different* event loops in
*different* threads. Consequences, both load-bearing:

  * ``asyncio.Lock`` is bound to the loop that created it -- unusable across the
    two. The registry is guarded by a ``threading.Lock`` instead.
  * ``asyncio.Event.set()`` is not thread-safe. Called from the request loop it
    would flip the flag but never schedule the waiter's wakeup on the loop that
    owns it, so the turn would sit until its timeout instead of resuming --
    which presents as "the app froze", not as a bug in a set() call. Every
    wakeup therefore goes through ``loop.call_soon_threadsafe`` on the loop
    captured when the request was created.

``tests/test_approval_gate.py::test_resolve_from_a_different_loop_wakes_the_waiter``
is the regression guard for that second point; it fails with a plain ``set()``.

Deliberately in-process and in-memory. The awaiting coroutine holds live
orchestrator state (message history, an open tool call) that cannot be
serialised and handed to another process, so a pending request is only
meaningful inside the process running that turn -- persisting it would be a lie.
This assumes a SINGLE backend worker, which is how the app runs. Under multiple
workers a response could land on a worker that isn't hosting the turn and would
404; that needs a shared broker plus per-turn worker affinity, not a DB table.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Kinds of suspension. Kept as plain strings so events/DTOs stay JSON-simple.
KIND_APPROVAL = "approval"
KIND_QUESTION = "question"

# How long a suspended turn waits before giving up. Generous: a human reading a
# diff (or answering a question) is slow, and the SSE heartbeat keeps the
# stream alive meanwhile. Callers decide what a timeout *means* for them.
DEFAULT_TIMEOUT_S = 600.0

TIMEOUT = "__timeout__"


@dataclass
class PendingRequest:
    """One turn suspended awaiting user input."""

    request_id: str
    kind: str
    chat_id: str
    message_id: str
    # Everything the UI needs to render the prompt (tool name, args, question
    # text, options...). Opaque here; each feature defines its own shape.
    payload: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    # Whatever the user sent back. Shape is per-kind: a decision string for
    # approvals, an answer string for questions.
    response: Any = None
    # The Event and the loop that owns it are created together, on the turn's
    # loop, inside create_pending -- never lazily, since a lazy create could
    # happen on the resolver's loop and bind the Event to the wrong one.
    _event: Optional[asyncio.Event] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "payload": self.payload,
            "created_at": self.created_at,
        }


# request_id -> PendingRequest. Guarded by a threading.Lock (not asyncio) --
# see the cross-loop note in the module docstring.
_pending: dict[str, PendingRequest] = {}
_lock = threading.Lock()


def _new_id(kind: str) -> str:
    prefix = "apr" if kind == KIND_APPROVAL else "qst"
    return f"{prefix}_" + uuid.uuid4().hex[:16]


async def create_pending(
    kind: str,
    chat_id: str,
    message_id: str,
    payload: dict[str, Any],
) -> PendingRequest:
    """Register a suspension and return it (does not wait).

    Must be awaited ON THE TURN'S LOOP: the Event binds to whatever loop is
    running here, and that is the loop the wakeup will be scheduled onto.
    """
    req = PendingRequest(
        request_id=_new_id(kind),
        kind=kind,
        chat_id=chat_id,
        message_id=message_id,
        payload=payload,
    )
    req._event = asyncio.Event()
    req._loop = asyncio.get_running_loop()
    with _lock:
        _pending[req.request_id] = req
    logger.info("Pending %s %s created for chat=%s", kind, req.request_id, chat_id)
    return req


async def wait_for_response(
    req: PendingRequest,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Any:
    """Block until resolved or ``timeout`` elapses.

    Returns the response, or the ``TIMEOUT`` sentinel. Either way the request is
    dropped from the registry, so a late resolve can't act on a turn that has
    already moved past this point.
    """
    assert req._event is not None, "request was not created via create_pending()"
    try:
        await asyncio.wait_for(req._event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        req.response = TIMEOUT
        logger.warning(
            "Pending %s %s timed out after %.0fs", req.kind, req.request_id, timeout,
        )
    finally:
        with _lock:
            _pending.pop(req.request_id, None)
    return req.response if req.response is not None else TIMEOUT


def resolve_pending(request_id: str, response: Any, *, kind: str | None = None) -> Optional[PendingRequest]:
    """Record a user response and wake the suspended turn.

    Sync on purpose: it does no awaiting, and it is called from the request loop
    while the waiter sleeps on the turn's loop. The wakeup is marshalled onto
    the owning loop via ``call_soon_threadsafe``.

    ``kind`` optionally asserts the request is the type the caller expects, so
    a question id can't be resolved through the approval endpoint.

    Returns the request on success, or None if the id is unknown -- already
    resolved, timed out, or its turn ended (e.g. backend restarted).
    """
    with _lock:
        req = _pending.get(request_id)
    if req is None:
        logger.warning("Pending %s not found (already resolved or expired)", request_id)
        return None
    if kind is not None and req.kind != kind:
        logger.warning("Pending %s is a %s, not a %s", request_id, req.kind, kind)
        return None
    req.response = response
    _wake(req)
    logger.info("Pending %s %s resolved", req.kind, request_id)
    return req


def _wake(req: PendingRequest) -> None:
    """Set the request's Event on the loop that owns it."""
    event, loop = req._event, req._loop
    if event is None:
        return
    if loop is None or loop.is_closed():
        # No owning loop to schedule onto (shouldn't happen); set directly so a
        # same-loop waiter still proceeds rather than hanging.
        event.set()
        return
    try:
        loop.call_soon_threadsafe(event.set)
    except RuntimeError:
        # Loop shut down between the check and the call -- the turn is gone, so
        # there is nothing left to wake.
        logger.debug("Pending %s: owning loop gone, nothing to wake", req.request_id)


def get_pending(request_id: str) -> Optional[PendingRequest]:
    with _lock:
        return _pending.get(request_id)


def list_pending_for_chat(chat_id: str, kind: str | None = None) -> list[PendingRequest]:
    """Pending requests for a chat.

    Lets a client that reconnected mid-turn (refresh, or the Tauri window
    reopening) re-render the card it would otherwise have missed, instead of
    showing a turn that looks stuck.
    """
    with _lock:
        return [
            r for r in _pending.values()
            if r.chat_id == chat_id and (kind is None or r.kind == kind)
        ]


def cancel_chat_pending(chat_id: str, response: Any = TIMEOUT) -> int:
    """Release every pending request for a chat. Used when a turn is abandoned.

    Without this, a turn that errored out while suspended would leave its entry
    behind and the UI would keep showing a live-looking prompt.
    """
    with _lock:
        victims = [r for r in _pending.values() if r.chat_id == chat_id]
    for r in victims:
        r.response = response
        _wake(r)
    return len(victims)
