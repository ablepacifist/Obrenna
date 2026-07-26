"""LIVE proof: the REAL local model reads and edits a REAL file on disk.

Unlike tests/test_codebase_edit_end_to_end.py (which scripts the model output for
determinism), this drives the ACTUAL orchestrator model through the real
streaming + tool loop + real codebase-agent dispatch, and prints the file before
and after. Nothing about the model's decisions is scripted.

Run:  python scripts/live_edit_proof.py
Requires Ollama running with the orchestrator model available.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
_AGENT_ROOT = Path(__file__).resolve().parents[2] / "codebase-agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.runtime import ResolvedPlan, orchestrate_turn
from app.db import Base
from app.mcp import codebase_tool_dispatch as ctd
from app.model_runtime.config import RuntimeConfig
from app.models import Chat, CodebaseAgentDevice, CodebaseProject

MODEL = "kwangsuklee/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled-GGUF"


class _InProcessConnection:
    def __init__(self):
        from codebase_agent.dispatch import dispatch
        self._dispatch = dispatch

    async def send_command(self, op, params, timeout: float = 30.0):
        return await asyncio.to_thread(self._dispatch, op, params)


async def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="obrenna_live_edit_"))
    project_root = workdir / "proj"
    project_root.mkdir()
    doc = project_root / "SETUP.md"
    original = (
        "# Project Setup\n\n"
        "## Start\n\n"
        "TODO: document how to start the app.\n\n"
        "## Stop\n\n"
        "TODO: document how to stop the app.\n"
    )
    doc.write_text(original, encoding="utf-8")

    # Agent-side project registration (real service, temp storage).
    import codebase_agent.projects as projects_svc
    import codebase_agent.storage as storage
    data_dir = workdir / ".agent"
    data_dir.mkdir()
    storage.DATA_DIR = data_dir
    storage.PROJECTS_FILE = data_dir / "projects.json"
    projects_svc.PROJECTS_FILE = data_dir / "projects.json"
    projects_svc.ensure_data_dir = lambda: data_dir.mkdir(exist_ok=True)
    agent_project = projects_svc.register_project("proj", str(project_root), write_enabled=True)

    # Backend DB.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    device_id = "dev-live-1"
    with TestSession() as s:
        s.add(CodebaseAgentDevice(device_id=device_id, name="live", approved=True, enabled=True))
        proj = CodebaseProject(
            name="proj", device_id=device_id, root_path=str(project_root),
            remote_project_id=agent_project.id, write_enabled=True, enabled=True,
        )
        s.add(proj); s.flush()
        s.add(Chat(id="chat-live", title="live", active_codebase_project_id=proj.id))
        s.commit()

    ctd.SessionLocal = TestSession
    conn = _InProcessConnection()
    ctd.get_codebase_agent_hub = lambda: type("H", (), {"get": lambda self, d: conn})()
    ctd._read_ledger.clear()

    config = RuntimeConfig(
        provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": MODEL},
    )
    plan = ResolvedPlan({
        "ctx": 8192,
        "orchestrator": {
            "model": MODEL, "tool_call_mode": "prompt_json",
            "reasoning_distilled": True, "max_tool_rounds": 5, "keep_alive": -1,
        },
    })

    print("=" * 70)
    print("FILE BEFORE:")
    print("-" * 70)
    print(doc.read_text(encoding="utf-8"))
    print("=" * 70)

    user_msg = (
        "Read SETUP.md, then edit it: under '## Start', replace the TODO line "
        "with `Run npm run dev` and under '## Stop' replace the TODO line with "
        "`Press Ctrl+C`. Make the edits to the file."
    )
    print(f"USER: {user_msg}\n")

    tool_events = []
    final_text = []
    async for ev in orchestrate_turn(
        user_msg, "chat-live", None, config, plan,
        workers_enabled=False, thinking_enabled=True,
    ):
        if ev.type == "tool_call":
            tool_events.append(("call", ev.payload.get("tool_name"), ev.payload.get("arguments")))
        elif ev.type == "tool_result":
            tool_events.append(("result", ev.payload.get("tool_name"), ev.payload.get("result", "")[:200]))
        elif ev.type == "token":
            final_text.append(ev.payload.get("text", ""))

    print("TOOL ACTIVITY:")
    for kind, name, extra in tool_events:
        print(f"  [{kind}] {name}: {str(extra)[:160]}")
    print()
    print("ASSISTANT:", "".join(final_text)[:500])
    print("=" * 70)

    after = doc.read_text(encoding="utf-8")
    print("FILE AFTER:")
    print("-" * 70)
    print(after)
    print("=" * 70)

    changed = after != original
    todo_gone = "TODO" not in after
    print(f"\nRESULT: file changed = {changed} | all TODOs replaced = {todo_gone}")
    if changed:
        print(">>> The live model edited a real file on disk. <<<")
        return 0
    print(">>> File unchanged — the model did not complete the edit. <<<")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
