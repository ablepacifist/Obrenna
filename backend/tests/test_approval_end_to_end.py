"""End-to-end proof of the manual/plan write gate against a REAL file on disk.

Same harness as ``test_codebase_edit_end_to_end`` (only the model's token stream
and the WebSocket transport are substituted; everything that mutates the file is
real), extended to cover the gate:

  * manual + approve  -> turn suspends, then the file really changes
  * manual + reject   -> file untouched, model told it was declined
  * plan              -> file untouched, no approval even requested
  * auto              -> unchanged behaviour (regression guard)

The manual cases prove the SUSPENSION is real: the approving task only runs
after the turn is observed to be blocked on ``approval_request``, so a gate that
failed to actually wait would let the edit land before the approval and fail the
ordering assertion.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_AGENT_ROOT = Path(__file__).resolve().parents[2] / "codebase-agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from app.agent import approvals, pending
from app.agent import runtime as rt
from app.agent.approvals import DECISION_APPROVE, DECISION_REJECT, resolve_approval
from app.agent.runtime import ResolvedPlan, orchestrate_turn
from app.db import Base
from app.mcp import codebase_tool_dispatch as ctd
from app.model_runtime.config import RuntimeConfig
from app.models import Chat, CodebaseAgentDevice, CodebaseProject

ORIGINAL = "# Setup\n\nTODO: write the real setup instructions here.\n"
OLD_STR = "TODO: write the real setup instructions here."
NEW_STR = "Run `npm run dev` to start, and press Ctrl+C to stop."


class _InProcessConnection:
    """Runs the SAME dispatch() the real codebase-agent runs, in-process."""

    def __init__(self) -> None:
        from codebase_agent.dispatch import dispatch
        self._dispatch = dispatch

    async def send_command(self, op, params, timeout: float = 20.0):
        return await asyncio.to_thread(self._dispatch, op, params)


class _StubMemory:
    def to_static_messages(self):
        return []

    def to_dynamic_messages(self):
        return []


def _build_world(tmp_path, monkeypatch, chat_id: str, agent_mode: str):
    """Real project dir + file, agent-side registration, DB rows. Returns the doc path."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    doc = project_root / "SETUP.md"
    doc.write_text(ORIGINAL, encoding="utf-8")

    import codebase_agent.projects as projects_svc
    import codebase_agent.storage as storage

    data_dir = tmp_path / ".agent"
    data_dir.mkdir()
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "PROJECTS_FILE", data_dir / "projects.json")
    monkeypatch.setattr(projects_svc, "PROJECTS_FILE", data_dir / "projects.json")
    monkeypatch.setattr(projects_svc, "ensure_data_dir", lambda: data_dir.mkdir(exist_ok=True))
    agent_project = projects_svc.register_project("proj", str(project_root), write_enabled=True)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    device_id = f"dev-{chat_id}"
    with TestSession() as s:
        s.add(CodebaseAgentDevice(device_id=device_id, name="test-dev", approved=True, enabled=True))
        proj = CodebaseProject(
            name="proj", device_id=device_id, root_path=str(project_root),
            remote_project_id=agent_project.id, write_enabled=True, enabled=True,
        )
        s.add(proj)
        s.flush()
        s.add(Chat(id=chat_id, title="gate test",
                   active_codebase_project_id=proj.id, agent_mode=agent_mode))
        s.commit()

    monkeypatch.setattr(ctd, "SessionLocal", TestSession)
    conn = _InProcessConnection()

    class _StubHub:
        def get(self, dev):
            return conn

    monkeypatch.setattr(ctd, "get_codebase_agent_hub", lambda: _StubHub())
    ctd._read_ledger.clear()
    return doc


def _script_read_then_edit(monkeypatch):
    """Model: round1 reads (satisfies the read-before-write ledger), round2 edits."""
    rounds = iter([
        [{"type": "tool_calls_done", "calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "codebase_read_file", "arguments": {"path": "SETUP.md"}},
        }]}],
        [{"type": "tool_calls_done", "calls": [{
            "id": "c2", "type": "function",
            "function": {"name": "codebase_edit_file", "arguments": {
                "path": "SETUP.md", "old_string": OLD_STR, "new_string": NEW_STR,
            }},
        }]}],
        [{"type": "token", "content": "Done."}],
    ])

    async def fake_stream(config, messages, **kwargs):
        for ev in next(rounds):
            yield ev

    monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})


def _config_and_plan():
    config = RuntimeConfig(
        provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3.5:4b"},
    )
    plan = ResolvedPlan({"orchestrator": {
        "model": "qwen3.5:4b", "tool_call_mode": "prompt_json", "max_tool_rounds": 4,
    }})
    return config, plan


@pytest.fixture(autouse=True)
def _clear_registry():
    pending._pending.clear()
    yield
    pending._pending.clear()


