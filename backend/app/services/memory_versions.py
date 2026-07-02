"""Version counters that invalidate the memory retrieval cache (Fix #7).

Every write that changes a cached memory artifact bumps a counter *in the same
DB transaction* as the write. The retrieval cache (``services/memory_cache.py``)
keys cached artifacts on these counters, so a bump atomically invalidates them.
Counters use SQLite ``INSERT ... ON CONFLICT ... RETURNING`` so the bump and the
read of the new value are a single statement; callers commit alongside their
data write so the version change is atomic with the data change.

Counters:
- ``account_memory_version`` — bumped on any fact ADD/UPDATE/DELETE/reconcile.
  Invalidates the cached account facts block and the assembled memory context.
  Because user_locked-fact writes also bump this counter, the cache can never
  serve a stale locked fact — a locked-fact edit invalidates immediately and the
  next turn re-reads locked facts fresh (the brief's "full versioned design").
- ``chat_memory_version`` — bumped on turn record. Invalidates the assembled
  context (recency buffer + archived-turn search results change).
- ``chats.rolling_summary_version`` — bumped on summary fold. Invalidates the
  assembled context (rolling summary text changes).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session


_BUMP_ACCOUNT_SQL = text(
    """
    INSERT INTO account_memory_version (account_id, version, updated_at)
    VALUES (:aid, 2, :now)
    ON CONFLICT(account_id) DO UPDATE SET
        version = account_memory_version.version + 1,
        updated_at = :now
    RETURNING version
    """
)

_BUMP_CHAT_SQL = text(
    """
    INSERT INTO chat_memory_version (chat_id, version, updated_at)
    VALUES (:cid, 2, :now)
    ON CONFLICT(chat_id) DO UPDATE SET
        version = chat_memory_version.version + 1,
        updated_at = :now
    RETURNING version
    """
)


def get_account_version(db: Session, account_id: str) -> int:
    """Current account version (default 1 when no write has occurred yet)."""
    row = db.execute(
        text("SELECT version FROM account_memory_version WHERE account_id = :aid"),
        {"aid": account_id},
    ).first()
    return int(row[0]) if row else 1


def bump_account_version(db: Session, account_id: str) -> int:
    """Increment the account version counter (creating the row on first write).

    Does NOT commit — the caller commits alongside its fact write so the bump
    is atomic with the data change. Returns the new version value.
    """
    now = datetime.now(timezone.utc)
    row = db.execute(_BUMP_ACCOUNT_SQL, {"aid": account_id, "now": now}).first()
    return int(row[0]) if row else get_account_version(db, account_id)


def get_chat_version(db: Session, chat_id: str) -> int:
    """Current chat version (default 1 when no turn has been recorded yet)."""
    row = db.execute(
        text("SELECT version FROM chat_memory_version WHERE chat_id = :cid"),
        {"cid": chat_id},
    ).first()
    return int(row[0]) if row else 1


def bump_chat_version(db: Session, chat_id: str) -> int:
    """Increment the chat version counter (creating the row on first record).

    Does NOT commit — the caller commits alongside the turn write. Returns the
    new version value.
    """
    now = datetime.now(timezone.utc)
    row = db.execute(_BUMP_CHAT_SQL, {"cid": chat_id, "now": now}).first()
    return int(row[0]) if row else get_chat_version(db, chat_id)


def get_rolling_summary_version(db: Session, chat_id: str) -> int:
    """Current rolling-summary version (default 1 when never folded)."""
    row = db.execute(
        text("SELECT rolling_summary_version FROM chats WHERE id = :cid"),
        {"cid": chat_id},
    ).first()
    if row is None:
        return 1
    val = row[0]
    return int(val) if val is not None else 1


def bump_rolling_summary_version(db: Session, chat_id: str) -> int:
    """Increment the rolling-summary version column on the chat row.

    Does NOT commit — the caller commits alongside the summary write.
    """
    db.execute(
        text(
            "UPDATE chats SET rolling_summary_version = rolling_summary_version + 1 "
            "WHERE id = :cid"
        ),
        {"cid": chat_id},
    )
    return get_rolling_summary_version(db, chat_id)