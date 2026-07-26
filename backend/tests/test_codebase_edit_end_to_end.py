"""End-to-end proof: the agent READS then EDITS a real file on disk.

Drives ``orchestrate_turn`` with a scripted two-tool sequence
(``codebase_read_file`` → ``codebase_edit_file``) through the REAL
tool-execution chain:

    runtime.handle_tool_calls
      → call_codebase_tool   (real read-before-write ledger + content-hash gate)
        → the REAL codebase-agent dispatch()  (edit.py / fs_tools.py)
          → a REAL file on disk

The ONLY things substituted are (1) the model's token stream — which must be
deterministic for a repeatable test — and (2) the WebSocket transport, replaced
by an in-process call to the exact same ``dispatch()`` the real agent runs. That
transport is not the code under test; everything that actually mutates the file
is real. A separate live-model smoke check (scripts/live_edit_proof.py) exercises
the real model end-to-end.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# The codebase-agent is a separate package (its own venv in the repo); make it
# importable so this test can drive the SAME dispatch the real agent runs.
_AGENT_ROOT = Path(__file__).resolve().parents[2] / "codebase-agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from app.agent import runtime as rt
from app.agent.runtime import ResolvedPlan, orchestrate_turn
from app.db import Base
from app.mcp import codebase_tool_dispatch as ctd
from app.model_runtime.config import RuntimeConfig
from app.models import Chat, CodebaseAgentDevice, CodebaseProject


class _InProcessConnection:
    """Stands in for the WebSocket DeviceConnection by running the SAME
    dispatch() the real codebase-agent runs, in-process, on a real temp dir."""

    def __init__(self) -> None:
        from codebase_agent.dispatch import dispatch

        self._dispatch = dispatch

    async def send_command(self, op, params, timeout: float = 20.0):
        # Mirror the real agent: filesystem work runs off the event loop.
        return await asyncio.to_thread(self._dispatch, op, params)


class _StubMemory:
    def to_static_messages(self):
        return []

    def to_dynamic_messages(self):
        return []


@pytest.mark.asyncio
async def test_agent_reads_then_edits_a_real_file(tmp_path, monkeypatch):
    # ── 1. a real project dir + file on disk ─────────────────────────────────
    project_root = tmp_path / "proj"
    project_root.mkdir()
    doc = project_root / "SETUP.md"
    original = "# Setup\n\nTODO: write the real setup instructions here.\n"
    doc.write_text(original, encoding="utf-8")

    old_str = "TODO: write the real setup instructions here."
    new_str = "Run `npm run dev` to start, and press Ctrl+C to stop."

    # ── 2. register the project on the AGENT side (real svc, temp storage) ───
    import codebase_agent.projects as projects_svc
    import codebase_agent.storage as storage

    data_dir = tmp_path / ".agent"
    data_dir.mkdir()
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "PROJECTS_FILE", data_dir / "projects.json")
    monkeypatch.setattr(projects_svc, "PROJECTS_FILE", data_dir / "projects.json")
    monkeypatch.setattr(projects_svc, "ensure_data_dir", lambda: data_dir.mkdir(exist_ok=True))
    agent_project = projects_svc.register_project("proj", str(project_root), write_enabled=True)

    # ── 3. backend DB: chat + approved device + project binding ──────────────
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    device_id = "dev-e2e-1"
    with TestSession() as s:
        s.add(CodebaseAgentDevice(device_id=device_id, name="test-dev", approved=True, enabled=True))
        proj = CodebaseProject(
            name="proj", device_id=device_id, root_path=str(project_root),
            remote_project_id=agent_project.id, write_enabled=True, enabled=True,
        )
        s.add(proj)
        s.flush()
        s.add(Chat(id="chat-e2e", title="edit test", active_codebase_project_id=proj.id))
        s.commit()

    # Point the codebase-tool dispatch at THIS db + an in-process agent conn.
    monkeypatch.setattr(ctd, "SessionLocal", TestSession)
    conn = _InProcessConnection()

    class _StubHub:
        def get(self, dev):
            return conn

    monkeypatch.setattr(ctd, "get_codebase_agent_hub", lambda: _StubHub())
    ctd._read_ledger.clear()  # start with a clean read-before-write ledger

    # ── 4. scripted model: round1 reads, round2 edits, round3 answers ────────
    rounds = iter([
        [{"type": "tool_calls_done", "calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "codebase_read_file", "arguments": {"path": "SETUP.md"}},
        }]}],
        [{"type": "tool_calls_done", "calls": [{
            "id": "c2", "type": "function",
            "function": {"name": "codebase_edit_file", "arguments": {
                "path": "SETUP.md", "old_string": old_str, "new_string": new_str,
            }},
        }]}],
        [{"type": "token", "content": "Done — I updated SETUP.md."}],
    ])

    async def fake_stream(config, messages, **kwargs):
        for ev in next(rounds):
            yield ev

    monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})

    config = RuntimeConfig(
        provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3.5:4b"},  # no utility model → narration no-ops
    )
    plan = ResolvedPlan({"orchestrator": {
        "model": "qwen3.5:4b", "tool_call_mode": "prompt_json", "max_tool_rounds": 4,
    }})

    # ── 5. run a real turn ───────────────────────────────────────────────────
    events = [e async for e in orchestrate_turn(
        "Fix SETUP.md: replace the TODO with real start/stop instructions.",
        "chat-e2e", None, config, plan, workers_enabled=False,
    )]

    # ── 6. the FILE ON DISK actually changed ─────────────────────────────────
    after = doc.read_text(encoding="utf-8")
    assert old_str not in after, f"TODO line should be gone. File is:\n{after}"
    assert new_str in after, f"new instructions should be present. File is:\n{after}"
    assert after == "# Setup\n\nRun `npm run dev` to start, and press Ctrl+C to stop.\n"

    # ── 7. both tools really executed against the real agent ────────────────
    result_events = [e for e in events if e.type == "tool_result"]
    names = [e.payload.get("tool_name") for e in result_events]
    assert "codebase_read_file" in names
    assert "codebase_edit_file" in names

    read_result = next(e for e in result_events if e.payload.get("tool_name") == "codebase_read_file")
    assert "TODO: write the real setup instructions here." in read_result.payload.get("result", "")

    edit_result = next(e for e in result_events if e.payload.get("tool_name") == "codebase_edit_file")
    assert "change_id" in edit_result.payload.get("result", "")  # real EditResult, not an error


@pytest.mark.asyncio
async def test_edit_is_blocked_until_the_file_is_read(tmp_path, monkeypatch):
    """The read-before-write ledger is REAL: an edit with no prior read is
    rejected with a retryable error and the file is left untouched."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    doc = project_root / "SETUP.md"
    original = "# Setup\n\nTODO: write the real setup instructions here.\n"
    doc.write_text(original, encoding="utf-8")

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
    device_id = "dev-e2e-2"
    with TestSession() as s:
        s.add(CodebaseAgentDevice(device_id=device_id, name="test-dev", approved=True, enabled=True))
        proj = CodebaseProject(
            name="proj", device_id=device_id, root_path=str(project_root),
            remote_project_id=agent_project.id, write_enabled=True, enabled=True,
        )
        s.add(proj)
        s.flush()
        s.add(Chat(id="chat-e2e-2", title="edit test", active_codebase_project_id=proj.id))
        s.commit()

    monkeypatch.setattr(ctd, "SessionLocal", TestSession)
    conn = _InProcessConnection()

    class _StubHub:
        def get(self, dev):
            return conn

    monkeypatch.setattr(ctd, "get_codebase_agent_hub", lambda: _StubHub())
    ctd._read_ledger.clear()

    # Edit WITHOUT a prior read.
    rounds = iter([
        [{"type": "tool_calls_done", "calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "codebase_edit_file", "arguments": {
                "path": "SETUP.md", "old_string": "TODO", "new_string": "DONE",
            }},
        }]}],
        [{"type": "token", "content": "I could not edit without reading first."}],
    ])

    async def fake_stream(config, messages, **kwargs):
        for ev in next(rounds):
            yield ev

    monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})

    config = RuntimeConfig(
        provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3.5:4b"},
    )
    plan = ResolvedPlan({"orchestrator": {
        "model": "qwen3.5:4b", "tool_call_mode": "prompt_json", "max_tool_rounds": 4,
    }})

    events = [e async for e in orchestrate_turn(
        "Edit SETUP.md.", "chat-e2e-2", None, config, plan, workers_enabled=False,
    )]

    # File is UNCHANGED, and the tool result told the model to read first.
    assert doc.read_text(encoding="utf-8") == original
    edit_result = next(
        e for e in events
        if e.type == "tool_result" and e.payload.get("tool_name") == "codebase_edit_file"
    )
    assert "codebase_read_file" in edit_result.payload.get("result", "")


