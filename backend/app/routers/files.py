import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import File as FileModel
from ..schemas.api import FileDTO
from ..services import csv_profiler
from ..services.storage import save_upload_async

router = APIRouter(prefix="/api/files")


@router.post("/upload", response_model=FileDTO)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    file_id, stored_path, size_bytes = await save_upload_async(file, file.filename)

    content_type = file.content_type or "application/octet-stream"
    row_count = None
    columns: list[str] = []

    if file.filename.lower().endswith(".csv"):
        try:
            df = csv_profiler.load_csv(str(stored_path))
            row_count = len(df)
            columns = [str(c) for c in df.columns]
        except Exception:
            pass

    record = FileModel(
        id=file_id,
        filename=file.filename,
        stored_path=str(stored_path),
        content_type=content_type,
        size_bytes=size_bytes,
        row_count=row_count,
        columns=columns,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return FileDTO(
        id=record.id,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        row_count=record.row_count,
        columns=record.columns or [],
        created_at=record.created_at.isoformat(),
    )
