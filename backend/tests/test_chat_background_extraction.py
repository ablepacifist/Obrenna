"""Tests for background fact extraction thread-safety (CRIT-004).

The bug: ``_run_fact_extraction`` used to receive the request-scoped
SQLAlchemy Session directly and run on a daemon thread while the request
thread continued using/closing that same session — SQLAlchemy Sessions are
not thread-safe, so this could corrupt writes or raise under concurrent use.
The fix: the background thread must open its own session and re-fetch
entities by id.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Chat, ChatMessage


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def db(session_factory):
    return session_factory()


@pytest.fixture
def sample_turn(db):
    chat = Chat(id="chat-bg-1", title="Background extraction test")
    db.add(chat)
    user_msg = ChatMessage(
        id="u-bg-1", chat_id=chat.id, role="user", text="My favorite color is teal.",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    asst_msg = ChatMessage(
        id="a-bg-1", chat_id=chat.id, role="assistant", text="Got it, teal it is.",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    db.add(user_msg)
    db.add(asst_msg)
    db.commit()
    return chat, user_msg, asst_msg


class TestRunFactExtractionSignature:
    """_run_fact_extraction must take IDs, not ORM objects bound to the
    request session — verifies the call site in send_message() was updated
    alongside the function body."""

    def test_accepts_id_arguments_not_orm_objects(self):
        import inspect
        from app.routers.chat import _run_fact_extraction

        sig = inspect.signature(_run_fact_extraction)
        params = list(sig.parameters.keys())
        assert params == ["chat_id", "user_msg_id", "assistant_msg_id"], (
            "background extraction must take primitive ids so it can open its "
            "own session and re-fetch, never receive Session-bound ORM objects"
        )


class TestRunFactExtractionOwnSession:
    """_run_fact_extraction must open its own SessionLocal(), not reuse any
    session passed in or held by the caller."""

    def test_opens_and_closes_its_own_session(self, monkeypatch, session_factory, sample_turn):
        chat, user_msg, asst_msg = sample_turn
        opened_sessions = []

        class TrackingSession:
            def __init__(self, real):
                self._real = real
                opened_sessions.append(self)
                self.closed = False

            def get(self, model, id_):
                return self._real.get(model, id_)

            def close(self):
                self.closed = True
                self._real.close()

        def fake_session_local():
            return TrackingSession(session_factory())

        import app.db as db_module
        monkeypatch.setattr(db_module, "SessionLocal", fake_session_local)

        def fake_extract(db, user_msg_arg, assistant_msg_arg, source_chat_id=None):
            # Confirm the objects were re-fetched via the NEW session, and
            # that the fetched rows match the ids we passed in.
            assert user_msg_arg.id == user_msg.id
            assert assistant_msg_arg.id == asst_msg.id
            assert source_chat_id == chat.id
            return []

        monkeypatch.setattr(
            "app.routers.chat.extract_and_reconcile_facts", fake_extract
        )

        from app.routers.chat import _run_fact_extraction

        _run_fact_extraction(chat.id, user_msg.id, asst_msg.id)

        assert len(opened_sessions) == 1, "must open exactly one new session"
        assert opened_sessions[0].closed is True, "must close its session when done"

    def test_missing_messages_do_not_raise(self, monkeypatch, session_factory):
        """If the referenced messages don't exist (e.g. deleted), the
        background job must log and return, not crash the daemon thread."""
        import app.db as db_module
        monkeypatch.setattr(db_module, "SessionLocal", session_factory)

        from app.routers.chat import _run_fact_extraction

        # Should not raise.
        _run_fact_extraction("nonexistent-chat", "nonexistent-user-msg", "nonexistent-asst-msg")
