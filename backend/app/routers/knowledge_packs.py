"""HTTP API for local knowledge-pack installation and registry management."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.knowledge_packs.builder import checksum_matches, validate_pack_file
from ..services.knowledge_packs.registry import install_pack, list_installed_packs, uninstall_pack

router = APIRouter(prefix="/api/knowledge-packs", tags=["knowledge-packs"])


class PackInstallRequest(BaseModel):
    pack_path: str = Field(..., min_length=1)


class PackRegistryResponse(BaseModel):
    pack_id: str
    name: str
    version: str
    installed_at: str
    source_path: str
    pack_path: str
    checksum_ok: bool
    status: str


@router.get("/installed", response_model=list[PackRegistryResponse])
def get_installed_packs():
    return list_installed_packs()


@router.post("/install", response_model=PackRegistryResponse)
def install_local_pack(payload: PackInstallRequest):
    path = Path(payload.pack_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Pack file not found")

    issues = validate_pack_file(path)
    errors = [issue.message for issue in issues if issue.level == "error"]
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    if not checksum_matches(path):
        raise HTTPException(status_code=400, detail="Pack checksum missing or invalid")

    try:
        entry = install_pack(path)
        return PackRegistryResponse(**entry.as_dict())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{pack_id}")
def uninstall_local_pack(pack_id: str):
    removed = uninstall_pack(pack_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Pack not installed")
    return {"removed": True, "pack_id": pack_id}