class _RealProject:
    """Lightweight stand-in for a CodebaseProject row, carrying just the four
    attributes call_codebase_tool reads. remote_project_id points at the REAL
    agent-side project so dispatch mutates the REAL temp dir."""

    def __init__(self, *, remote_project_id, id, device_id, write_enabled=True):
        self.remote_project_id = remote_project_id
        self.id = id
        self.device_id = device_id
        self.write_enabled = write_enabled


def _wire_real_agent(tmp_path, monkeypatch, *, device_id):
    """Register a real agent-side project on a real temp dir + an in-process
    dispatch connection, and point call_codebase_tool's device lookup at it.
    Returns (project_root, remote_project_id)."""
    project_root = tmp_path / "proj"
    project_root.mkdir()

    import codebase_agent.projects as projects_svc
    import codebase_agent.storage as storage

    data_dir = tmp_path / ".agent"
    data_dir.mkdir()
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "PROJECTS_FILE", data_dir / "projects.json")
    monkeypatch.setattr(projects_svc, "PROJECTS_FILE", data_dir / "projects.json")
    monkeypatch.setattr(projects_svc, "ensure_data_dir", lambda: data_dir.mkdir(exist_ok=True))
    agent_project = projects_svc.register_project("proj", str(project_root), write_enabled=True)

    conn = _InProcessConnection()
    monkeypatch.setattr(ctd, "_get_connected_approved_device", lambda dev_id: (conn, None))
    ctd._read_ledger.clear()
    return project_root, agent_project.id


