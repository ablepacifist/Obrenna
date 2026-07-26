"""Tests for HIGH-005: a recoverable orchestrator error must not roll back
tokens that already streamed to the UI.

Before the fix, ``_handle_normal_chat._collect`` raised ``RuntimeError`` on
any runtime ``error`` event, which ``send_message`` turned into an
``HTTPException(503)``. Because the user/assistant messages and chat row are
only committed at the end of ``send_message`` (after the runtime call
returns), a 503 exception unwound the whole request before that commit ran
— the frontend had already rendered streamed tokens, but on reload the turn
was gone. The fix makes the collector return whatever text streamed before
the error (plus a note) instead of raising, so the turn is still persisted.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.events import StreamEvent
from app.db import Base
from app.models import AppSettings, Chat, ChatMessage, ModelEndpoint
from app.schemas.api import ChatRequest


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
        models={"orchestrator": "qwen3.5:4b"},
    ))
    chat = Chat(id="chat-err-1", title="Error path test")
    session.add(chat)
    session.commit()
    return session


class TestPartialTurnPersistsOnRecoverableError:
    @pytest.mark.asyncio
    async def test_streamed_tokens_survive_a_mid_stream_error(self, monkeypatch, db):
        from app.routers import chat as chat_router

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(chat_id="chat-err-1", type="token", payload={"text": "Partial an"})
            yield StreamEvent(chat_id="chat-err-1", type="token", payload={"text": "swer here."})
            yield StreamEvent(
                chat_id="chat-err-1", type="error",
                payload={"error_code": "orchestrator_error", "message": "model crashed", "recoverable": True},
            )

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "fallback", "ctx": 8192, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5:4b"}, "summarizer": {}, "utility": {},
            },
        )

        chat = db.get(Chat, "chat-err-1")
        user_msg = ChatMessage(
            id="u-err-1", chat_id=chat.id, role="user", text="hello",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        db.commit()

        payload = ChatRequest(chat_id=chat.id, message="hello")

        reply_text, msg_id, _is_exp0, _tool_events = chat_router._handle_normal_chat(
            db, chat, user_msg, payload, assistant_message_id="asst-err-1",
        )

        # The tokens that streamed before the error must NOT be discarded.
        assert reply_text == "Partial answer here."
        assert msg_id == "asst-err-1"

    @pytest.mark.asyncio
    async def test_error_with_no_tokens_yields_placeholder_not_empty_string(self, monkeypatch, db):
        from app.routers import chat as chat_router

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(
                chat_id="chat-err-1", type="error",
                payload={"error_code": "summarizer_failure", "message": "summarizer failed", "recoverable": False},
            )

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "fallback", "ctx": 8192, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5:4b"}, "summarizer": {}, "utility": {},
            },
        )

        chat = db.get(Chat, "chat-err-1")
        user_msg = ChatMessage(
            id="u-err-2", chat_id=chat.id, role="user", text="hello again",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        db.commit()

        payload = ChatRequest(chat_id=chat.id, message="hello again")

        reply_text, _msg_id, _is_exp0, _tool_events = chat_router._handle_normal_chat(
            db, chat, user_msg, payload, assistant_message_id="asst-err-2",
        )

        assert reply_text, "must not persist an empty assistant message"
        assert "summarizer failed" in reply_text

    @pytest.mark.asyncio
    async def test_unexpected_crash_before_any_event_still_raises_503(self, monkeypatch, db):
        """A crash in the runtime itself (before it can emit a typed error
        event) is a different failure mode: no error event reached the UI,
        so this must still surface as a hard failure rather than silently
        persisting a blank/successful-looking turn."""
        from fastapi import HTTPException

        from app.routers import chat as chat_router

        async def fake_orchestrate_turn(*args, **kwargs):
            raise RuntimeError("unexpected crash")
            yield  # pragma: no cover - unreachable, makes this an async generator

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "fallback", "ctx": 8192, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5:4b"}, "summarizer": {}, "utility": {},
            },
        )

        chat = db.get(Chat, "chat-err-1")
        user_msg = ChatMessage(
            id="u-err-3", chat_id=chat.id, role="user", text="hello once more",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        db.commit()

        payload = ChatRequest(chat_id=chat.id, message="hello once more")

        with pytest.raises(HTTPException) as exc_info:
            chat_router._handle_normal_chat(
                db, chat, user_msg, payload, assistant_message_id="asst-err-3",
            )
        assert exc_info.value.status_code == 503
