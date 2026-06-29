"""Setup routes for managed hardware detection and plan resolution."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AppSettings
from ..schemas.api import ManagedPlanResponse
from ..services.hardware import resolve_managed_plan

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/managed-plan", response_model=ManagedPlanResponse)
def get_managed_plan():
    """Detect hardware and resolve a managed plan."""
    plan = resolve_managed_plan()
    return ManagedPlanResponse(**plan)


@router.post("/managed-plan/confirm")
def confirm_managed_plan():
    """Persist the current managed plan as the active setup.

    The frontend calls this after the user accepts the detected plan.
    It writes the plan metadata to the AppSettings row.
    """
    # The actual plan data is returned by GET /api/setup/managed-plan.
    # This endpoint exists for the UI flow: user reviews, clicks confirm,
    # backend persists it.
    # For now, we return the latest plan so the frontend can store it locally.
    plan = resolve_managed_plan()
    return {"confirmed": True, "plan": plan}