def test_strip_wrapping_code_fence():
    """Models wrap file content in ```lang ... ``` even when writing a raw file;
    that fence must be stripped so the .py file isn't invalid Python."""
    from app.mcp.codebase_tool_dispatch import _strip_wrapping_code_fence
    # Fenced whole-file content → stripped.
    assert _strip_wrapping_code_fence("```python\nprint(1)\n```") == "print(1)"
    assert _strip_wrapping_code_fence("```\nx = 1\n```") == "x = 1"
    assert _strip_wrapping_code_fence("```py\ndef f():\n    return 2\n```") == "def f():\n    return 2"
    # No fence → untouched.
    assert _strip_wrapping_code_fence("print(1)") == "print(1)"
    # A real markdown file (prose + an embedded block) is NOT a single wrapping
    # fence, so it must be left exactly as-is.
    md = "# Title\n\nSome text.\n\n```python\ncode()\n```\n\nMore text.\n"
    assert _strip_wrapping_code_fence(md) == md


@pytest.mark.asyncio
async def test_write_file_strips_wrapping_fence_end_to_end(tmp_path, monkeypatch):
    """The dispatch strips a wrapping fence before the file hits disk, so a
    fence-wrapped write produces VALID source, not a literal ```python line."""
    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-fence")
    proj = _RealProject(remote_project_id=rp, id="p-fence", device_id="d-fence")
    res = await ctd.call_codebase_tool("chat-fence", proj, "codebase_write_file", {
        "path": "app.py", "content": "```python\nprint('hi')\n```",
    })
    assert res.get("created") is True
    on_disk = (project_root / "app.py").read_text(encoding="utf-8")
    assert on_disk == "print('hi')"
    assert "```" not in on_disk


@pytest.mark.asyncio
async def test_delete_file_removes_from_disk_after_read(tmp_path, monkeypatch):
    """The whole point of the reviewed transcript: the model must be able to
    DELETE a duplicate file, and it must actually leave disk."""
    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-del")
    dup = project_root / "README.md"
    dup.write_text("duplicate readme\n", encoding="utf-8")
    proj = _RealProject(remote_project_id=rp, id="p-del", device_id="d-del")

    # A blind delete (no prior read) is refused, file stays.
    blocked = await ctd.call_codebase_tool("chat-del", proj, "codebase_delete_file", {"path": "README.md"})
    assert blocked.get("error") is True
    assert blocked.get("retryable") is True
    assert dup.exists()

    # After a read, the delete goes through and the file is gone.
    await ctd.call_codebase_tool("chat-del", proj, "codebase_read_file", {"path": "README.md"})
    ok = await ctd.call_codebase_tool("chat-del", proj, "codebase_delete_file", {"path": "README.md"})
    assert ok.get("deleted") is True
    assert ok.get("path") == "README.md"
    assert not dup.exists()
    # The ledger entry for the deleted path is dropped (a re-create would
    # need its own read again).
    assert ("chat-del", "p-del", "README.md") not in ctd._read_ledger


@pytest.mark.asyncio
async def test_move_file_relocates_on_disk_and_carries_ledger(tmp_path, monkeypatch):
    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-mv")
    src = project_root / "README.md"
    src.write_text("keeper\n", encoding="utf-8")
    proj = _RealProject(remote_project_id=rp, id="p-mv", device_id="d-mv")

    # Read first so the ledger has the source (proves it carries to the dest).
    await ctd.call_codebase_tool("chat-mv", proj, "codebase_read_file", {"path": "README.md"})
    res = await ctd.call_codebase_tool(
        "chat-mv", proj, "codebase_move_file",
        {"path": "README.md", "new_path": "docs/README.md"},
    )
    assert res.get("moved") is True
    assert not src.exists()
    assert (project_root / "docs" / "README.md").read_text(encoding="utf-8") == "keeper\n"
    # Ledger moved with the file: old key gone, new key present.
    assert ("chat-mv", "p-mv", "README.md") not in ctd._read_ledger
    assert ("chat-mv", "p-mv", "docs/README.md") in ctd._read_ledger


