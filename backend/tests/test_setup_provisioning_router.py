from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AppSettings, ModelEndpoint, ProvisionJob, ProvisionJobItem
from app.routers.setup import confirm_managed_plan, get_provisioning_job


class _DummyPlan(dict):
    pass


def _make_plan() -> dict:
    return {
        "path": "gpu",
        "plan_id": "T0-subfloor",
        "plan_rank": 50,
        "ctx": 8192,
        "helper_count": 1,
        "fingerprint_hash": "fp-123",
        "runtime_priority": ["vulkan", "cuda"],
        "runtime_forbidden": [],
        "required_launch_flags": [],
        "recommended_setup_mode": "managed",
        "action": "ok",
        "reason": None,
        "detection_warnings": [],
        "orchestrator": {
            "model": "qwen3.5-0.8b-claude-opus-reasoning-distilled",
            "quant": "Q4_K_M",
            "device": "gpu",
            "ctx_min": 8192,
            "ctx_max": 16384,
        },
        "summarizer": {
            "model": "granite-4.0-h-350m",
            "quant": "Q4_K_M",
            "device": "cpu",
        },
        "utility": {
            "model": "granite-4.0-h-350m",
            "quant": "IQ3_XXS",
            "device": "cpu",
        },
        "optional_orchestrator": None,
        "validation_stubbed": True,
    }


def test_confirm_creates_provision_job_and_items(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        db.add(
            AppSettings(
                id=1,
                setup_complete=False,
                setup_mode="managed",
                theme="light",
                active_models=[],
                managed_plan={},
            )
        )
        db.add(
            ModelEndpoint(
                id=1,
                provider="openai_compatible",
                base_url="http://localhost:11434/v1",
                api_key="",
                models={},
            )
        )
        db.commit()

        monkeypatch.setattr(
            "app.routers.setup.resolve_managed_plan",
            lambda runtime_base_url=None: _make_plan(),
        )
        monkeypatch.setattr("app.routers.setup.provisioning_manager.start", lambda *_args, **_kwargs: None)

        result = confirm_managed_plan(db=db)

        assert result["confirmed"] is True
        assert result["status"] == "queued"
        assert result["runtime_kind"] == "ollama"
        assert result["supports_pull"] is True
        assert result["reused"] is False

        jobs = db.query(ProvisionJob).all()
        assert len(jobs) == 1
        assert jobs[0].fingerprint_hash == "fp-123"

        items = db.query(ProvisionJobItem).filter(ProvisionJobItem.job_id == jobs[0].id).all()
        assert len(items) == 3

        settings = db.get(AppSettings, 1)
        assert settings.setup_complete is False
        assert settings.managed_plan.get("plan_id") == "T0-subfloor"
        assert settings.active_models == [
            "qwen3.5-0.8b-claude-opus-reasoning-distilled",
            "granite-4.0-h-350m",
            "granite-4.0-h-350m",
        ]


def test_confirm_reuses_active_job(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        db.add(AppSettings(id=1, active_models=[], managed_plan={}))
        db.add(ModelEndpoint(id=1, provider="openai_compatible", base_url="http://localhost:11434/v1"))
        db.commit()

        monkeypatch.setattr(
            "app.routers.setup.resolve_managed_plan",
            lambda runtime_base_url=None: _make_plan(),
        )
        monkeypatch.setattr("app.routers.setup.provisioning_manager.start", lambda *_args, **_kwargs: None)

        first = confirm_managed_plan(db=db)
        second = confirm_managed_plan(db=db)

        assert first["reused"] is False
        assert second["reused"] is True
        assert second["job_id"] == first["job_id"]

        count = db.query(ProvisionJob).count()
        assert count == 1


def test_get_provisioning_job_snapshot(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        db.add(AppSettings(id=1, active_models=[], managed_plan={}))
        db.add(ModelEndpoint(id=1, provider="openai_compatible", base_url="http://localhost:11434/v1"))
        db.commit()

        monkeypatch.setattr(
            "app.routers.setup.resolve_managed_plan",
            lambda runtime_base_url=None: _make_plan(),
        )
        monkeypatch.setattr("app.routers.setup.provisioning_manager.start", lambda *_args, **_kwargs: None)
        created = confirm_managed_plan(db=db)

        snapshot = get_provisioning_job(created["job_id"], db=db)
        assert snapshot["id"] == created["job_id"]
        assert snapshot["status"] == "queued"
        assert len(snapshot["items"]) == 3
