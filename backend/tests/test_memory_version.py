"""Tests for the versioned memory cache (Fix #7).

Verifies the brief's locked-correctness contract:
- every fact write (ADD/UPDATE/DELETE) bumps ``account_memory_version`` and the
  fact's own ``version``;
- a turn record bumps ``chat_memory_version``; a summary fold bumps the rolling
  summary version;
- ``assemble_context`` returns the *same* cached object when no version
  counter changed (cache hit), and a *fresh* object reflecting the write when a
  counter bumped (cache miss) — so a stale user_locked fact is never served.

fastembed is not installed in this test environment, so ``embed_text`` is
monkeypatched with a deterministic bag-of-words vector (same approach as
``test_memory_locked_retrieval.py``).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Chat, ChatMessage, MemoryFact
from app.services.memory import (
    assemble_context,
    create_fact,
    delete_fact,
    record_turn_after_response,
    update_fact,
)
from app.services.memory_versions import (
    bump_account_version,
    bump_chat_version,
    bump_rolling_summary_version,
    get_account_version,
    get_chat_version,
    get_rolling_summary_version,
)
from app.services.migrations import run_migrations

_VOCAB = ["teal", "python", "rust", "color", "favorite", "language", "programming", "user"]


def _fake_embed(text: str) -> list[float]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return [1.0 if word in tokens else 0.0 for word in _VOCAB]


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    monkeypatch.setattr("app.services.vector_store.embed_text", _fake_embed)
    monkeypatch.setattr("app.services.memory.embed_text", _fake_embed)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    local_session = sessionmaker(bind=engine)
    session = local_session()
    run_migrations(session)
    return session


@pytest.fixture
def sample_chat(db: Session):
    chat = Chat(id="chat-version-1", title="Version cache test")
    db.add(chat)
    db.commit()
    return chat


@pytest.fixture
def sample_messages(db: Session, sample_chat: Chat):
    u1 = ChatMessage(
        id="vu1", chat_id=sample_chat.id, role="user", text="What is my favorite programming language?",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    a1 = ChatMessage(
        id="va1", chat_id=sample_chat.id, role="assistant", text="Your favorite is Python.",
        created_at=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
    )
    db.add_all([u1, a1])
    db.commit()
    return {"u1": u1, "a1": a1}


# ── Version counter bumps ────────────────────────────────────────────────────


class TestVersionBumps:
    def test_account_version_starts_at_1(self, db):
        assert get_account_version(db, MemoryFact.ACCOUNT_ID) == 1

    def test_bump_account_version_increments_and_returns_new(self, db):
        new_v = bump_account_version(db, MemoryFact.ACCOUNT_ID)
        db.commit()
        assert new_v == 2
        assert get_account_version(db, MemoryFact.ACCOUNT_ID) == 2
        new_v = bump_account_version(db, MemoryFact.ACCOUNT_ID)
        db.commit()
        assert new_v == 3

    def test_create_fact_bumps_account_version(self, db):
        assert get_account_version(db, MemoryFact.ACCOUNT_ID) == 1
        create_fact(db, "User lives in Seattle")
        assert get_account_version(db, MemoryFact.ACCOUNT_ID) == 2

    def test_update_fact_bumps_account_version_and_fact_version(self, db):
        fact = create_fact(db, "User lives in Seattle")
        assert fact.version == 1
        v0 = get_account_version(db, MemoryFact.ACCOUNT_ID)
        updated = update_fact(db, fact.id, "User lives in Portland")
        assert updated.version == 2
        assert get_account_version(db, MemoryFact.ACCOUNT_ID) == v0 + 1

    def test_delete_fact_bumps_account_version_and_fact_version(self, db):
        fact = create_fact(db, "User lives in Seattle")
        v0 = get_account_version(db, MemoryFact.ACCOUNT_ID)
        assert delete_fact(db, fact.id)
        db.flush()
        assert get_account_version(db, MemoryFact.ACCOUNT_ID) == v0 + 1
        refreshed = db.get(MemoryFact, fact.id)
        assert refreshed.version == 2
        assert refreshed.deleted_at is not None

    def test_record_turn_bumps_chat_version(self, db, sample_chat, sample_messages):
        assert get_chat_version(db, sample_chat.id) == 1
        record_turn_after_response(db, sample_chat, sample_messages["u1"], sample_messages["a1"])
        assert get_chat_version(db, sample_chat.id) == 2

    def test_bump_rolling_summary_version_increments(self, db, sample_chat):
        assert get_rolling_summary_version(db, sample_chat.id) == 1
        bump_rolling_summary_version(db, sample_chat.id)
        db.commit()
        assert get_rolling_summary_version(db, sample_chat.id) == 2


# ── Cache correctness: no stale facts ────────────────────────────────────────


class TestAssembleContextCache:
    def test_repeated_query_returns_same_cached_object(self, db, sample_chat):
        create_fact(db, "User's favorite programming language is Python.", sample_chat.id)
        ctx1 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        ctx2 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        # Cache hit: the exact same MemoryContext object is returned, skipping
        # all retrieval (no version counter changed between the two calls).
        assert ctx1 is ctx2

    def test_different_query_returns_different_object(self, db, sample_chat):
        create_fact(db, "User's favorite programming language is Python.", sample_chat.id)
        ctx1 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        ctx2 = assemble_context(db, sample_chat, "Tell me about a different topic entirely")
        assert ctx1 is not ctx2

    def test_update_locked_fact_reflected_on_next_turn(self, db, sample_chat):
        fact = create_fact(db, "User's favorite programming language is Python.", sample_chat.id)
        ctx1 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert any("Python" in f["text"] for f in ctx1.facts)

        # User edits their locked fact. update_fact bumps account_memory_version,
        # which invalidates the cached context for this account.
        update_fact(db, fact.id, "User's favorite programming language is Rust.")

        ctx2 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert ctx2 is not ctx1, "a locked-fact edit must invalidate the cached context"
        texts2 = [f["text"] for f in ctx2.facts]
        assert any("Rust" in t for t in texts2), "the updated locked fact must appear"
        assert not any("Python" in t for t in texts2), "the stale text must not be served"

    def test_delete_fact_not_served_on_next_turn(self, db, sample_chat):
        fact = create_fact(db, "User's favorite programming language is Python.", sample_chat.id)
        ctx1 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert any("Python" in f["text"] for f in ctx1.facts)

        delete_fact(db, fact.id)

        ctx2 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert ctx2 is not ctx1, "a delete must invalidate the cached context"
        assert not any("Python" in f["text"] for f in ctx2.facts), (
            "a deleted fact must not be served from a stale cache"
        )

    def test_new_fact_appears_on_next_turn(self, db, sample_chat):
        ctx1 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert not any("Python" in f["text"] for f in ctx1.facts)

        create_fact(db, "User's favorite programming language is Python.", sample_chat.id)

        ctx2 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert ctx2 is not ctx1, "an add must invalidate the cached context"
        assert any("Python" in f["text"] for f in ctx2.facts)

    def test_new_turn_invalidates_cached_context(self, db, sample_chat, sample_messages):
        ctx1 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        # Record a turn: bumps chat_memory_version → cached context invalidated.
        record_turn_after_response(db, sample_chat, sample_messages["u1"], sample_messages["a1"])
        ctx2 = assemble_context(db, sample_chat, "What is my favorite programming language?")
        assert ctx2 is not ctx1, "a new turn must invalidate the cached context"