@pytest.mark.asyncio
async def test_edit_with_empty_old_string_rejected_before_agent(tmp_path, monkeypatch):
    """The fake-deletion footgun: old_string="" is rejected at the dispatch
    layer with a retryable error that names the right tools, and never reaches
    the agent (so it can't no-op-succeed)."""
    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-empty")
    doc = project_root / "SETUP.md"
    doc.write_text("keep me\n", encoding="utf-8")
    proj = _RealProject(remote_project_id=rp, id="p-empty", device_id="d-empty")

    await ctd.call_codebase_tool("chat-empty", proj, "codebase_read_file", {"path": "SETUP.md"})
    res = await ctd.call_codebase_tool(
        "chat-empty", proj, "codebase_edit_file",
        {"path": "SETUP.md", "old_string": "", "new_string": "", "replace_all": True},
    )
    assert res.get("error") is True
    assert res.get("retryable") is True
    assert "codebase_delete_file" in res.get("message", "")
    # File untouched — no fake success.
    assert doc.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.asyncio
async def test_agent_writes_then_runs_a_script_through_real_dispatch(tmp_path, monkeypatch):
    """The coding-agent loop: write a file with codebase_write_file, then RUN it
    with codebase_run_command, and get the real program output back. Proves the
    new execution capability end-to-end through the same dispatch the packaged
    agent runs."""
    import sys

    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-run")
    proj = _RealProject(remote_project_id=rp, id="p-run", device_id="d-run")

    # 1. the model writes a script
    w = await ctd.call_codebase_tool("chat-run", proj, "codebase_write_file", {
        "path": "fib.py",
        "content": "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n\nprint(fib(10))\n",
    })
    assert w.get("created") is True
    assert (project_root / "fib.py").exists()

    # 2. the model runs it and gets the real output
    r = await ctd.call_codebase_tool("chat-run", proj, "codebase_run_command", {
        "command": f'"{sys.executable}" fib.py',
    })
    assert r.get("error") is not True, f"run failed: {r}"
    assert r.get("exit_code") == 0
    assert r.get("stdout", "").strip() == "55"  # fib(10) == 55


@pytest.mark.asyncio
async def test_run_command_reports_failure_not_success(tmp_path, monkeypatch):
    """A script that crashes must come back with a non-zero exit_code and the
    traceback in stderr — so the model can see it failed and fix it, instead of
    falsely reporting success."""
    import sys

    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-fail")
    proj = _RealProject(remote_project_id=rp, id="p-fail", device_id="d-fail")

    await ctd.call_codebase_tool("chat-fail", proj, "codebase_write_file", {
        "path": "broken.py", "content": "raise ValueError('nope')\n",
    })
    r = await ctd.call_codebase_tool("chat-fail", proj, "codebase_run_command", {
        "command": f'"{sys.executable}" broken.py',
    })
    assert r.get("exit_code") not in (0, None)
    assert "ValueError" in r.get("stderr", "")


@pytest.mark.asyncio
async def test_run_command_blocked_when_write_disabled(tmp_path, monkeypatch):
    """Execution is gated at the same level as editing: a read-only project
    cannot run commands."""
    project_root, rp = _wire_real_agent(tmp_path, monkeypatch, device_id="d-ro")
    proj = _RealProject(remote_project_id=rp, id="p-ro", device_id="d-ro", write_enabled=False)

    r = await ctd.call_codebase_tool("chat-ro", proj, "codebase_run_command", {"command": "echo hi"})
    assert r.get("error") is True
    assert "disabled" in r.get("message", "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path_arg", [{"path": ""}, {"path": None}, {}])
async def test_empty_or_missing_path_normalizes_to_project_root(path_arg, monkeypatch):
    """A model listing/searching the project commonly sends path="" (meaning
    "the whole project"). The agent rejects "" as "Invalid path", failing the
    model's first exploratory call. call_codebase_tool must normalize empty /
    None / missing path to the root ("."), not pass "" through."""
    captured = {}

    class _Conn:
        async def send_command(self, op, params, timeout: float = 20.0):
            captured["op"] = op
            captured["params"] = params
            return {"entries": []}

    monkeypatch.setattr(ctd, "_get_connected_approved_device", lambda dev_id: (_Conn(), None))

    class _Proj:
        remote_project_id = "rp1"
        id = "p1"
        device_id = "d1"
        write_enabled = True

    result = await ctd.call_codebase_tool("chat1", _Proj(), "codebase_list_directory", dict(path_arg))
    assert "error" not in result
    assert captured["params"]["path"] == "."