@pytest.mark.asyncio
async def test_manual_mode_suspends_then_applies_on_approve(tmp_path, monkeypatch):
    doc = _build_world(tmp_path, monkeypatch, "chat-manual-ok", "manual")
    _script_read_then_edit(monkeypatch)
    config, plan = _config_and_plan()

    events = []
    file_when_asked: list[str] = []

    async def consume():
        async for ev in orchestrate_turn(
            "Fix SETUP.md.", "chat-manual-ok", None, config, plan,
            workers_enabled=False, agent_mode="manual",
        ):
            events.append(ev)
            if ev.type == "approval_request":
                # The turn is blocked right now. Snapshot the file, then decide.
                file_when_asked.append(doc.read_text(encoding="utf-8"))
                resolve_approval(ev.payload["approval_id"], DECISION_APPROVE)

    await asyncio.wait_for(consume(), timeout=30)

    # Exactly one approval, and it was for the edit (not the read).
    reqs = [e for e in events if e.type == "approval_request"]
    assert len(reqs) == 1, f"expected 1 approval, got {[e.payload for e in reqs]}"
    assert reqs[0].payload["tool_name"] == "codebase_edit_file"
    # The diff the UI needs travels with the event.
    assert reqs[0].payload["arguments"]["old_string"] == OLD_STR
    assert reqs[0].payload["arguments"]["new_string"] == NEW_STR

    # SUSPENSION WAS REAL: file still original at the moment we were asked.
    assert file_when_asked == [ORIGINAL]

    # ...and the approved edit then really landed on disk.
    after = doc.read_text(encoding="utf-8")
    assert after == "# Setup\n\nRun `npm run dev` to start, and press Ctrl+C to stop.\n"

    resolved = [e for e in events if e.type == "approval_resolved"]
    assert [e.payload["decision"] for e in resolved] == [DECISION_APPROVE]


@pytest.mark.asyncio
async def test_manual_mode_reject_leaves_file_untouched(tmp_path, monkeypatch):
    doc = _build_world(tmp_path, monkeypatch, "chat-manual-no", "manual")
    _script_read_then_edit(monkeypatch)
    config, plan = _config_and_plan()

    events = []

    async def consume():
        async for ev in orchestrate_turn(
            "Fix SETUP.md.", "chat-manual-no", None, config, plan,
            workers_enabled=False, agent_mode="manual",
        ):
            events.append(ev)
            if ev.type == "approval_request":
                resolve_approval(ev.payload["approval_id"], DECISION_REJECT)

    await asyncio.wait_for(consume(), timeout=30)

    assert doc.read_text(encoding="utf-8") == ORIGINAL, "a rejected edit must not touch the file"

    # The model is told it was declined, non-retryably, so it can't loop on it.
    edit_results = [
        e for e in events
        if e.type == "tool_result" and e.payload.get("tool_name") == "codebase_edit_file"
    ]
    assert len(edit_results) == 1
    body = json.loads(edit_results[0].payload["result"])
    assert body["user_declined"] is True
    assert body["retryable"] is False


@pytest.mark.asyncio
async def test_plan_mode_refuses_without_asking(tmp_path, monkeypatch):
    doc = _build_world(tmp_path, monkeypatch, "chat-plan", "plan")
    _script_read_then_edit(monkeypatch)
    config, plan = _config_and_plan()

    events = [e async for e in orchestrate_turn(
        "Fix SETUP.md.", "chat-plan", None, config, plan,
        workers_enabled=False, agent_mode="plan",
    )]

    assert doc.read_text(encoding="utf-8") == ORIGINAL, "plan mode must not write"
    # Refused outright — the user is never prompted in plan mode.
    assert [e for e in events if e.type == "approval_request"] == []

    edit_results = [
        e for e in events
        if e.type == "tool_result" and e.payload.get("tool_name") == "codebase_edit_file"
    ]
    assert len(edit_results) == 1
    body = json.loads(edit_results[0].payload["result"])
    assert body["error"] is True
    assert "plan mode" in body["message"].lower()

    # Reads are still allowed, so a plan can be grounded in the real code.
    read_results = [
        e for e in events
        if e.type == "tool_result" and e.payload.get("tool_name") == "codebase_read_file"
    ]
    assert len(read_results) == 1
    assert OLD_STR in read_results[0].payload["result"]


@pytest.mark.asyncio
async def test_auto_mode_is_unchanged(tmp_path, monkeypatch):
    """Regression guard: the default path must not have grown a prompt."""
    doc = _build_world(tmp_path, monkeypatch, "chat-auto", "auto")
    _script_read_then_edit(monkeypatch)
    config, plan = _config_and_plan()

    events = [e async for e in orchestrate_turn(
        "Fix SETUP.md.", "chat-auto", None, config, plan,
        workers_enabled=False, agent_mode="auto",
    )]

    assert [e for e in events if e.type == "approval_request"] == []
    assert doc.read_text(encoding="utf-8") == "# Setup\n\nRun `npm run dev` to start, and press Ctrl+C to stop.\n"
