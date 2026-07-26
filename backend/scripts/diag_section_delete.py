"""Diagnostic: watch EXACTLY what the model sends for a large section-delete edit.

Copies the real SETUP_DOCUMENTATION.md into a temp project and asks the model to
remove the Troubleshooting section, printing every codebase_edit_file old_string
and the agent's result — so we can see why the edit doesn't land and fix it.
"""
from __future__ import annotations

import asyncio
import json
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


class _Conn:
    def __init__(self):
        from codebase_agent.dispatch import dispatch
        self._d = dispatch

    async def send_command(self, op, params, timeout: float = 30.0):
        return await asyncio.to_thread(self._d, op, params)


async def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="diag_"))
    root = work / "proj"; root.mkdir()
    doc = root / "SETUP_DOCUMENTATION.md"
    shutil.copyfile(REAL_DOC, doc)
    before = doc.read_text(encoding="utf-8")

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

    cfg = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1",
                        models={"orchestrator": MODEL})
    import os
    _mode = os.getenv("DIAG_TOOL_MODE", "prompt_json")
    plan = ResolvedPlan({"ctx": 8192, "orchestrator": {
        "model": MODEL, "tool_call_mode": _mode, "reasoning_distilled": True,
        "max_tool_rounds": 6, "keep_alive": -1,
    }})
    print(f"[tool_call_mode={_mode}]")

    msg = ("Read SETUP_DOCUMENTATION.md, then use codebase_edit_file to delete the "
           "entire Troubleshooting section (the '## Troubleshooting' heading and the "
           "whole table under it). Leave the rest of the file unchanged.")

    print(f"file has {before.count(chr(10))+1} lines; CRLF={'YES' if chr(13) in before else 'no'}\n")
    n_edit = 0
    n_call = 0
    tokens = []
    think_chars = 0
    async for ev in orchestrate_turn(msg, "c1", None, cfg, plan,
                                     workers_enabled=False, thinking_enabled=True):
        if ev.type == "tool_call":
            n_call += 1
            name = ev.payload.get("tool_name")
            args = ev.payload.get("arguments") or {}
            if name == "codebase_edit_file":
                n_edit += 1
                print(f"--- EDIT ATTEMPT #{n_edit} ---")
                print("  old_string:", repr(args.get("old_string"))[:400])
                print("  new_string:", repr(args.get("new_string"))[:200])
            else:
                print(f"[call] {name} {json.dumps(args)[:120]}")
        elif ev.type == "tool_result":
            if ev.payload.get("tool_name") == "codebase_edit_file":
                print("  RESULT:", ev.payload.get("result", "")[:200])
                print()
        elif ev.type == "token":
            tokens.append(ev.payload.get("text", ""))
        elif ev.type == "thinking_delta":
            think_chars += len(ev.payload.get("text", ""))
    print(f"\n[total tool_calls={n_call}, thinking_chars={think_chars}]")
    print("ASSISTANT TEXT:", ("".join(tokens))[:500])

    after = doc.read_text(encoding="utf-8")
    print("=" * 60)
    print("file changed:", after != before, "| troubleshooting gone:", "## Troubleshooting" not in after)
    print(f"edit attempts made: {n_edit}")
    return 0 if after != before else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
