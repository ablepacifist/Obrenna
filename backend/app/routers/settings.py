from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import DEFAULT_BASE_URL
from ..db import get_db
from ..models import AppSettings, ModelEndpoint
from ..model_runtime.client import test_connection_sync
from ..model_runtime.config import RuntimeConfig
from ..schemas.api import (
    AppSettingsDTO,
    ModelEndpointConfig,
    ModelRoles,
    TestConnectionResult,
)

router = APIRouter(prefix="/api/settings")


def _normalize_models(models) -> dict:
    """Convert ModelRoles Pydantic model or plain dict to a plain dict for JSON columns."""
    if models is None:
        return {}
    if isinstance(models, ModelRoles):
        return models.model_dump()
    if isinstance(models, dict):
        return models
    return {}


# --- model endpoint ----------------------------------------------------------

@router.get("/model-endpoint", response_model=ModelEndpointConfig)
def get_model_endpoint(db: Session = Depends(get_db)):
    row = db.get(ModelEndpoint, 1)
    if row is None:
        row = ModelEndpoint(
            id=1,
            provider="openai_compatible",
            base_url=DEFAULT_BASE_URL,
            api_key="",
            models={},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return ModelEndpointConfig(
        provider=row.provider,
        base_url=row.base_url,
        api_key=row.api_key or "",
        models=row.models or {},
    )


@router.post("/model-endpoint", response_model=ModelEndpointConfig)
def save_model_endpoint(payload: ModelEndpointConfig, db: Session = Depends(get_db)):
    row = db.get(ModelEndpoint, 1)
    if row is None:
        row = ModelEndpoint(id=1)
        db.add(row)
    row.provider = payload.provider
    row.base_url = payload.base_url
    row.api_key = payload.api_key or ""
    row.models = _normalize_models(payload.models)
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
        models=_normalize_models(payload.models),
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
        workers_enabled=row.workers_enabled,
        orchestrator_override=row.orchestrator_override or None,
    )


@router.post("/app", response_model=AppSettingsDTO)
def save_app_settings(payload: AppSettingsDTO, db: Session = Depends(get_db)):
    """Update app settings. Fields the caller omits are LEFT ALONE.

    This used to assign every field unconditionally. Because each field on
    AppSettingsDTO has a default, an omitted field arrived as that default and
    was written over the stored value -- so a partial update silently wiped
    everything it didn't mention. Posting only ``{"orchestrator_override":
    null}`` reset ``setup_complete`` to False and dumped the user back into the
    first-run setup wizard with their chats apparently gone.

    The frontend's own client types this as ``Partial<AppSettings>``, so
    partial posts are the expected shape, not an abuse of the endpoint.

    ``exclude_unset`` distinguishes "field absent" from "field explicitly set
    to its default" -- clearing the override with an explicit ``null`` still
    works, while omitting it leaves it untouched.
    """
    row = db.get(AppSettings, 1)
    provided = payload.model_dump(exclude_unset=True)

    if "setup_complete" in provided:
        row.setup_complete = provided["setup_complete"]
    if "setup_mode" in provided:
        row.setup_mode = provided["setup_mode"]
    if "theme" in provided:
        row.theme = provided["theme"]
    if "active_models" in provided:
        row.active_models = provided["active_models"] or []
    if "managed_plan" in provided:
        row.managed_plan = provided["managed_plan"] or {}
    if "workers_enabled" in provided:
        row.workers_enabled = provided["workers_enabled"]
    if "orchestrator_override" in provided:
        row.orchestrator_override = (provided["orchestrator_override"] or "").strip() or None
    db.commit()
    db.refresh(row)
    return AppSettingsDTO(
        setup_complete=row.setup_complete,
        setup_mode=row.setup_mode or "managed",
        theme=row.theme or "system",
        active_models=row.active_models or [],
        managed_plan=row.managed_plan or {},
        workers_enabled=row.workers_enabled,
        orchestrator_override=row.orchestrator_override or None,
    )
