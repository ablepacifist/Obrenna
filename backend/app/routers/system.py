from fastapi import APIRouter

from ..schemas.api import HardwareInfo
from ..services.hardware import detect_hardware

router = APIRouter(prefix="/api/system")


@router.get("/hardware", response_model=HardwareInfo)
def get_hardware():
    hw = detect_hardware()
    return HardwareInfo(**hw)
