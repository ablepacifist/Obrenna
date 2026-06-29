from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AppSettings, ModelEndpoint
from ..model_runtime.client import test_connection_sync
from ..model_runtime.config import RuntimeConfig
from ..schemas.api import (
    AppSettingsDTO,
    ModelEndpointConfig,
    TestConnectionResult,
)

router = APIRouter(prefix="/api/settings")


# --- model endpoint ----------------------------------------------------------

@router.get("/model-endpoint", response_model=ModelEndpointConfig)
def get_model_endpoint(db: Session = Depends(get_db)):
    row = db.get(ModelEndpoint, 1)
    return ModelEndpointConfig(
        provider=row.provider,
        base_url=row.base_url,
        api_key=row.api_key or "",
        models=row.models or {},
    )


@router.post("/model-endpoint", response_model=ModelEndpointConfig)
def save_model_endpoint(payload: ModelEndpointConfig, db: Session = Depends(get_db)):
    row = db.get(ModelEndpoint, 1)
    row.provider = payload.provider
    row.base_url = payload.base_url
    row.api_key = payload.api_key or None
    row.models = payload.models or {}
    db.commit()
    db.refresh(row)
    return ModelEndpointConfig(
        provider=row.provider,
        base_url=row.base_url,
        api_key=row.api_key or "",
        models=row.models or {},
    )


@router.post("/model-endpoint/test", response_model=TestConnectionResult)
def test_model_endpoint(payload: ModelEndpointConfig, db: Session = Depends(get_db)):
    cfg = RuntimeConfig(
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key or "",
        models=payload.models or {},
    )
    result = test_connection_sync(cfg)
    return TestConnectionResult(**result)


# --- app settings ------------------------------------------------------------

@router.get("/app", response_model=AppSettingsDTO)
def get_app_settings(db: Session = Depends(get_db)):
    row = db.get(AppSettings, 1)
    return AppSettingsDTO(
        setup_complete=row.setup_complete,
        setup_mode=row.setup_mode or "managed",
        theme=row.theme or "system",
        active_models=row.active_models or [],
        managed_plan=row.managed_plan or {},
    )


@router.post("/app", response_model=AppSettingsDTO)
def save_app_settings(payload: AppSettingsDTO, db: Session = Depends(get_db)):
    row = db.get(AppSettings, 1)
    row.setup_complete = payload.setup_complete
    row.setup_mode = payload.setup_mode
    row.theme = payload.theme
    row.active_models = payload.active_models or []
    row.managed_plan = payload.managed_plan or {}
    db.commit()
    db.refresh(row)
    return AppSettingsDTO(
        setup_complete=row.setup_complete,
        setup_mode=row.setup_mode or "managed",
        theme=row.theme or "system",
        active_models=row.active_models or [],
        managed_plan=row.managed_plan or {},
    )
