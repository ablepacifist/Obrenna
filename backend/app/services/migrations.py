"""Idempotent schema upgrades and backfill for memory tables."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Chat, ChatMessage, ChatTurn

logger = logging.getLogger(__name__)

VECTOR_EMBEDDING_DIM = 384


def _column_exists(tx, table: str, column: str) -> bool:
    # PRAGMA doesn't support bind parameters in many sqlite versions
    cols = tx.execute(
        text(f"PRAGMA table_info({table})")
    ).mappings().fetchall()
    return any(c["name"] == column for c in cols)


def _table_exists(tx, table: str) -> bool:
    rows = tx.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table}
    ).fetchall()
    return bool(rows)


def run_migrations(db: Session) -> None:
    """Add missing columns/tables, create sqlite-vec virtual tables, backfill turns.

    All operations are idempotent — safe to run multiple times.
    """
    def _migrate():
        # --- settings_app.managed_plan ---
        if not _column_exists(db, "settings_app", "managed_plan"):
            db.execute(text("ALTER TABLE settings_app ADD COLUMN managed_plan JSON NOT NULL DEFAULT '{}'"))

        # --- chats.rolling_summary ---
        if not _column_exists(db, "chats", "rolling_summary"):
            db.execute(text("ALTER TABLE chats ADD COLUMN rolling_summary TEXT NOT NULL DEFAULT ''"))

        # --- chats.summarized_upto_turn_index ---
        if not _column_exists(db, "chats", "summarized_upto_turn_index"):
            db.execute(
                text("ALTER TABLE chats ADD COLUMN summarized_upto_turn_index INTEGER NOT NULL DEFAULT -1")
            )

        # --- chat_turns table ---
        if not _table_exists(db, "chat_turns"):
            db.execute(text("""
                CREATE TABLE chat_turns (
                    id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                    turn_index INTEGER NOT NULL,
                    user_message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
                    assistant_message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
                    user_text TEXT NOT NULL DEFAULT '',
                    assistant_text TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP NOT NULL
                )
            """))
            db.execute(text(
                "CREATE UNIQUE INDEX idx_turns_chat_index ON chat_turns(chat_id, turn_index)"
            ))

        # --- memory_facts table ---
        if not _table_exists(db, "memory_facts"):
            db.execute(text("""
                CREATE TABLE memory_facts (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL DEFAULT 'local-default',
                    fact_text TEXT NOT NULL,
                    source_chat_id TEXT,
                    user_locked INTEGER NOT NULL DEFAULT 0,
                    deleted_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """))

        # --- chat_turn_vectors (sqlite-vec) ---
        if not _table_exists(db, "chat_turn_vectors"):
            db.execute(text(f"""
                CREATE VIRTUAL TABLE chat_turn_vectors USING vec0(
                    embedding float[{VECTOR_EMBEDDING_DIM}]
                )
            """))

        # --- memory_fact_vectors (sqlite-vec) ---
        if not _table_exists(db, "memory_fact_vectors"):
            db.execute(text(f"""
                CREATE VIRTUAL TABLE memory_fact_vectors USING vec0(
                    embedding float[{VECTOR_EMBEDDING_DIM}]
                )
            """))

    try:
        _migrate()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Migration failed: %s", exc)

    # Backfill turns (idempotent — skips already-archived)
    backfill_turns(db)


def backfill_turns(db: Session) -> int:
    """Pair user/assistant messages into ChatTurn rows. Returns count created."""
    existing = set()
    for t in db.query(ChatTurn.user_message_id).all():
        existing.add(t[0])

    chats = db.query(Chat.id).all()
    count = 0

    for (chat_id,) in chats:
        msgs = (
            db.query(ChatMessage)
            .filter_by(chat_id=chat_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

        last_user = None
        idx = 0
        for msg in msgs:
            if msg.role == "user" and msg.id not in existing:
                last_user = msg
            elif msg.role == "assistant" and last_user is not None:
                if last_user.id not in existing:
                    db.add(ChatTurn(
                        id=uuid.uuid4().hex,
                        chat_id=chat_id,
                        turn_index=idx,
                        user_message_id=last_user.id,
                        assistant_message_id=msg.id,
                        user_text=last_user.text,
                        assistant_text=msg.text,
                        created_at=msg.created_at,
                    ))
                    existing.add(last_user.id)
                    count += 1
                last_user = None
                idx += 1
            elif msg.role == "user" and last_user is not None and msg.id not in existing:
                # Unpaired user message (no following assistant) — skip
                last_user = None

    if count > 0:
        db.commit()

    logger.info("Backfilled %d chat turns.", count)
    return count
