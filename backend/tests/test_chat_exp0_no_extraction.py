"""Tests for HIGH-009: EXP0 must not trigger background fact extraction.

The EXP0 tier (experimental_opt_in_tiers.EXP0 in hardware_catalog.json)
explicitly declares "recency-only" memory with
``memory_subsystem_override.embedding_model = "NOT LOADED at this tier —
skip retrieval gate entirely"``. Before the fix, ``send_message`` always
dispatched ``_run_fact_extraction`` in a background thread regardless of
tier — and that function calls ``embed_text()`` (memory.py), lazy-loading
the ONNX embedding model on a machine the catalog says explicitly should
never load one (as low as 4GB RAM / 2 cores).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AppSettings, ModelEndpoint


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    local_session = sessionmaker(bind=engine)
    session = local_session()
    session.add(AppSettings(id=1, workers_enabled=False))
    session.add(ModelEndpoint(
        id=1, provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": "qwen3.5-0.8b-claude-opus-reasoning-distilled"},
    ))
    session.commit()
    return session


class TestHandleNormalChatReturnsExp0Flag:
    @pytest.mark.asyncio
    async def test_exp0_plan_flag_is_true_for_08b_orchestrator(self, monkeypatch, db):
        from app.agent.events import StreamEvent
        from app.models import Chat, ChatMessage
        from app.routers import chat as chat_router
        from app.schemas.api import ChatRequest
        from datetime import datetime, timezone

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(chat_id="chat-exp0-1", type="token", payload={"text": "hi"})

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "gpu", "plan_id": "EXP0-minimal", "ctx": 4096, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5-0.8b-claude-opus-reasoning-distilled"},
                "summarizer": {}, "utility": {},
            },
        )

        chat = Chat(id="chat-exp0-1", title="EXP0 test")
        db.add(chat)
        user_msg = ChatMessage(
            id="u-exp0-1", chat_id=chat.id, role="user", text="hi",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        db.commit()

        payload = ChatRequest(chat_id=chat.id, message="hi")

        _reply, _msg_id, is_exp0 = chat_router._handle_normal_chat(
            db, chat, user_msg, payload, assistant_message_id="asst-exp0-1",
        )

        assert is_exp0 is True

    @pytest.mark.asyncio
    async def test_non_exp0_plan_flag_is_false(self, monkeypatch, db):
        from app.agent.events import StreamEvent
        from app.models import Chat, ChatMessage
        from app.routers import chat as chat_router
        from app.schemas.api import ChatRequest
        from datetime import datetime, timezone

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(chat_id="chat-nonexp0-1", type="token", payload={"text": "hi"})

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "gpu", "plan_id": "T3-plus", "ctx": 16384, "helper_count": 2,
                "orchestrator": {"model": "qwen3.5-9b-claude-opus-reasoning-distilled"},
                "summarizer": {"model": "granite4.0-h-micro-3b"},
                "utility": {"model": "qwen3.5-0.8b"},
            },
        )

        chat = Chat(id="chat-nonexp0-1", title="Non-EXP0 test")
        db.add(chat)
        user_msg = ChatMessage(
            id="u-nonexp0-1", chat_id=chat.id, role="user", text="hi",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        db.commit()

        payload = ChatRequest(chat_id=chat.id, message="hi")

        _reply, _msg_id, is_exp0 = chat_router._handle_normal_chat(
            db, chat, user_msg, payload, assistant_message_id="asst-nonexp0-1",
        )

        assert is_exp0 is False


class TestSendMessageSkipsExtractionOnExp0:
    """Full send_message() integration: EXP0 must not start the background
    fact-extraction thread at all."""

    def test_exp0_turn_does_not_dispatch_fact_extraction_thread(self, monkeypatch, db):
        from app.agent.events import StreamEvent
        from app.routers import chat as chat_router
        from app.schemas.api import ChatRequest

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(chat_id="doesnt-matter", type="token", payload={"text": "hi there"})

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "gpu", "plan_id": "EXP0-minimal", "ctx": 4096, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5-0.8b-claude-opus-reasoning-distilled"},
                "summarizer": {}, "utility": {},
            },
        )

        thread_started = []

        class _TrackingThread:
            def __init__(self, target=None, args=(), daemon=None):
                thread_started.append((target, args))

            def start(self):
                pass

        monkeypatch.setattr(chat_router.threading, "Thread", _TrackingThread)

        payload = ChatRequest(message="hi there")
        chat_router.send_message(payload, db=db)

        assert thread_started == [], (
            "EXP0 must not dispatch background fact extraction — "
            "the tier forbids loading the embedding model entirely"
        )

    def test_non_exp0_turn_still_dispatches_fact_extraction_thread(self, monkeypatch, db):
        from app.agent.events import StreamEvent
        from app.routers import chat as chat_router
        from app.schemas.api import ChatRequest

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(chat_id="doesnt-matter", type="token", payload={"text": "hi there"})

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "gpu", "plan_id": "T3-plus", "ctx": 16384, "helper_count": 2,
                "orchestrator": {"model": "qwen3.5-9b-claude-opus-reasoning-distilled"},
                "summarizer": {"model": "granite4.0-h-micro-3b"},
                "utility": {"model": "qwen3.5-0.8b"},
            },
        )

        thread_started = []

        class _TrackingThread:
            def __init__(self, target=None, args=(), daemon=None):
                thread_started.append((target, args))

            def start(self):
                pass

        monkeypatch.setattr(chat_router.threading, "Thread", _TrackingThread)

        payload = ChatRequest(message="hi there")
        chat_router.send_message(payload, db=db)

        assert len(thread_started) == 1
        assert thread_started[0][0] is chat_router._run_fact_extraction
