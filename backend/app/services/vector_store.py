"""Vector similarity search for chat turns and memory facts.

Uses brute-force cosine similarity over embeddings computed on-the-fly
from persisted SQLite rows. Wraps the VectorStore ABC interface.

sqlite-vec is not currently active unless explicitly implemented and
enabled in memory_config.json.
"""
from __future__ import annotations

import logging
from math import sqrt
from typing import Sequence

from sqlalchemy.orm import Session

from ..services.embeddings import embed_text
from ..services.memory_config import (
    TIGHT_ARCHIVE_TOP_K,
    get_default_top_k,
    get_memory_config,
    get_similarity_threshold,
    get_vector_backend,
)
from .vector_store_base import VectorHit, VectorStore

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sqrt(sum(x * x for x in a))
    mag_b = sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Brute-force implementation ────────────────────────────────────────────────


class BruteForceCosineStore(VectorStore):
    """VectorStore backed by on-the-fly cosine over persisted SQLite rows.

    Embeddings are not stored in a separate index — they are computed
    from chat_turns and memory_facts text columns at search time.
    """

    def upsert(self, item_id: str, embedding: Sequence[float], record_type: str) -> None:
        """Embed text and cache; no DB write — embeddings are recomputed on demand."""
        pass

    def delete(self, item_id: str, record_type: str) -> None:
        """No separate cache to clean up."""
        pass

    def search(
        self,
        query_embedding: Sequence[float],
        record_type: str,
        top_k: int,
        min_similarity: float,
    ) -> list[VectorHit]:
        """Search persisted rows for similarity matches."""
        from ..models import ChatTurn, MemoryFact

        try:
            if record_type == "turn":
                return self._search_turns(query_embedding, top_k, min_similarity)
            elif record_type == "fact":
                return self._search_facts(query_embedding, top_k, min_similarity)
            else:
                logger.warning("Unknown record_type: %s", record_type)
                return []
        except Exception as exc:
            logger.warning("Vector search failed for %s: %s", record_type, exc)
            return []

    def _search_turns(
        self,
        query_vec: list[float],
        top_k: int,
        min_similarity: float,
    ) -> list[VectorHit]:
        """Search chat_turns table."""
        # Note: this needs a session — callers pass chat_id via wrapper
        raise NotImplementedError(
            "BruteForceCosineStore.search_turns requires a chat_id; "
            "use the module-level search_turns wrapper instead."
        )

    def _search_facts(
        self,
        query_vec: list[float],
        top_k: int,
        min_similarity: float,
    ) -> list[VectorHit]:
        """Search memory_facts table."""
        # Note: this needs a session — callers pass via wrapper
        raise NotImplementedError(
            "BruteForceCosineStore.search_facts requires a session; "
            "use the module-level search_facts wrapper instead."
        )


# ── Module-level singleton (backward compatible) ─────────────────────────────


_store: BruteForceCosineStore | None = None


def _get_store() -> BruteForceCosineStore:
    global _store
    if _store is None:
        backend = get_vector_backend()
        if backend == "bruteforce_cosine":
            _store = BruteForceCosineStore()
        elif backend == "sqlite_vec":
            raise NotImplementedError(
                "sqlite_vec backend is not yet implemented. "
                "Enable bruteforce_cosine in memory_config.json."
            )
        else:
            _store = BruteForceCosineStore()
    return _store


# ── Insert helpers ────────────────────────────────────────────────────────────


def insert_turn_vector(db: Session, turn_id: str, text_content: str) -> bool:
    """Embed text and store; no-op if embedding unavailable."""
    vec = embed_text(text_content)
    if vec is None:
        return False
    _get_store().upsert(turn_id, vec, "turn")
    return True


def insert_fact_vector(db: Session, fact_id: str, text_content: str) -> bool:
    """Embed text and store; no-op if embedding unavailable."""
    vec = embed_text(text_content)
    if vec is None:
        return False
    _get_store().upsert(fact_id, vec, "fact")
    return True


def delete_turn_vector(db: Session, turn_id: str) -> None:
    """Remove turn embedding from store."""
    _get_store().delete(turn_id, "turn")


def delete_fact_vector(db: Session, fact_id: str) -> None:
    """Remove fact embedding from store."""
    _get_store().delete(fact_id, "fact")


# ── Search wrappers ───────────────────────────────────────────────────────────


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
        threshold = get_similarity_threshold()

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
        top_k = get_default_top_k()
    if threshold is None:
        threshold = get_similarity_threshold()

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
