"""Tests for memory fact lock semantics and reconciliation."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL
from app.db import Base
from app.models import MemoryFact
from app.services.memory import _add_fact, create_fact, update_fact, delete_fact, extract_and_reconcile_facts
from app.services.migrations import run_migrations


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


class TestFactLockSemantics:
    def test_create_fact_user_source_defaults_locked(self, db: Session):
        """User-created facts should default to user_locked=True."""
        fact = create_fact(db, "User created fact", "chat001")
        assert fact is not None
        assert fact.user_locked is True

    def test_create_fact_auto_source_defaults_unlocked(self, db: Session):
        """Auto-extracted facts should default to user_locked=False."""
        fact = _add_fact(db, "Auto extracted fact", "chat001", source="auto")
        assert fact is not None
        assert fact.user_locked is False

    def test_update_fact_preserves_locked(self, db: Session):
        """Updating a user fact should preserve user_locked=True."""
        fact = create_fact(db, "User created fact")
        assert fact.user_locked is True
        updated = update_fact(db, fact.id, "Updated text")
        assert updated is not None
        assert updated.user_locked is True
        assert updated.fact_text == "Updated text"

    def test_delete_fact_tombstones_locked_fact(self, db: Session):
        """Deleting a fact should tombstone it and keep user_locked=True."""
        fact = create_fact(db, "To be deleted")
        assert fact.user_locked is True
        ok = delete_fact(db, fact.id)
        assert ok is True
        stored = db.query(MemoryFact).filter_by(id=fact.id).first()
        assert stored is not None
        assert stored.deleted_at is not None
        assert stored.user_locked is True

    def test_auto_memory_cannot_overwrite_user_locked_fact(self, db: Session):
        """Auto-memory extraction should not be able to update user-locked facts."""
        user_fact = create_fact(db, "User's fact that should not change")
        assert user_fact.user_locked is True

        # Simulate extract_and_reconcile_facts behavior for a similar candidate
        # The reconciliation should skip locked facts
        # We test this by checking that the auto-memory actor can't call update_fact
        result = update_fact(db, user_fact.id, "Auto updated text", actor="auto")
        assert result is None

    def test_auto_actor_cannot_delete_fact(self, db: Session):
        """Auto-memory should not be able to delete facts."""
        fact = create_fact(db, "Should not be deletable by auto")
        ok = delete_fact(db, fact.id, actor="auto")
        assert ok is False

    def test_user_actor_can_delete_fact(self, db: Session):
        """User should be able to delete facts."""
        fact = create_fact(db, "User can delete")
        ok = delete_fact(db, fact.id, actor="user")
        assert ok is True

    def test_auto_actor_cannot_update_fact(self, db: Session):
        """Auto-memory should not be able to call update_fact directly."""
        fact = create_fact(db, "Should not be updatable by auto")
        result = update_fact(db, fact.id, "Auto update attempt", actor="auto")
        assert result is None
