"""Local file storage helpers (uploads + generated artifacts)."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from ..config import ARTIFACTS_DIR, UPLOADS_DIR, ensure_dirs


def save_upload(file_obj, original_name: str) -> tuple[str, Path, int]:
    """Persist an uploaded file to the uploads dir. Returns (file_id, path, size)."""
    ensure_dirs()
    file_id = uuid.uuid4().hex
    safe_name = Path(original_name).name or "upload"
    dest = UPLOADS_DIR / f"{file_id}__{safe_name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file_obj, out)
    return file_id, dest, dest.stat().st_size


async def save_upload_async(file_obj, original_name: str) -> tuple[str, Path, int]:
    """Async variant for FastAPI UploadFile objects."""
    ensure_dirs()
    file_id = uuid.uuid4().hex
    safe_name = Path(original_name).name or "upload"
    dest = UPLOADS_DIR / f"{file_id}__{safe_name}"
    with dest.open("wb") as out:
        content = await file_obj.read()
        out.write(content)
    return file_id, dest, dest.stat().st_size


def artifact_pdf_path(artifact_id: str) -> Path:
    ensure_dirs()
    return ARTIFACTS_DIR / f"{artifact_id}.pdf"
