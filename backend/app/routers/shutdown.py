"""Graceful shutdown endpoint for desktop backend."""
from fastapi import APIRouter

router = APIRouter()


@router.post("/shutdown")
def shutdown():
    import os
    import signal
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting down"}
