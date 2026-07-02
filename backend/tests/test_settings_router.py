from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ModelEndpoint
from app.routers.settings import get_model_endpoint, save_model_endpoint
from app.schemas.api import ModelEndpointConfig


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_save_model_endpoint_preserves_empty_local_api_key():
    with _session() as db:
        db.add(
            ModelEndpoint(
                id=1,
                provider="openai_compatible",
                base_url="http://localhost:11434/v1",
                api_key="existing-key",
                models={},
            )
        )
        db.commit()

        saved = save_model_endpoint(
            ModelEndpointConfig(
                provider="openai_compatible",
                base_url="http://localhost:11434/v1",
                api_key="",
                models={
                    "orchestrator": "qwen3.5-0.8b-claude-opus-reasoning-distilled",
                    "summarizer": "",
                    "utility": "granite-4.0-h-350m",
                },
            ),
            db=db,
        )

        row = db.get(ModelEndpoint, 1)
        assert saved.api_key == ""
        assert row.api_key == ""
        assert row.models["orchestrator"] == "qwen3.5-0.8b-claude-opus-reasoning-distilled"


def test_model_endpoint_access_creates_missing_singleton_row():
    with _session() as db:
        saved = save_model_endpoint(
            ModelEndpointConfig(
                provider="openai_compatible",
                base_url="http://localhost:11434/v1",
                api_key="",
                models={"orchestrator": "local-model", "summarizer": "", "utility": ""},
            ),
            db=db,
        )

        loaded = get_model_endpoint(db=db)

        assert saved.api_key == ""
        assert loaded.base_url == "http://localhost:11434/v1"
        assert loaded.models.orchestrator == "local-model"
