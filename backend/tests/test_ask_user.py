"""Tests for the ask_user clarifying-question tool.

Covers the same two properties the approval gate needs, since both ride the
same rendezvous: the turn genuinely SUSPENDS while waiting, and it resumes with
the answer fed back as the tool's result.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from app.agent import pending
from app.agent import runtime as rt
from app.agent.questions import (
    ASK_USER_TOOL_DEF,
    ASK_USER_TOOL_NAME,
    NO_ANSWER,
    create_question,
    list_pending_for_chat,
    resolve_question,
    wait_for_answer,
)
from app.agent.runtime import ResolvedPlan, orchestrate_turn


@pytest.fixture(autouse=True)
def _clear_registry():
    pending._pending.clear()
    yield
    pending._pending.clear()


class _StubMemory:
    def to_static_messages(self):
        return []

    def to_dynamic_messages(self):
        return []


def test_tool_def_shape_matches_the_allowlist_convention():
    """Flat name/description/inputSchema — NOT the OpenAI nested envelope.

    ``_format_tools_for_model`` raises on an entry with no top-level name, and
    on one with neither a TOOL_DEFS entry nor an inline ``inputSchema``. Getting
    this wrong breaks EVERY turn, not just ones that ask a question, so it is
    worth pinning directly.
    """
    assert ASK_USER_TOOL_DEF["name"] == ASK_USER_TOOL_NAME
    assert "inputSchema" in ASK_USER_TOOL_DEF
    assert "parameters" not in ASK_USER_TOOL_DEF
    assert ASK_USER_TOOL_DEF["inputSchema"]["required"] == ["question"]
    # It must survive the real formatter.
    formatted = rt._format_tools_for_model([ASK_USER_TOOL_DEF])
    assert formatted[0]["function"]["name"] == ASK_USER_TOOL_NAME


def test_answer_round_trip():
    async def scenario():
        q = await create_question(
            chat_id="c1", message_id="m1", call_id="call_1",
            question="Which file?", options=["a.py", "b.py"],
        )
        assert list_pending_for_chat("c1") == [q]
        resolve_question(q.request_id, "a.py")
        assert await wait_for_answer(q, timeout=5) == "a.py"
        assert list_pending_for_chat("c1") == []

    asyncio.run(scenario())


def test_no_answer_times_out_to_none():
    async def scenario():
        q = await create_question(
            chat_id="c1", message_id="m1", call_id="call_1", question="Which file?",
        )
        assert await wait_for_answer(q, timeout=0.05) is None

    asyncio.run(scenario())


def test_blank_answer_rejected():
    async def scenario():
        q = await create_question(
            chat_id="c1", message_id="m1", call_id="call_1", question="Which file?",
        )
        with pytest.raises(ValueError):
            resolve_question(q.request_id, "   ")

    asyncio.run(scenario())


def test_question_id_cannot_be_resolved_as_an_approval():
    """Kind is enforced, so the two endpoints can't cross-resolve each other."""
    from app.agent.approvals import resolve_approval

    async def scenario():
        q = await create_question(
            chat_id="c1", message_id="m1", call_id="call_1", question="Which file?",
        )
        assert resolve_approval(q.request_id, "approve") is None
        # Still pending — the bogus resolve didn't consume it.
        assert list_pending_for_chat("c1") == [q]

    asyncio.run(scenario())


def test_answer_from_a_different_loop_wakes_the_waiter():
    """Cross-loop resume, same topology as production (see pending.py)."""
    turn_loop = asyncio.new_event_loop()
    threading.Thread(target=turn_loop.run_forever, daemon=True).start()
    created = threading.Event()
    holder: dict = {}

    async def turn():
        q = await create_question(
            chat_id="c-cross", message_id="m1", call_id="call_1", question="Which?",
        )
        holder["q"] = q
        created.set()
        return await wait_for_answer(q, timeout=5)

    fut = asyncio.run_coroutine_threadsafe(turn(), turn_loop)
    assert created.wait(timeout=5)

    async def answer():
        return resolve_question(holder["q"].request_id, "the second one")

    assert asyncio.run(answer()) is not None
    assert fut.result(timeout=5) == "the second one"
    turn_loop.call_soon_threadsafe(turn_loop.stop)


# ── Through the real orchestrator ────────────────────────────────────────────


