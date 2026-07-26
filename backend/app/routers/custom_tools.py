"""Custom API tools API: list, create, update, and delete user-defined tools."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CustomTool
from ..schemas.api import CustomToolCreateRequest, CustomToolDTO, CustomToolUpdateRequest
from ..services import custom_tools as custom_tools_svc

router = APIRouter(prefix="/api/custom-tools", tags=["custom-tools"])


def _to_dto(tool: CustomTool) -> CustomToolDTO:
    return CustomToolDTO(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        base_url=tool.base_url,
        http_method=tool.http_method,
        headers=tool.headers or {},
        params=tool.params or [],
        enabled=tool.enabled,
        created_at=tool.created_at.isoformat(),
        updated_at=tool.updated_at.isoformat(),
    )


@router.get("", response_model=list[CustomToolDTO])
def list_tools(db: Session = Depends(get_db)):
    """List all custom API tools."""
    return [_to_dto(t) for t in custom_tools_svc.list_custom_tools(db)]


@router.post("", response_model=CustomToolDTO)
def create_tool(payload: CustomToolCreateRequest, db: Session = Depends(get_db)):
    """Register a new custom API tool."""
    try:
        tool, error = custom_tools_svc.create_custom_tool(
            db, payload.model_dump(mode="json")
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return _to_dto(tool)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create custom tool: {exc}")


@router.patch("/{tool_id}", response_model=CustomToolDTO)
def update_tool(tool_id: str, payload: CustomToolUpdateRequest, db: Session = Depends(get_db)):
    """Update a custom API tool."""
    try:
        updates = payload.model_dump(mode="json", exclude_unset=True)
        tool, error = custom_tools_svc.update_custom_tool(db, tool_id, updates)
        if error:
            status_code = 404 if error == "Custom tool not found" else 400
            raise HTTPException(status_code=status_code, detail=error)
        return _to_dto(tool)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update custom tool: {exc}")


@router.delete("/{tool_id}")
def delete_tool(tool_id: str, db: Session = Depends(get_db)):
    """Remove a custom API tool."""
    try:
        ok = custom_tools_svc.delete_custom_tool(db, tool_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Custom tool not found.")
        return {"deleted": True, "tool_id": tool_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete custom tool: {exc}")
