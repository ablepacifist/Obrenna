"""Tests for the manual/plan-mode write gate and its pause/resume primitive.

The load-bearing property here is CROSS-LOOP resume: a turn awaits its approval
on the runtime's dedicated background loop, while the decision arrives on the
request loop. If ``resolve_approval`` ever goes back to a plain
``asyncio.Event.set()``, the waiter is never scheduled and the turn hangs until
its timeout -- which looks like "the app froze", not like a bug in a set() call.
``test_resolve_from_a_different_loop_wakes_the_waiter`` is the regression guard.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from app.agent import approvals, pending
from app.agent.approvals import (
    DECISION_APPROVE,
    DECISION_REJECT,
    create_approval,
    list_pending_for_chat,
    resolve_approval,
    wait_for_decision,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    """Approvals are process-global; don't let one test's entries leak."""
    pending._pending.clear()
    yield
    pending._pending.clear()


def test_create_then_resolve_approve():
    async def scenario():
        approval = await create_approval(
            chat_id="c1", message_id="m1", tool_name="codebase_edit_file",
            call_id="call_1", arguments={"path": "a.txt"},
        )
        assert list_pending_for_chat("c1") == [approval]
        resolve_approval(approval.request_id, DECISION_APPROVE)
        assert await wait_for_decision(approval, timeout=5) == DECISION_APPROVE
        # Spent: dropped from the registry so the id can't be reused.
        assert list_pending_for_chat("c1") == []

    asyncio.run(scenario())


def test_reject_is_returned():
    async def scenario():
        approval = await create_approval(
            chat_id="c1", message_id="m1", tool_name="codebase_write_file",
            call_id="call_1", arguments={},
        )
        resolve_approval(approval.request_id, DECISION_REJECT)
        assert await wait_for_decision(approval, timeout=5) == DECISION_REJECT

    asyncio.run(scenario())


def test_timeout_when_nobody_decides():
    async def scenario():
        approval = await create_approval(
            chat_id="c1", message_id="m1", tool_name="codebase_edit_file",
            call_id="call_1", arguments={},
        )
        # Timeout is treated as a refusal, and the entry is cleaned up so a
        # late decision can't execute a call the turn already moved past.
        assert await wait_for_decision(approval, timeout=0.05) == "timeout"
        assert list_pending_for_chat("c1") == []
        assert resolve_approval(approval.request_id, DECISION_APPROVE) is None

    asyncio.run(scenario())


def test_unknown_id_returns_none():
    assert resolve_approval("apr_does_not_exist", DECISION_APPROVE) is None


def test_invalid_decision_rejected():
    async def scenario():
        approval = await create_approval(
            chat_id="c1", message_id="m1", tool_name="codebase_edit_file",
            call_id="call_1", arguments={},
        )
        with pytest.raises(ValueError):
            resolve_approval(approval.request_id, "maybe")

    asyncio.run(scenario())


def test_resolve_from_a_different_loop_wakes_the_waiter():
    """The real topology: waiter on a background loop, resolver on another.

    This is what production does (turn on ``_SyncAsyncRunner``'s loop, HTTP
    handler on uvicorn's). A same-loop test would pass even with a plain
    ``Event.set()``, so only this one actually pins the behaviour.
    """
    turn_loop = asyncio.new_event_loop()
    threading.Thread(target=turn_loop.run_forever, daemon=True).start()
    created = threading.Event()
    holder: dict = {}

    async def turn():
        approval = await create_approval(
            chat_id="c-cross", message_id="m1", tool_name="codebase_edit_file",
            call_id="call_1", arguments={"path": "x.txt"},
        )
        holder["approval"] = approval
        created.set()
        # Short timeout on purpose: if the cross-loop wakeup is broken this
        # returns "timeout" and the assert below fails fast, instead of the
        # test hanging for the 600s production default.
        return await wait_for_decision(approval, timeout=5)

    fut = asyncio.run_coroutine_threadsafe(turn(), turn_loop)
    assert created.wait(timeout=5), "approval was never created"

    # Resolve from a *different* loop, mimicking the request handler.
    async def decide():
        return resolve_approval(holder["approval"].request_id, DECISION_APPROVE)

    assert asyncio.run(decide()) is not None
    assert fut.result(timeout=5) == DECISION_APPROVE

    turn_loop.call_soon_threadsafe(turn_loop.stop)


def test_cancel_chat_approvals_releases_waiters():
    turn_loop = asyncio.new_event_loop()
    threading.Thread(target=turn_loop.run_forever, daemon=True).start()
    created = threading.Event()
    holder: dict = {}

    async def turn():
        approval = await create_approval(
            chat_id="c-cancel", message_id="m1", tool_name="codebase_delete_file",
            call_id="call_1", arguments={},
        )
        holder["approval"] = approval
        created.set()
        return await wait_for_decision(approval, timeout=5)

    fut = asyncio.run_coroutine_threadsafe(turn(), turn_loop)
    assert created.wait(timeout=5)

    assert approvals.cancel_chat_approvals("c-cancel") == 1
    # An abandoned turn's waiter is released as a rejection, not left hanging.
    assert fut.result(timeout=5) == DECISION_REJECT

    turn_loop.call_soon_threadsafe(turn_loop.stop)


# ── The gate's effect on dispatch ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_call_is_not_dispatched():
    """A blocked call returns a non-retryable refusal without touching the MCP."""
    from app.agent.runtime import handle_tool_calls

    dispatched: list[str] = []

    class SpyClient:
        async def call_tool(self, name, args):
            dispatched.append(name)
            return {"ok": True}

    calls = [{
        "id": "call_blocked",
        "type": "function",
        "function": {"name": "web_search", "arguments": {"query": "x"}},
    }]
    results = await handle_tool_calls(
        calls, SpyClient(),
        blocked_calls={"call_blocked": "The user declined this change."},
    )

    assert dispatched == [], "a blocked call must never reach the dispatcher"
    body = json.loads(results[0]["content"])
    assert body["error"] is True
    assert body["retryable"] is False
    assert body["user_declined"] is True
    assert "declined" in body["message"]


@pytest.mark.asyncio
async def test_unblocked_calls_still_dispatch_and_keep_order():
    """Blocking one call must not disturb the others' 1:1 result alignment."""
    from app.agent.runtime import handle_tool_calls

    class SpyClient:
        async def call_tool(self, name, args):
            return {"tool": name}

    calls = [
        {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": {"query": "a"}}},
        {"id": "c2", "type": "function", "function": {"name": "web_search", "arguments": {"query": "b"}}},
        {"id": "c3", "type": "function", "function": {"name": "web_search", "arguments": {"query": "c"}}},
    ]
    results = await handle_tool_calls(
        calls, SpyClient(), blocked_calls={"c2": "declined"},
    )

    assert [r["tool_call_id"] for r in results] == ["c1", "c2", "c3"]
    assert json.loads(results[1]["content"])["user_declined"] is True
    for i in (0, 2):
        assert "user_declined" not in results[i]["content"]
