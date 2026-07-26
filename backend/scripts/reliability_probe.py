"""Measure how RELIABLY the orchestrator emits a tool call vs. just narrating.

Runs the same read task N times through the real runtime + live model and reports,
per tool_call_mode, how many runs actually called a codebase tool. This is the
head-to-head prompt_json vs openai_native reliability number — the thing that
determines whether the model "can see files."

Run:  DIAG_N=5 python scripts/reliability_probe.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
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
REAL_DOC = Path(r"e:\code\LLM\obrenna-gateway\SETUP_DOCUMENTATION.md")
TASK = ("Review this project. Read SETUP_DOCUMENTATION.md and tell me what the "
        "project does and how to change its configuration.")


class _Conn:
    def __init__(self):
        from codebase_agent.dispatch import dispatch
        self._d = dispatch

    async def send_command(self, op, params, timeout: float = 30.0):
        return await asyncio.to_thread(self._d, op, params)


def _setup(work: Path):
    root = work / "proj"; root.mkdir()
    shutil.copyfile(REAL_DOC, root / "SETUP_DOCUMENTATION.md")
    import codebase_agent.projects as psvc
    import codebase_agent.storage as storage
    dd = work / ".agent"; dd.mkdir()
    storage.DATA_DIR = dd; storage.PROJECTS_FILE = dd / "p.json"
    psvc.PROJECTS_FILE = dd / "p.json"; psvc.ensure_data_dir = lambda: dd.mkdir(exist_ok=True)
    ap = psvc.register_project("proj", str(root), write_enabled=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine); TS = sessionmaker(bind=engine)
    with TS() as s:
        s.add(CodebaseAgentDevice(device_id="d1", name="d", approved=True, enabled=True))
        p = CodebaseProject(name="proj", device_id="d1", root_path=str(root),
                            remote_project_id=ap.id, write_enabled=True, enabled=True)
        s.add(p); s.flush()
        s.add(Chat(id="c1", title="t", active_codebase_project_id=p.id)); s.commit()
    ctd.SessionLocal = TS
    conn = _Conn()
    ctd.get_codebase_agent_hub = lambda: type("H", (), {"get": lambda self, d: conn})()
    ctd._read_ledger.clear()


async def run_once(mode: str) -> bool:
    cfg = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1",
                        models={"orchestrator": MODEL})
    plan = ResolvedPlan({"ctx": 8192, "orchestrator": {
        "model": MODEL, "tool_call_mode": mode, "reasoning_distilled": True,
        "max_tool_rounds": 5, "keep_alive": -1,
    }})
    called = False
    async for ev in orchestrate_turn(TASK, "c1", None, cfg, plan,
                                     workers_enabled=False, thinking_enabled=True):
        if ev.type == "tool_call" and (ev.payload.get("tool_name") or "").startswith("codebase_"):
            called = True
    return called


async def main() -> int:
    n = int(os.getenv("DIAG_N", "5"))
    work = Path(tempfile.mkdtemp(prefix="rel_"))
    _setup(work)
    for mode in ("prompt_json", "openai_native"):
        hits = 0
        marks = []
        for i in range(n):
            ok = await run_once(mode)
            hits += 1 if ok else 0
            marks.append("Y" if ok else "N")
            print(f"  [{mode}] run {i+1}/{n}: {'CALLED TOOL' if ok else 'narrated (no tool)'}", flush=True)
        print(f"RESULT {mode:15s}: {hits}/{n} runs called a codebase tool   [{' '.join(marks)}]", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
