"""LIVE proof that the agent can BUILD and RUN a project from a prompt.

This is the "just like Claude Code" test: give the real model one prompt, let it
write files AND run commands through the real dispatch chain, then — independently
of anything the model claims — verify the project actually works by running it
ourselves and checking the output.

Task: build FizzBuzz (1..15) and run it. FizzBuzz is a good probe because the
correct output is exact and unambiguous, so "it works" is checkable, not a
matter of opinion.

Run:  DIAG_N=3 python scripts/live_build_and_run_probe.py
Needs Ollama at :11434 with the distilled model.
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

MODEL = os.getenv("PROBE_MODEL", "kwangsuklee/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled-GGUF")
TOOL_MODE = os.getenv("PROBE_TOOL_MODE", "prompt_json")

TASK = (
    "In this project, create a Python script named fizzbuzz.py that prints the "
    "numbers from 1 to 15, one per line, except: for multiples of 3 print 'Fizz', "
    "for multiples of 5 print 'Buzz', and for multiples of both 3 and 5 print "
    "'FizzBuzz'. Then run it with codebase_run_command to make sure it works, and "
    "fix it if the output is wrong."
)

EXPECTED = ["1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8", "Fizz", "Buzz",
            "11", "Fizz", "13", "14", "FizzBuzz"]


class _Conn:
    def __init__(self):
        from codebase_agent.dispatch import dispatch
        self._d = dispatch

    async def send_command(self, op, params, timeout: float = 30.0):
        return await asyncio.to_thread(self._d, op, params)


def _setup(work: Path) -> Path:
    root = work / "proj"
    root.mkdir()
    import codebase_agent.projects as psvc
    import codebase_agent.storage as storage
    dd = work / ".agent"
    dd.mkdir()
    storage.DATA_DIR = dd
    storage.PROJECTS_FILE = dd / "p.json"
    psvc.PROJECTS_FILE = dd / "p.json"
    psvc.ensure_data_dir = lambda: dd.mkdir(exist_ok=True)
    ap = psvc.register_project("proj", str(root), write_enabled=True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine)
    with TS() as s:
        s.add(CodebaseAgentDevice(device_id="d1", name="d", approved=True, enabled=True))
        p = CodebaseProject(name="proj", device_id="d1", root_path=str(root),
                            remote_project_id=ap.id, write_enabled=True, enabled=True)
        s.add(p)
        s.flush()
        s.add(Chat(id="c1", title="t", active_codebase_project_id=p.id))
        s.commit()
    ctd.SessionLocal = TS
    conn = _Conn()
    ctd.get_codebase_agent_hub = lambda: type("H", (), {"get": lambda self, d: conn})()
    ctd._read_ledger.clear()
    return root


async def run_turn(root: Path):
    cfg = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1",
                        models={"orchestrator": MODEL})
    plan = ResolvedPlan({"ctx": 8192, "orchestrator": {
        "model": MODEL, "tool_call_mode": TOOL_MODE,
        "reasoning_distilled": (TOOL_MODE == "prompt_json" and "coder" not in MODEL),
        "max_tool_rounds": 8, "keep_alive": -1,
        "stream_timeout_seconds": int(os.getenv("PROBE_TIMEOUT", "600")),
    }})
    tool_calls: list[str] = []
    ran_command = False
    async for ev in orchestrate_turn(TASK, "c1", None, cfg, plan,
                                     workers_enabled=False, thinking_enabled=True):
        if ev.type == "tool_call":
            name = ev.payload.get("tool_name", "")
            tool_calls.append(name)
            if name == "codebase_run_command":
                ran_command = True
    return tool_calls, ran_command


def _independent_verify(root: Path) -> tuple[bool, str]:
    """Ground truth: WE run the produced file and check the output ourselves,
    ignoring whatever the model said."""
    import subprocess
    fb = root / "fizzbuzz.py"
    if not fb.exists():
        return False, "fizzbuzz.py was not created"
    try:
        proc = subprocess.run([sys.executable, "fizzbuzz.py"], cwd=str(root),
                              capture_output=True, text=True, timeout=15,
                              stdin=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        return False, f"running it raised {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return False, f"exit={proc.returncode} stderr={proc.stderr[:200]!r}"
    got = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if got == EXPECTED:
        return True, "output exactly matches FizzBuzz 1..15"
    return False, f"wrong output: got {got}"


async def one_run(i: int) -> dict:
    work = Path(tempfile.mkdtemp(prefix="build_"))
    root = _setup(work)
    checks = []
    try:
        tool_calls, ran_command = await run_turn(root)
        wrote = "codebase_write_file" in tool_calls or "codebase_edit_file" in tool_calls
        works, detail = _independent_verify(root)
        print(f"  [run {i}] tools={tool_calls}")
        print(f"  [run {i}] wrote_file={wrote} ran_command={ran_command} WORKS={works} ({detail})")
        checks.append((f"run{i}: wrote a file", wrote, str(tool_calls)))
        checks.append((f"run{i}: ran a command", ran_command, str(tool_calls)))
        checks.append((f"run{i}: project actually works (independently verified)", works, detail))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"checks": checks}


async def main() -> int:
    n = int(os.getenv("DIAG_N", "3"))
    allc = []
    for i in range(1, n + 1):
        print(f"=== RUN {i}/{n} ===", flush=True)
        try:
            res = await one_run(i)
            allc.extend(res["checks"])
        except Exception as exc:  # noqa: BLE001
            print(f"  [run {i}] EXCEPTION {type(exc).__name__}: {exc}", flush=True)
            allc.append((f"run{i}: no exception", False, str(exc)))

    print("\n===== SUMMARY =====", flush=True)
    for name, ok, detail in allc:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"   -- {detail}"))
    works_checks = [c for c in allc if "actually works" in c[0]]
    n_works = sum(1 for _, ok, _ in works_checks if ok)
    print(f"\nPROJECT WORKS in {n_works}/{len(works_checks)} runs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