def _script_ask_then_answer(monkeypatch):
    rounds = iter([
        [{"type": "tool_calls_done", "calls": [{
            "id": "q1", "type": "function",
            "function": {"name": ASK_USER_TOOL_NAME, "arguments": {
                "question": "Which file did you mean?",
                "options": ["src/a.py", "src/b.py"],
            }},
        }]}],
        [{"type": "token", "content": "Got it."}],
    ])

    async def fake_stream(config, messages, **kwargs):
        for ev in next(rounds):
            yield ev

    monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})


def _config_and_plan():
    from app.model_runtime.config import RuntimeConfig
    config = RuntimeConfig(
        provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3.5:4b"},
    )
    plan = ResolvedPlan({"orchestrator": {
        "model": "qwen3.5:4b", "tool_call_mode": "prompt_json", "max_tool_rounds": 4,
    }})
    return config, plan


@pytest.mark.asyncio
async def test_turn_suspends_on_ask_user_and_feeds_the_answer_back(monkeypatch):
    _script_ask_then_answer(monkeypatch)
    config, plan = _config_and_plan()

    events = []
    answered_at: list[bool] = []

    async def consume():
        async for ev in orchestrate_turn(
            "Fix the bug.", "chat-ask", None, config, plan, workers_enabled=False,
        ):
            events.append(ev)
            if ev.type == "question_request":
                # The turn is blocked here: no tool_result for this call yet.
                answered_at.append(
                    any(e.type == "tool_result" and e.payload.get("call_id") == "q1"
                        for e in events)
                )
                resolve_question(ev.payload["question_id"], "src/b.py")

    await asyncio.wait_for(consume(), timeout=30)

    reqs = [e for e in events if e.type == "question_request"]
    assert len(reqs) == 1
    assert reqs[0].payload["question"] == "Which file did you mean?"
    assert reqs[0].payload["options"] == ["src/a.py", "src/b.py"]

    # SUSPENSION WAS REAL: the call had produced no result when we were asked.
    assert answered_at == [False]

    resolved = [e for e in events if e.type == "question_resolved"]
    assert [e.payload["answer"] for e in resolved] == ["src/b.py"]

    # The answer is fed back as this call's tool result, so the model continues
    # with it in context rather than re-asking.
    results = [e for e in events if e.type == "tool_result" and e.payload.get("call_id") == "q1"]
    assert len(results) == 1
    assert "src/b.py" in results[0].payload["result"]
    # ...and it is NOT an error payload, unlike a declined write.
    assert "user_declined" not in results[0].payload["result"]


@pytest.mark.asyncio
async def test_unanswered_question_tells_the_model_to_assume(monkeypatch):
    _script_ask_then_answer(monkeypatch)
    config, plan = _config_and_plan()
    # Make the wait expire immediately instead of sitting for 600s.
    monkeypatch.setattr(rt, "wait_for_answer", lambda q, **kw: _none())

    async def _none():
        return None

    events = [e async for e in orchestrate_turn(
        "Fix the bug.", "chat-ask-timeout", None, config, plan, workers_enabled=False,
    )]

    results = [e for e in events if e.type == "tool_result" and e.payload.get("call_id") == "q1"]
    assert len(results) == 1
    # It must not leave the model hanging — it gets an explicit instruction.
    assert results[0].payload["result"] == NO_ANSWER


@pytest.mark.asyncio
async def test_empty_question_is_refused_without_suspending(monkeypatch):
    """A malformed call must not park the turn on an empty prompt."""
    rounds = iter([
        [{"type": "tool_calls_done", "calls": [{
            "id": "q1", "type": "function",
            "function": {"name": ASK_USER_TOOL_NAME, "arguments": {"question": "   "}},
        }]}],
        [{"type": "token", "content": "ok"}],
    ])

    async def fake_stream(config, messages, **kwargs):
        for ev in next(rounds):
            yield ev

    monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})
    config, plan = _config_and_plan()

    events = [e async for e in orchestrate_turn(
        "Fix the bug.", "chat-ask-empty", None, config, plan, workers_enabled=False,
    )]

    assert [e for e in events if e.type == "question_request"] == []
    results = [e for e in events if e.type == "tool_result" and e.payload.get("call_id") == "q1"]
    assert len(results) == 1
    assert "non-empty" in results[0].payload["result"]
