"""Manual-mode write approval: a typed layer over the pending-request rendezvous.

The suspend/resume mechanism (and its cross-loop subtleties) lives in
``pending.py``; this module only adds the approval-specific vocabulary --
approve/reject, and the tool call being gated. ``ask_user`` questions share the
same primitive via ``questions.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .pending import (
    KIND_APPROVAL,
    TIMEOUT,
    PendingRequest,
    cancel_chat_pending,
    create_pending,
    get_pending,
    list_pending_for_chat as _list_pending,
    resolve_pending,
    wait_for_response,
)

logger = logging.getLogger(__name__)

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISION_TIMEOUT = "timeout"


async def create_approval(
    chat_id: str,
    message_id: str,
    tool_name: str,
    call_id: str,
    arguments: dict[str, Any],
) -> PendingRequest:
    """Register a write awaiting the user's verdict (does not wait)."""
    return await create_pending(
        KIND_APPROVAL, chat_id, message_id,
        {"tool_name": tool_name, "call_id": call_id, "arguments": arguments},
    )


async def wait_for_decision(approval: PendingRequest, timeout: float = 600.0) -> str:
    """Block until decided. Returns 'approve' | 'reject' | 'timeout'.

    A timeout is surfaced as its own value rather than silently as a rejection
    so callers/telemetry can tell "the user said no" from "nobody was there".
    Both are treated as *not approved* at the call site.
    """
    response = await wait_for_response(approval, timeout=timeout)
    if response is TIMEOUT or response is None:
        return DECISION_TIMEOUT
    return str(response)


def resolve_approval(approval_id: str, decision: str) -> Optional[PendingRequest]:
    """Record a decision and wake the suspended turn.

    Returns the request, or None if the id is unknown (already decided, timed
    out, or its turn ended). Callers should surface that as a 404.
    """
    if decision not in (DECISION_APPROVE, DECISION_REJECT):
        raise ValueError(f"invalid decision: {decision!r}")
    return resolve_pending(approval_id, decision, kind=KIND_APPROVAL)


def list_pending_for_chat(chat_id: str) -> list[PendingRequest]:
    """Approvals (only) currently blocking this chat's turn."""
    return _list_pending(chat_id, kind=KIND_APPROVAL)


def cancel_chat_approvals(chat_id: str) -> int:
    """Release every pending request for a chat as a rejection."""
    return cancel_chat_pending(chat_id, response=DECISION_REJECT)


# Re-exported so existing callers/tests keep a single import site.
__all__ = [
    "DECISION_APPROVE",
    "DECISION_REJECT",
    "DECISION_TIMEOUT",
    "PendingRequest",
    "cancel_chat_approvals",
    "create_approval",
    "get_pending",
    "list_pending_for_chat",
    "resolve_approval",
    "wait_for_decision",
]
