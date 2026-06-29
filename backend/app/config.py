"""Runtime configuration. Local-first: everything lives under a single data dir."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("OBRENNA_DATA_DIR", os.getenv("GREBGLOB_DATA_DIR", str(BACKEND_DIR / "data")))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
DB_PATH = DATA_DIR / "app.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

# Default local model endpoint (Ollama's OpenAI-compatible API).
DEFAULT_BASE_URL = "http://localhost:11434/v1"


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, ARTIFACTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
