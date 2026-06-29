from fastapi import APIRouter

from ..schemas.api import HardwareInfo
from ..services.hardware import detect_hardware, resolve_managed_plan

router = APIRouter(prefix="/api/system")


@router.get("/hardware", response_model=HardwareInfo)
def get_hardware():
    hw = detect_hardware()
    return HardwareInfo(**hw)


@router.get("/hardware/managed-plan")
def get_hardware_managed_plan():
    """Detect hardware and return a managed plan recommendation."""
    plan = resolve_managed_plan()
    return plan
