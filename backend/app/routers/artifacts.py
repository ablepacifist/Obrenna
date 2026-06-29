from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..graphs import run_csv_dashboard
from ..models import Artifact, File
from ..schemas.api import ArtifactResponse, DashboardFromCsvRequest, ExportPdfResponse
from ..services.pdf_export import export_artifact_pdf
from ..services.storage import artifact_pdf_path

router = APIRouter(prefix="/api/artifacts")


def _save_artifact_to_db(spec: dict, db: Session) -> str:
    record = Artifact(
        id=spec["id"],
        artifact_type=spec["artifact_type"],
        title=spec["title"],
        summary=spec.get("summary"),
        source_file_id=spec.get("source_file_id"),
        spec=spec["spec"],
    )
    db.add(record)
    db.commit()
    return record.id


@router.post("/dashboard-from-csv", response_model=ArtifactResponse)
def dashboard_from_csv(payload: DashboardFromCsvRequest, db: Session = Depends(get_db)):
    file_record = db.get(File, payload.file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    def save_fn(spec: dict) -> str:
        return _save_artifact_to_db(spec, db)

    state = run_csv_dashboard(
        file_path=file_record.stored_path,
        file_id=file_record.id,
        filename=file_record.filename,
        instruction=payload.instruction,
        save_fn=save_fn,
    )

    artifact_id = state.get("artifact_id")
    if not artifact_id:
        raise HTTPException(status_code=500, detail="Artifact generation failed.")

    record = db.get(Artifact, artifact_id)
    full_spec = {
        "id": record.id,
        "artifact_type": record.artifact_type,
        "title": record.title,
        "summary": record.summary,
        "source_file_id": record.source_file_id,
        "created_at": record.created_at.isoformat(),
        "spec": record.spec,
    }
    return ArtifactResponse(artifact_id=artifact_id, artifact=full_spec)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
    record = db.get(Artifact, artifact_id)
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    full_spec = {
        "id": record.id,
        "artifact_type": record.artifact_type,
        "title": record.title,
        "summary": record.summary,
        "source_file_id": record.source_file_id,
        "created_at": record.created_at.isoformat(),
        "spec": record.spec,
    }
    return ArtifactResponse(artifact_id=record.id, artifact=full_spec)


@router.post("/{artifact_id}/export/pdf", response_model=ExportPdfResponse)
def export_pdf(artifact_id: str, db: Session = Depends(get_db)):
    record = db.get(Artifact, artifact_id)
    if not record:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    pdf_path = artifact_pdf_path(artifact_id)
    full_spec = {
        "id": record.id,
        "artifact_type": record.artifact_type,
        "title": record.title,
        "summary": record.summary,
        "source_file_id": record.source_file_id,
        "created_at": record.created_at.isoformat(),
        "spec": record.spec,
    }

    export_artifact_pdf(full_spec, pdf_path)

    record.pdf_path = str(pdf_path)
    db.commit()

    return ExportPdfResponse(
        artifact_id=artifact_id,
        download_path=str(pdf_path),
        filename=pdf_path.name,
    )


@router.get("/{artifact_id}/export/pdf/download")
def download_pdf(artifact_id: str, db: Session = Depends(get_db)):
    record = db.get(Artifact, artifact_id)
    if not record or not record.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found. Export first.")
    return FileResponse(
        record.pdf_path,
        media_type="application/pdf",
        filename=f"{artifact_id}.pdf",
    )
