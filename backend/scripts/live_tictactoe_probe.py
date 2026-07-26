"""LIVE test: can the agent build a working Tic-Tac-Toe game ON ITS OWN?

One prompt to the real model. It must write the code AND run it itself through
the real dispatch chain. Then — independently of anything the model claims — we
verify the win-detection logic it wrote is actually correct by running its
check_winner() against a battery of known boards (all rows, columns, both
diagonals, a draw, an empty board).

The interface (check_winner(board), board = 9 cells 'X'/'O'/' ') is specified in
the prompt so the correctness check is fair and not brittle — a real user
specifying an API. Everything else (how it builds the game, the demo, the board
rendering) is up to the model.

Run:  DIAG_N=3 python scripts/live_tictactoe_probe.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
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

TASK = (
    "Build a working Tic-Tac-Toe game in Python in a file named tictactoe.py at "
    "the project root. Requirements:\n"
    "- Include a function check_winner(board) where board is a list of 9 cells, "
    "each the string 'X', 'O', or ' ' (a space), indexed 0-8 left to right, top to "
    "bottom. It returns 'X' or 'O' if that player has three in a row (any row, "
    "column, or diagonal), otherwise it returns None.\n"
    "- When the file is run directly, play a short demo game between X and O and "
    "print the final board and who won.\n"
    "Then RUN it with codebase_run_command to make sure it executes without errors, "
    "and if there is any error, read it and fix the file, then run it again. Only "
    "tell me it's done once it runs cleanly."
)

# (board, expected) — covers every kind of win line, plus draw and empty.
CASES = [
    (['X', 'X', 'X', ' ', ' ', ' ', ' ', ' ', ' '], 'X'),   # top row
    ([' ', ' ', ' ', 'O', 'O', 'O', ' ', ' ', ' '], 'O'),   # middle row
    (['X', ' ', ' ', 'X', ' ', ' ', 'X', ' ', ' '], 'X'),   # left column
    ([' ', ' ', 'O', ' ', ' ', 'O', ' ', ' ', 'O'], 'O'),   # right column
    (['X', ' ', ' ', ' ', 'X', ' ', ' ', ' ', 'X'], 'X'),   # main diagonal
    ([' ', ' ', 'O', ' ', 'O', ' ', 'O', ' ', ' '], 'O'),   # anti diagonal
    (['X', 'O', 'X', 'O', 'X', 'O', 'O', 'X', 'O'], None),  # full board, draw
    ([' '] * 9, None),                                       # empty
]


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
        "model": MODEL, "tool_call_mode": "prompt_json", "reasoning_distilled": True,
        "max_tool_rounds": 10, "keep_alive": -1,
    }})
    tool_calls, ran = [], False
    async for ev in orchestrate_turn(TASK, "c1", None, cfg, plan,
                                     workers_enabled=False, thinking_enabled=True):
        if ev.type == "tool_call":
            n = ev.payload.get("tool_name", "")
            tool_calls.append(n)
            if n == "codebase_run_command":
                ran = True
    return tool_calls, ran


def _find_game(root: Path) -> Path | None:
    p = root / "tictactoe.py"
    if p.is_file():
        return p
    hits = [
        q for q in root.rglob("*.py")
        if q.is_file()
        and ".codebase-agent-backups" not in q.parts  # skip the agent's backup copies
        and "check_winner" in q.read_text(encoding="utf-8", errors="replace")
    ]
    return hits[0] if hits else None


def _independent_verify(root: Path) -> tuple[bool, str]:
    """Ground truth: run the model's OWN check_winner against known boards."""
    game = _find_game(root)
    if game is None:
        return False, "no tictactoe.py / check_winner found"

    # 1. It must at least run without crashing.
    try:
        demo = subprocess.run([sys.executable, game.name], cwd=str(game.parent),
                              capture_output=True, text=True, timeout=15,
                              stdin=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        return False, f"running it raised {type(exc).__name__}: {exc}"
    if demo.returncode != 0:
        return False, f"demo crashed: exit={demo.returncode} stderr={demo.stderr[:200]!r}"

    # 2. Its win-detection logic must be correct across the battery.
    import json
    checker = (
        "import json, sys\n"
        f"mod = __import__('{game.stem}')\n"
        f"cases = json.loads(r'''{json.dumps(CASES)}''')\n"
        "bad = []\n"
        "for board, exp in cases:\n"
        "    got = mod.check_winner(board)\n"
        "    got = got if got in ('X','O') else None\n"
        "    if got != exp: bad.append((board, exp, got))\n"
        "print('BAD=' + json.dumps(bad))\n"
        "sys.exit(1 if bad else 0)\n"
    )
    try:
        v = subprocess.run([sys.executable, "-c", checker], cwd=str(game.parent),
                           capture_output=True, text=True, timeout=15,
                           stdin=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        return False, f"verifier raised {type(exc).__name__}: {exc}"
    if v.returncode == 0:
        return True, "runs cleanly AND check_winner correct on all 8 boards"
    return False, f"check_winner wrong: {v.stdout.strip() or v.stderr[:200]!r}"


async def one_run(i: int) -> list[tuple]:
    work = Path(tempfile.mkdtemp(prefix="ttt_"))
    root = _setup(work)
    checks = []
    try:
        tool_calls, ran = await run_turn(root)
        wrote = any(t in tool_calls for t in ("codebase_write_file", "codebase_edit_file"))
        works, detail = _independent_verify(root)
        print(f"  [run {i}] tools={tool_calls}")
        print(f"  [run {i}] wrote={wrote} ran_command={ran} WORKS={works} ({detail})")
        checks.append((f"run{i}: wrote code", wrote, str(tool_calls)))
        checks.append((f"run{i}: ran it itself", ran, str(tool_calls)))
        checks.append((f"run{i}: game actually works (independently verified)", works, detail))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return checks


async def main() -> int:
    n = int(os.getenv("DIAG_N", "3"))
    allc = []
    for i in range(1, n + 1):
        print(f"=== RUN {i}/{n} ===", flush=True)
        try:
            allc.extend(await one_run(i))
        except Exception as exc:  # noqa: BLE001
            print(f"  [run {i}] EXCEPTION {type(exc).__name__}: {exc}", flush=True)
            allc.append((f"run{i}: no exception", False, str(exc)))

    print("\n===== SUMMARY =====", flush=True)
    for name, ok, detail in allc:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"   -- {detail}"))
    works = [c for c in allc if "actually works" in c[0]]
    nworks = sum(1 for _, ok, _ in works if ok)
    print(f"\nTIC-TAC-TOE WORKS in {nworks}/{len(works)} runs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
