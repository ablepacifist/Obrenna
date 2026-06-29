"""GrebGlob backend desktop launcher.

Starts the FastAPI app on a specific port for the Tauri desktop shell.
Must be run with GREBGLOB_DATA_DIR and GREBGLOB_PORT set.
"""
import os
import sys

# Ensure data dir is set before any imports that trigger config/db initialization
if "GREBGLOB_DATA_DIR" not in os.environ:
    data_dir = os.path.join(
        os.path.expanduser("~"),
        "AppData",
        "Roaming",
        "GrebGlob" if sys.platform == "win32" else "GrebGlob",
    )
    os.environ["GREBGLOB_DATA_DIR"] = data_dir

import uvicorn

from main import app  # noqa: E402

if __name__ == "__main__":
    host = os.getenv("GREBGLOB_HOST", "127.0.0.1")
    port = int(os.getenv("GREBGLOB_PORT", "8000"))

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level="info",
    )
