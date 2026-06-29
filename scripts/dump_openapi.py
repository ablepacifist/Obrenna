"""Dump the backend FastAPI OpenAPI document to a file without running a server.

Usage: python scripts/dump_openapi.py <output.json>
Imported by scripts/codegen.mjs to generate frontend API types.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "openapi.json"
    try:
        from main import app  # type: ignore
    except Exception as exc:  # pragma: no cover - best effort
        print(f"could not import backend app: {exc}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
