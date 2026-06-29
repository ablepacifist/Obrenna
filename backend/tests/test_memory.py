"""Tests for the memory subsystem."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL
from app.db import Base
from app.models import Chat, ChatMessage, ChatTurn, MemoryFact
from app.services.memory import (
    pick_memory_budget,
    assemble_context,
    record_turn_after_response,
    build_model_messages,
    MemoryContext,
    get_active_facts,
    update_fact,
    delete_fact,
    create_fact,
)
from app.services.migrations import run_migrations, backfill_turns


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    """Session with migrations already run."""
    local_session = sessionmaker(bind=engine)
    session = local_session()
    run_migrations(session)
    return session


@pytest.fixture
def sample_chat(db: Session):
    chat = Chat(id="chat001", title="Test chat")
    db.add(chat)
    db.commit()
    return chat


@pytest.fixture
def sample_messages(db: Session, sample_chat: Chat):
    u1 = ChatMessage(
        id="u1", chat_id=sample_chat.id, role="user",
        text="What is the capital of France?",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    a1 = ChatMessage(
        id="a1", chat_id=sample_chat.id, role="assistant",
        text="The capital of France is Paris.",
        created_at=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
    )
    u2 = ChatMessage(
        id="u2", chat_id=sample_chat.id, role="user",
        text="How many inhabitants does Paris have?",
        created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    a2 = ChatMessage(
        id="a2", chat_id=sample_chat.id, role="assistant",
        text="Paris has about 2.1 million inhabitants.",
        created_at=datetime(2025, 1, 2, 1, tzinfo=timezone.utc),
    )
    db.add_all([u1, a1, u2, a2])
    db.commit()
    return {"u1": u1, "a1": a1, "u2": u2, "a2": a2}


# ── pick_memory_budget ───────────────────────────────────────────────────────


class TestPickMemoryBudget:
    def test_8k_returns_2048(self):
        assert pick_memory_budget(8192) == 2048

    def test_16k_returns_4096(self):
        assert pick_memory_budget(16384) == 4096

    def test_32k_returns_8192(self):
        assert pick_memory_budget(32768) == 8192

    def test_above_32k_returns_8192(self):
        assert pick_memory_budget(65536) == 8192

    def test_below_8k_returns_2048(self):
        assert pick_memory_budget(4096) == 2048

    def test_none_returns_4096(self):
        assert pick_memory_budget(None) == 4096


# ── backfill_turns ──────────────────────────────────────────────────────────


class TestBackfillTurns:
    def test_backfills_user_assistant_pairs(self, db: Session, sample_messages):
        count = backfill_turns(db)
        assert count == 2
        turns = db.query(ChatTurn).filter_by(chat_id="chat001").all()
        assert len(turns) == 2
        assert turns[0].turn_index == 0
        assert turns[0].user_message_id == "u1"
        assert turns[0].assistant_message_id == "a1"
        assert turns[1].turn_index == 1
        assert turns[1].user_message_id == "u2"
        assert turns[1].assistant_message_id == "a2"

    def test_skips_malformed_sequences(self, db: Session, sample_chat):
        u1 = ChatMessage(id="m1", chat_id=sample_chat.id, role="user", text="Hi",
                         created_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        u2 = ChatMessage(id="m2", chat_id=sample_chat.id, role="user", text="Bye",
                         created_at=datetime(2025, 1, 2, tzinfo=timezone.utc))
        db.add_all([u1, u2])
        db.commit()
        count = backfill_turns(db)
        assert count == 0

    def test_idempotent(self, db: Session, sample_messages):
        backfill_turns(db)
        count = backfill_turns(db)
        assert count == 0  # nothing new to backfill


# ── MemoryContext ───────────────────────────────────────────────────────────


class TestMemoryContext:
    def test_empty_to_messages(self):
        ctx = MemoryContext()
        msgs = ctx.to_messages()
        assert len(msgs) == 0

    def test_with_summary(self):
        ctx = MemoryContext(rolling_summary="Previous context about project X")
        msgs = ctx.to_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert "Previous context about project X" in msgs[0]["content"]

    def test_with_facts(self):
        ctx = MemoryContext(facts=[{"id": "f1", "text": "User prefers Python"}])
        msgs = ctx.to_messages()
        assert len(msgs) == 1
        assert "User prefers Python" in msgs[0]["content"]

    def test_build_model_messages(self):
        ctx = MemoryContext(rolling_summary="Old stuff")
        msgs = build_model_messages("Hello", ctx)
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello"

    def test_no_context_returns_user_only(self):
        ctx = MemoryContext()
        msgs = build_model_messages("Hello", ctx)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "Hello"}


# ── record_turn_after_response ──────────────────────────────────────────────


class TestRecordTurnAfterResponse:
    def test_creates_turn(self, db: Session, sample_chat, sample_messages):
        turn = record_turn_after_response(db, sample_chat, sample_messages["u1"], sample_messages["a1"])
        assert turn is not None
        created = db.query(ChatTurn).filter_by(chat_id="chat001").first()
        assert created is not None
        assert created.turn_index == 0
        assert created.user_text == "What is the capital of France?"

    def test_incremental_indices(self, db: Session, sample_chat, sample_messages):
        record_turn_after_response(db, sample_chat, sample_messages["u1"], sample_messages["a1"])
        record_turn_after_response(db, sample_chat, sample_messages["u2"], sample_messages["a2"])
        turns = db.query(ChatTurn).filter_by(chat_id="chat001").all()
        assert len(turns) == 2
        assert turns[0].turn_index == 0
        assert turns[1].turn_index == 1


# ── MemoryFact CRUD ─────────────────────────────────────────────────────────


class TestMemoryFactCRUD:
    def test_create_fact(self, db: Session):
        fact = create_fact(db, "User lives in Seattle", "chat001")
        assert fact is not None
        assert fact.fact_text == "User lives in Seattle"
        assert fact.user_locked is False

    def test_get_active_facts(self, db: Session):
        create_fact(db, "Fact 1")
        create_fact(db, "Fact 2")
        facts = get_active_facts(db)
        assert len(facts) == 2

    def test_delete_fact(self, db: Session):
        fact = create_fact(db, "To delete")
        ok = delete_fact(db, fact.id)
        assert ok is True
        facts = get_active_facts(db)
        assert len(facts) == 0
        # Tombstone still exists
        stored = db.query(MemoryFact).filter_by(id=fact.id).first()
        assert stored is not None
        assert stored.deleted_at is not None

    def test_update_fact(self, db: Session):
        fact = create_fact(db, "Old text")
        updated = update_fact(db, fact.id, "New text")
        assert updated is not None
        assert updated.fact_text == "New text"
        assert updated.user_locked is True

    def test_delete_nonexistent(self, db: Session):
        ok = delete_fact(db, "nonexistent-id")
        assert ok is False

    def test_update_nonexistent(self, db: Session):
        result = update_fact(db, "nonexistent-id", "text")
        assert result is None

    def test_active_facts_excludes_deleted(self, db: Session):
        f1 = create_fact(db, "Keep")
        f2 = create_fact(db, "Remove")
        delete_fact(db, f2.id)
        facts = get_active_facts(db)
        ids = {f.id for f in facts}
        assert f1.id in ids
        assert f2.id not in ids
