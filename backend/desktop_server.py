"""Obrenna backend desktop launcher.

Starts the FastAPI app on a specific port for the Tauri desktop shell.
Must be run with OBRENNA_DATA_DIR and OBRENNA_PORT set.
"""
import os
import sys
import logging

# Support old GREBGLOB_* env vars as fallback for backwards compatibility
for old, new in [
    ("GREBGLOB_DATA_DIR", "OBRENNA_DATA_DIR"),
    ("GREBGLOB_PORT", "OBRENNA_PORT"),
    ("GREBGLOB_HOST", "OBRENNA_HOST"),
    ("GREBGLOB_DESKTOP", "OBRENNA_DESKTOP"),
]:
    if new not in os.environ and old in os.environ:
        os.environ[new] = os.environ[old]

# Ensure data dir is set before any imports that trigger config/db initialization
if "OBRENNA_DATA_DIR" not in os.environ:
    data_dir = os.path.join(
        os.path.expanduser("~"),
        "AppData",
        "Roaming",
        "Obrenna" if sys.platform == "win32" else "Obrenna",
    )
    os.environ["OBRENNA_DATA_DIR"] = data_dir

import uvicorn


def _configure_logging() -> str:
    level_name = os.getenv("OBRENNA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if os.getenv("OBRENNA_TRACE_LOGS") == "1":
        logging.getLogger("app.trace").setLevel(logging.INFO)
    return level_name.lower()


_LOG_LEVEL = _configure_logging()

from main import app  # noqa: E402

if __name__ == "__main__":
    host = os.getenv("OBRENNA_HOST", "127.0.0.1")
    port = int(os.getenv("OBRENNA_PORT", "8000"))

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=_LOG_LEVEL,
    )
