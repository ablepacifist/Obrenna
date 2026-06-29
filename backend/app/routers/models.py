from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ModelEndpoint
from ..schemas.api import CatalogModel
from ..services.hardware import detect_hardware
from ..services.model_catalog import catalog_with_fit

router = APIRouter(prefix="/api/models")


@router.get("/catalog", response_model=list[CatalogModel])
def get_catalog(db: Session = Depends(get_db)):
    hardware = detect_hardware()
    return [CatalogModel(**m) for m in catalog_with_fit(hardware)]
