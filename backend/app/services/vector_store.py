"""Vector similarity search for chat turns and memory facts.

Uses brute-force cosine similarity over embeddings stored in regular columns.
sqlite-vec is not required and not used.
"""
from __future__ import annotations

import logging
from math import sqrt

from sqlalchemy.orm import Session

from ..services.embeddings import embed_text
from ..services.memory_config import (
    FACT_TOP_K,
    SIMILARITY_THRESHOLD,
    TIGHT_ARCHIVE_TOP_K,
)

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sqrt(sum(x * x for x in a))
    mag_b = sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def insert_turn_vector(db: Session, turn_id: str, text_content: str) -> bool:
    """Embed text and store; no-op if embedding unavailable."""
    vec = embed_text(text_content)
    if vec is None:
        return False
    # Embeddings are computed on the fly during search — nothing to persist separately.
    return True


def insert_fact_vector(db: Session, fact_id: str, text_content: str) -> bool:
    """Embed text and store; no-op if embedding unavailable."""
    vec = embed_text(text_content)
    if vec is None:
        return False
    return True


def delete_turn_vector(db: Session, turn_id: str) -> None:
    pass  # no separate vector store to clean up


def delete_fact_vector(db: Session, fact_id: str) -> None:
    pass  # no separate vector store to clean up


def search_turns(
    db: Session,
    chat_id: str,
    query_text: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[tuple[float, str]]:
    """Return (similarity, turn_id) pairs for the most relevant archived turns."""
    if top_k is None:
        top_k = TIGHT_ARCHIVE_TOP_K
    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    query_vec = embed_text(query_text)
    if query_vec is None:
        return []

    from ..models import ChatTurn

    try:
        turns = (
            db.query(ChatTurn)
            .filter_by(chat_id=chat_id)
            .order_by(ChatTurn.turn_index.desc())
            .limit(top_k * 3)
            .all()
        )
        scored: list[tuple[float, str]] = []
        for turn in turns:
            tv = embed_text(f"{turn.user_text} {turn.assistant_text}")
            if tv is None:
                continue
            sim = _cosine(query_vec, tv)
            if sim >= threshold:
                scored.append((sim, turn.id))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[:top_k]
    except Exception as exc:
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
) -> list[tuple[float, str, str]]:
    """Return (similarity, fact_id, fact_text) for the most relevant memory facts."""
    if top_k is None:
        top_k = FACT_TOP_K
    if threshold is None:
        threshold = SIMILARITY_THRESHOLD

    query_vec = embed_text(query_text)
    if query_vec is None:
        return []

    from ..models import MemoryFact

    try:
        query = db.query(MemoryFact).filter(MemoryFact.account_id == MemoryFact.ACCOUNT_ID)
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
    except Exception as exc:
        logger.warning("Fact search failed: %s", exc)
        return []
