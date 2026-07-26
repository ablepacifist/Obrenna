"""Codebase project pairings API: list, pair (create), update, and remove."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CodebaseProject
from ..schemas.api import CodebaseProjectCreateRequest, CodebaseProjectDTO, CodebaseProjectUpdateRequest
from ..services import codebase_projects as codebase_projects_svc

router = APIRouter(prefix="/api/codebase-projects", tags=["codebase-projects"])


def _to_dto(p: CodebaseProject) -> CodebaseProjectDTO:
    return CodebaseProjectDTO(
        id=p.id,
        name=p.name,
        device_id=p.device_id,
        root_path=p.root_path,
        write_enabled=p.write_enabled,
        enabled=p.enabled,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


@router.get("", response_model=list[CodebaseProjectDTO])
def list_projects(db: Session = Depends(get_db)):
    """List all paired codebase projects."""
    return [_to_dto(p) for p in codebase_projects_svc.list_codebase_projects(db)]


@router.post("", response_model=CodebaseProjectDTO)
async def create_project(payload: CodebaseProjectCreateRequest, db: Session = Depends(get_db)):
    """Register a folder on an already-approved, connected codebase-agent device."""
    try:
        project, error = await codebase_projects_svc.create_codebase_project(db, payload.model_dump(mode="json"))
        if error:
            raise HTTPException(status_code=400, detail=error)
        return _to_dto(project)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to pair codebase project: {exc}")


@router.patch("/{project_id}", response_model=CodebaseProjectDTO)
async def update_project(project_id: str, payload: CodebaseProjectUpdateRequest, db: Session = Depends(get_db)):
    """Update a codebase project's name/write-enabled/enabled state."""
    try:
        updates = payload.model_dump(mode="json", exclude_unset=True)
        project, error = await codebase_projects_svc.update_codebase_project(db, project_id, updates)
        if error:
            status_code = 404 if error == "Codebase project not found" else 400
            raise HTTPException(status_code=status_code, detail=error)
        return _to_dto(project)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update codebase project: {exc}")


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: Session = Depends(get_db)):
    """Unpair a codebase project."""
    try:
        ok = await codebase_projects_svc.delete_codebase_project(db, project_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Codebase project not found.")
        return {"deleted": True, "project_id": project_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete codebase project: {exc}")
