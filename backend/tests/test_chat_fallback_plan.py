"""Tests for MED-011: the fallback hardware plan must preserve tool_call_mode.

When hardware resolution fails (or the resolver returns a plan without an
orchestrator model), ``_get_hardware_plan`` falls back to the raw
``ModelEndpoint.models`` setting. Before the fix, that fallback dict omitted
``tool_call_mode`` entirely, so ``ResolvedPlan.orchestrator_tool_call_mode``
silently defaulted to "openai_native" — even for the DB-seeded default
orchestrator, which is a prompt-JSON distill. Driving a prompt-JSON model as
native means its `{"action":"tool_call",...}` envelope is never parsed and
leaks into the chat as literal text.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ModelEndpoint


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    local_session = sessionmaker(bind=engine)
    return local_session()


class TestFallbackPlanToolCallMode:
    def test_fallback_preserves_prompt_json_for_distilled_orchestrator(self, monkeypatch, db):
        from app.routers import chat as chat_router

        # Force hardware resolution to fail so the fallback path is taken.
        def failing_resolve(*args, **kwargs):
            raise RuntimeError("no hardware probe available")

        monkeypatch.setattr(
            "app.services.hardware.resolve_managed_plan", failing_resolve
        )

        db.add(ModelEndpoint(
            id=1, provider="openai_compatible", base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5-9b-claude-opus-reasoning-distilled"},
        ))
        db.commit()

        plan = chat_router._get_hardware_plan(db, workers_enabled=True)

        assert plan["path"] == "fallback"
        assert plan["orchestrator"]["model"] == "qwen3.5-9b-claude-opus-reasoning-distilled"
        assert plan["orchestrator"]["tool_call_mode"] == "prompt_json"

    def test_fallback_preserves_native_for_stock_orchestrator(self, monkeypatch, db):
        from app.routers import chat as chat_router

        def failing_resolve(*args, **kwargs):
            raise RuntimeError("no hardware probe available")

        monkeypatch.setattr(
            "app.services.hardware.resolve_managed_plan", failing_resolve
        )

        db.add(ModelEndpoint(
            id=1, provider="openai_compatible", base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5-27b"},
        ))
        db.commit()

        plan = chat_router._get_hardware_plan(db, workers_enabled=True)

        assert plan["orchestrator"]["model"] == "qwen3.5-27b"
        assert plan["orchestrator"]["tool_call_mode"] == "openai_native"

    def test_fallback_with_no_endpoint_defaults_to_native(self, monkeypatch, db):
        from app.routers import chat as chat_router

        def failing_resolve(*args, **kwargs):
            raise RuntimeError("no hardware probe available")

        monkeypatch.setattr(
            "app.services.hardware.resolve_managed_plan", failing_resolve
        )

        # No ModelEndpoint row at all — falls all the way to the last
        # branch of _get_hardware_plan (no ep, no orchestrator model).
        plan = chat_router._get_hardware_plan(db, workers_enabled=True)

        assert plan["orchestrator"]["model"] == ""
        assert plan["orchestrator"]["tool_call_mode"] == "openai_native"

    def test_lookup_tool_call_mode_handles_unknown_model(self):
        from app.routers.chat import _lookup_tool_call_mode

        assert _lookup_tool_call_mode("some-unlisted-model") == "openai_native"
        assert _lookup_tool_call_mode("") == "openai_native"
