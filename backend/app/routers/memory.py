"""Memory subsystem API: list, create, update, and delete local memory facts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MemoryFact
from ..schemas.api import MemoryFactCreateRequest, MemoryFactDTO, MemoryFactUpdateRequest
from ..services import memory as memory_svc

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/facts", response_model=list[MemoryFactDTO])
def list_facts(db: Session = Depends(get_db)):
    """List all active (non-deleted) memory facts."""
    facts = memory_svc.get_active_facts(db)
    return [
        MemoryFactDTO(
            id=f.id,
            fact_text=f.fact_text,
            source_chat_id=f.source_chat_id,
            user_locked=f.user_locked,
            created_at=f.created_at.isoformat(),
            updated_at=f.updated_at.isoformat(),
        )
        for f in facts
    ]


@router.post("/facts", response_model=MemoryFactDTO)
def create_fact(payload: MemoryFactCreateRequest, db: Session = Depends(get_db)):
    """Create a user-initiated memory fact (user_locked=true by default)."""
    try:
        fact = memory_svc.create_fact(db, payload.fact_text, source="user")
        if fact is None:
            raise HTTPException(status_code=500, detail="Failed to create fact.")
        return MemoryFactDTO(
            id=fact.id,
            fact_text=fact.fact_text,
            source_chat_id=fact.source_chat_id,
            user_locked=fact.user_locked,
            created_at=fact.created_at.isoformat(),
            updated_at=fact.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create fact: {exc}")


@router.patch("/facts/{fact_id}", response_model=MemoryFactDTO)
def update_fact(fact_id: str, payload: MemoryFactUpdateRequest, db: Session = Depends(get_db)):
    """Update a fact's text, recompute embedding, set user_locked=true."""
    try:
        fact = memory_svc.update_fact(db, fact_id, payload.fact_text)
        if fact is None:
            raise HTTPException(status_code=404, detail="Fact not found.")
        return MemoryFactDTO(
            id=fact.id,
            fact_text=fact.fact_text,
            source_chat_id=fact.source_chat_id,
            user_locked=fact.user_locked,
            created_at=fact.created_at.isoformat(),
            updated_at=fact.updated_at.isoformat(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update fact: {exc}")


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: str, db: Session = Depends(get_db)):
    """Soft-delete a fact: set deleted_at, keep vector for tombstone."""
    try:
        ok = memory_svc.delete_fact(db, fact_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Fact not found.")
        return {"deleted": True, "fact_id": fact_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete fact: {exc}")
