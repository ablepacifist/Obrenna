"""Tests for HIGH-007: user-locked memory facts must be retrievable.

``user_locked`` means "protected from auto-overwrite/delete by the fact
reconciler" (see memory.py::_reconcile_fact) — it is NOT a visibility flag.
Before the fix, ``vector_store.search_facts`` defaulted
``exclude_locked=True``, and ``assemble_context`` called it with that
default. Since user-created facts default to ``user_locked=True``
(``_add_fact``), this meant the user's own explicitly-saved memories were
never surfaced to the orchestrator — only auto-extracted (unlocked) facts
ever appeared in context.

fastembed is not installed in this test environment, so ``embed_text`` is
monkeypatched with a deterministic bag-of-words vector so cosine similarity
behaves predictably without the real ONNX model.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Chat, MemoryFact
from app.services.memory import assemble_context
from app.services.migrations import run_migrations


_VOCAB = ["teal", "python", "rust", "color", "favorite", "language", "programming"]


def _fake_embed(text: str) -> list[float]:
    """Deterministic bag-of-words vector over a tiny fixed vocabulary."""
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
    chat = Chat(id="chat-locked-1", title="Locked fact retrieval test")
    db.add(chat)
    db.commit()
    return chat


def _make_fact(db: Session, text: str, *, user_locked: bool) -> MemoryFact:
    fact = MemoryFact(
        id=uuid.uuid4().hex,
        fact_text=text,
        user_locked=user_locked,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.commit()
    return fact


class TestSearchFactsExcludeLockedParam:
    """search_facts() itself keeps exclude_locked=True as its own default —
    the fix is at the assemble_context call site (below), which now passes
    exclude_locked=False explicitly. This just confirms the parameter still
    works both ways so callers can choose."""

    def test_exclude_locked_true_hides_locked_facts(self, db):
        from app.services.vector_store import search_facts

        _make_fact(db, "My favorite color is teal.", user_locked=True)

        results = search_facts(
            db, "What is my favorite color?", threshold=0.1, exclude_locked=True
        )
        texts = [r[2] for r in results]
        assert not any("teal" in t for t in texts)

    def test_exclude_locked_false_surfaces_locked_facts(self, db):
        from app.services.vector_store import search_facts

        _make_fact(db, "My favorite color is teal.", user_locked=True)
        _make_fact(db, "I write Rust programs.", user_locked=False)

        results = search_facts(db, "What is my favorite color?", threshold=0.1, exclude_locked=False)
        texts = [r[2] for r in results]
        assert any("teal" in t for t in texts), (
            "with exclude_locked=False, a user-locked fact must be retrievable — "
            "locked means protected from overwrite, not hidden from retrieval"
        )


class TestAssembleContextSurfacesLockedFacts:
    def test_user_created_locked_fact_appears_in_context(self, db, sample_chat):
        _make_fact(db, "My favorite programming language is Python.", user_locked=True)

        ctx = assemble_context(db, sample_chat, "What is my favorite programming language?")

        fact_texts = [f["text"] for f in ctx.facts]
        assert any("Python" in t for t in fact_texts), (
            "a user's own locked fact must reach the orchestrator context"
        )

    def test_auto_extracted_unlocked_fact_still_appears(self, db, sample_chat):
        _make_fact(db, "User's favorite programming language is Rust.", user_locked=False)

        ctx = assemble_context(db, sample_chat, "What is my favorite programming language?")

        fact_texts = [f["text"] for f in ctx.facts]
        assert any("Rust" in t for t in fact_texts)
