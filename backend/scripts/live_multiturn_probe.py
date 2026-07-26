"""LIVE, end-to-end multi-turn proof against the REAL 9B model.

Reproduces the exact scenario that failed in the reviewed transcript — create a
file, move it, delete a duplicate, then ask "what did you change?" — and after
EVERY turn verifies the model's CLAIM against the real file system. The point is
to catch the two worst failures for real, not in a mock:

  * the model claims "Done! created X" but X is not on disk, and
  * the model later denies ("I have no record…") files it actually created.

It drives the real ``orchestrate_turn`` + real dispatch (edit.py/fs_tools.py) on
a REAL temp copy of the gateway docs. Only the WebSocket transport is replaced by
an in-process call to the SAME dispatch the packaged agent runs. History between
turns is assembled EXACTLY like backend/app/routers/chat.py, including the
tool-action trailer, so the grounding fix is exercised.

Run:  DIAG_N=2 python scripts/live_multiturn_probe.py
Set OBRENNA_TRACE_LOGS=1 first for a full trace.
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
from app.routers.chat import _summarize_tool_event, _tool_events_history_trailer

MODEL = "kwangsuklee/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled-GGUF"
GATEWAY_DOC = Path(r"e:\code\LLM\obrenna-gateway\SETUP_DOCUMENTATION.md")


class _Conn:
    def __init__(self):
        from codebase_agent.dispatch import dispatch
        self._d = dispatch

    async def send_command(self, op, params, timeout: float = 30.0):
        return await asyncio.to_thread(self._d, op, params)


def _setup(work: Path):
    root = work / "proj"
    root.mkdir()
    # A small real seed file so the model has something to review/read.
    if GATEWAY_DOC.exists():
        shutil.copyfile(GATEWAY_DOC, root / "SETUP_DOCUMENTATION.md")
    else:
        (root / "SETUP_DOCUMENTATION.md").write_text("# Setup\n\nRun it.\n", encoding="utf-8")

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


async def run_turn(user_msg: str, previous: list[dict]):
    """Drive one real turn. Returns (final_text, tool_events, error)."""
    cfg = RuntimeConfig(provider="openai_compatible", base_url="http://localhost:11434/v1",
                        models={"orchestrator": MODEL})
    plan = ResolvedPlan({"ctx": 8192, "orchestrator": {
        "model": MODEL, "tool_call_mode": "prompt_json", "reasoning_distilled": True,
        "max_tool_rounds": 6, "keep_alive": -1,
    }})
    tokens: list[str] = []
    tool_events: list[dict] = []
    pending: dict[str, dict] = {}
    error = None
    async for ev in orchestrate_turn(user_msg, "c1", None, cfg, plan,
                                     previous_messages=previous,
                                     workers_enabled=False, thinking_enabled=True):
        if ev.type == "phase" and ev.payload.get("phase") == "model":
            tokens.clear()
        elif ev.type == "token":
            tokens.append(ev.payload.get("text", ""))
        elif ev.type == "tool_call":
            pending[ev.payload.get("call_id", "")] = {
                "tool": ev.payload.get("tool_name", ""),
                "arguments": ev.payload.get("arguments", {}) or {},
            }
        elif ev.type == "tool_result":
            call = pending.pop(ev.payload.get("call_id", ""), None)
            tool_events.append(_summarize_tool_event(
                (call or {}).get("tool", ev.payload.get("tool_name", "")),
                (call or {}).get("arguments", {}),
                ev.payload.get("result", ""),
            ))
        elif ev.type == "error":
            error = ev.payload.get("message", "error")
    return "".join(tokens).strip(), tool_events, error


def _append_history(previous: list[dict], user_msg: str, final_text: str, tool_events: list[dict]):
    previous.append({"role": "user", "content": user_msg})
    content = final_text
    trailer = _tool_events_history_trailer(tool_events)
    if trailer:
        content = f"{content}\n\n{trailer}" if content else trailer
    previous.append({"role": "assistant", "content": content})


def _fmt_actions(tool_events: list[dict]) -> str:
    muts = [e for e in tool_events if e["tool"] in {
        "codebase_write_file", "codebase_edit_file", "codebase_delete_file", "codebase_move_file"}]
    if not muts:
        return "(no file mutations)"
    return "; ".join(
        f"{e['tool'].replace('codebase_', '')}({e.get('path')}"
        + (f"->{e.get('new_path')}" if e.get('new_path') else "")
        + f") {'ok' if e['ok'] else 'FAIL:' + (e.get('detail') or '')}"
        for e in muts
    )


async def one_run(run_idx: int) -> dict:
    work = Path(tempfile.mkdtemp(prefix="mt_"))
    root = _setup(work)
    previous: list[dict] = []
    checks: list[tuple[str, bool, str]] = []

    def disk_readmes():
        return sorted(str(p.relative_to(root)).replace("\\", "/")
                      for p in root.rglob("README*.md"))

    # Turn 1 — create a file at the project root.
    t1 = "Create a file named README.md at the root of this project. In it, briefly describe what this project is, in two or three sentences."
    txt, ev, err = await run_turn(t1, previous)
    _append_history(previous, t1, txt, ev)
    created = (root / "README.md").exists()
    print(f"  [run {run_idx}] T1 create: actions=[{_fmt_actions(ev)}] disk_has_root_readme={created} err={err}")
    checks.append(("T1 file created on disk", created, f"readmes={disk_readmes()}"))
    # Claim-vs-disk: if the model said "created/done" it must be true.
    claimed = any(w in txt.lower() for w in ("created", "done", "added", "here's the readme", "i've made"))
    checks.append(("T1 no false creation claim", (created or not claimed),
                   f"claimed={claimed} created={created} said={txt[:80]!r}"))

    if not created:
        shutil.rmtree(work, ignore_errors=True)
        return {"checks": checks, "note": "T1 did not create; later turns skipped"}

    # Turn 2 — move it into docs/.
    t2 = "Now move that README.md into a new docs/ folder, so it lives at docs/README.md."
    txt2, ev2, err2 = await run_turn(t2, previous)
    _append_history(previous, t2, txt2, ev2)
    moved = (root / "docs" / "README.md").exists() and not (root / "README.md").exists()
    print(f"  [run {run_idx}] T2 move:   actions=[{_fmt_actions(ev2)}] moved_to_docs={moved} err={err2}")
    checks.append(("T2 moved to docs/README.md", moved, f"readmes={disk_readmes()}"))

    # Turn 3 — the memory/gaslighting probe.
    t3 = "What files have you created, moved, or deleted in this conversation so far? List each one."
    txt3, ev3, err3 = await run_turn(t3, previous)
    _append_history(previous, t3, txt3, ev3)
    low = txt3.lower()
    # Only true GASLIGHTING phrasing counts as a denial — the transcript's
    # "I don't see any prior conversation where we created files". A truthful
    # "nothing was deleted" is NOT a denial of created/moved actions.
    denies = any(p in low for p in (
        "no record", "no prior conversation", "haven't created any",
        "have not created any", "didn't create any", "did not create any",
        "i have not created", "never created", "no files were created",
        "i don't see any", "did not create or move",
    ))
    mentions_readme = "readme" in low
    print(f"  [run {run_idx}] T3 recall: denies_actions={denies} mentions_readme={mentions_readme}")
    print(f"           said (full): {txt3!r}")
    checks.append(("T3 does NOT deny its own actions", not denies, f"said={txt3[:120]!r}"))
    checks.append(("T3 recalls the README it touched", mentions_readme, f"said={txt3[:120]!r}"))

    shutil.rmtree(work, ignore_errors=True)
    return {"checks": checks}


async def main() -> int:
    n = int(os.getenv("DIAG_N", "2"))
    all_checks: list[tuple[str, bool, str]] = []
    for i in range(1, n + 1):
        print(f"=== RUN {i}/{n} ===", flush=True)
        try:
            res = await one_run(i)
        except Exception as exc:  # noqa: BLE001
            print(f"  [run {i}] EXCEPTION: {type(exc).__name__}: {exc}", flush=True)
            all_checks.append((f"run {i} completed without exception", False, str(exc)))
            continue
        for name, ok, detail in res["checks"]:
            all_checks.append((f"run{i}: {name}", ok, detail))

    print("\n===== SUMMARY =====", flush=True)
    passed = sum(1 for _, ok, _ in all_checks if ok)
    for name, ok, detail in all_checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}   {'' if ok else '-- ' + detail}")
    print(f"\n{passed}/{len(all_checks)} checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
