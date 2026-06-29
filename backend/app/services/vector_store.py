"""sqlite-vec vector store for chat turns and memory facts.

Uses the active SQLAlchemy engine connection directly to load the
sqlite-vec extension and perform vector operations.
"""
from __future__ import annotations

import logging
from math import sqrt

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ..config import DATABASE_URL
from ..services.embeddings import embed_text
from ..services.memory_config import (
    EMBEDDING_DIM,
    FACT_TOP_K,
    SIMILARITY_THRESHOLD,
    TIGHT_ARCHIVE_TOP_K,
)

logger = logging.getLogger(__name__)

# Singleton engine for raw DBAPI access (needed for sqlite-vec extension loading)
_vec_engine = None


def _vec_engine():
    global _vec_engine
    if _vec_engine is None:
        _connect_args = {"check_same_thread": False}
        _vec_engine = create_engine(
            DATABASE_URL, connect_args=_connect_args, future=True
        )
    return _vec_engine


def _ensure_vec_loaded(conn) -> bool:
    """Load the sqlite-vec extension on the given connection. Returns success."""
    try:
        conn.execute(text("SELECT vec_version()"))
        return True
    except Exception:
        pass
    try:
        conn.execute(text("SELECT load_extension('sqlite-vec')"))
        return True
    except Exception:
        pass
    # Try common paths
    for path in (
        "sqlite-vec",
        "sqlite3-vec",
        "vec",
    ):
        try:
            conn.execute(text(f"SELECT load_extension('{path}')"))
            return True
        except Exception:
            continue
    return False


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sqrt(sum(x * x for x in a))
    mag_b = sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def insert_turn_vector(db: Session, turn_id: str, text_content: str) -> bool:
    """Embed *text_content* and insert into chat_turn_vectors keyed by turn_id."""
    vec = embed_text(text_content)
    if vec is None:
        return False
    try:
        conn = _vec_engine().connect()
        try:
            if not _ensure_vec_loaded(conn):
                logger.warning("sqlite-vec not available — turn vector not inserted.")
                return False
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO chat_turn_vectors(rowid, embedding) "
                    "VALUES (:rid, :vec)"
                ),
                {"rid": int(turn_id[:8], 16) if turn_id else 0, "vec": vec},
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to insert turn vector: %s", exc)
        return False


def insert_fact_vector(db: Session, fact_id: str, text_content: str) -> bool:
    """Embed *text_content* and insert into memory_fact_vectors keyed by fact_id."""
    vec = embed_text(text_content)
    if vec is None:
        return False
    try:
        conn = _vec_engine().connect()
        try:
            if not _ensure_vec_loaded(conn):
                logger.warning("sqlite-vec not available — fact vector not inserted.")
                return False
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO memory_fact_vectors(rowid, embedding) "
                    "VALUES (:rid, :vec)"
                ),
                {"rid": int(fact_id[:8], 16) if fact_id else 0, "vec": vec},
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to insert fact vector: %s", exc)
        return False


def delete_turn_vector(db: Session, turn_id: str) -> None:
    try:
        conn = _vec_engine().connect()
        try:
            _ensure_vec_loaded(conn)
            conn.execute(
                text("DELETE FROM chat_turn_vectors WHERE rowid = :rid"),
                {"rid": int(turn_id[:8], 16) if turn_id else 0},
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete turn vector: %s", exc)


def delete_fact_vector(db: Session, fact_id: str) -> None:
    try:
        conn = _vec_engine().connect()
        try:
            _ensure_vec_loaded(conn)
            conn.execute(
                text("DELETE FROM memory_fact_vectors WHERE rowid = :rid"),
                {"rid": int(fact_id[:8], 16) if fact_id else 0},
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete fact vector: %s", exc)


def search_turns(
    db: Session,
    chat_id: str,
    query_text: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[dict]:
    """Search archived turns within a single chat by similarity to *query_text*."""
    if top_k is None:
        top_k = TIGHT_ARCHIVE_TOP_K
    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    query_vec = embed_text(query_text)
    if query_vec is None:
        return []

    try:
        conn = _vec_engine().connect()
        try:
            _ensure_vec_loaded(conn)
            # Use sqlite-vec kNN search then filter by threshold
            results = conn.execute(
                text("""
                    SELECT v.rowid AS vec_id
                    FROM chat_turn_vectors v
                    LEFT JOIN chat_turns t ON t.id = :chat_prefix || substr(:vec_hex, 1)
                    WHERE v.embedding ?(:query)
                    ORDER BY v.distance ASC
                    LIMIT :limit
                """),
                {
                    "chat_prefix": chat_id[:8],
                    "vec_hex": hex(int(chat_id[:8], 16))[2:] if len(chat_id) >= 8 else "0",
                    "query": query_vec,
                    "limit": top_k * 3,  # fetch extra to filter by threshold
                },
            ).mappings().fetchall()

            # Fallback: since sqlite-vec join may not work directly, use brute-force
            from ..models import ChatTurn  # noqa: PLC0414

            turns = (
                db.query(ChatTurn)
                .filter_by(chat_id=chat_id)
                .order_by(ChatTurn.turn_index.desc())
                .limit(top_k * 3)
                .all()
            )
            scored: list[tuple[float, str]] = []
            for turn in turns:
                content = f"{turn.user_text} {turn.assistant_text}"
                tv = embed_text(content)
                if tv is None:
                    continue
                sim = _cosine(query_vec, tv)
                if sim >= threshold:
                    scored.append((sim, turn.id))

            scored.sort(key=lambda x: (-x[0], x[1]))
            return scored[:top_k]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Turn search failed: %s", exc)
        return []


def search_facts(
    db: Session,
    query_text: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    exclude_deleted: bool = True,
    exclude_locked: bool = True,
) -> list[dict]:
    """Search memory facts by similarity to *query_text*."""
    if top_k is None:
        top_k = FACT_TOP_K
    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    query_vec = embed_text(query_text)
    if query_vec is None:
        return []

    # Import here to avoid circular imports
    from ..models import ChatTurn, MemoryFact  # noqa: PLC0414

    try:
        conn = _vec_engine().connect()
        try:
            _ensure_vec_loaded(conn)
        finally:
            conn.close()
    except Exception:
        pass

    # Brute-force similarity search (safe, deterministic)
    query = db.query(MemoryFact).filter(
        MemoryFact.account_id == MemoryFact.ACCOUNT_ID,
    )
    if exclude_deleted:
        query = query.filter(MemoryFact.deleted_at.is_(None))
    if exclude_locked:
        query = query.filter(MemoryFact.user_locked == False)  # noqa: E712

    facts = query.order_by(MemoryFact.updated_at.desc()).limit(top_k * 3).all()

    scored: list[tuple[float, str, str]] = []
    for fact in facts:
        fv = embed_text(fact.fact_text)
        if fv is None:
            continue
        sim = _cosine(query_vec, fv)
        if sim >= threshold:
            scored.append((sim, fact.id, fact.fact_text))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:top_k]
