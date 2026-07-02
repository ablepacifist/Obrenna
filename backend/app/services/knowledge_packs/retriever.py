"""Hybrid retrieval for local Obrenna knowledge packs.

v1 intentionally keeps the implementation small and portable:
- SQLite pack files on disk
- pure Python similarity scoring
- optional embeddings via the project's existing fastembed wrapper
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..embeddings import embed_text
from .schema import PACK_VECTOR_DIM

logger = logging.getLogger(__name__)

Embedder = Callable[[str], list[float] | None]


@dataclass(frozen=True)
class KnowledgeCardHit:
    """A scored knowledge-card result returned by pack retrieval."""

    id: str
    topic: str
    card_type: str
    content: str
    confidence: float
    score: float
    pack_path: str
    origin: str = "direct"
    expanded_from: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for prompt assembly."""

        return {
            "id": self.id,
            "topic": self.topic,
            "card_type": self.card_type,
            "content": self.content,
            "confidence": self.confidence,
            "score": self.score,
            "pack_path": self.pack_path,
            "origin": self.origin,
            "expanded_from": list(self.expanded_from),
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class KnowledgeContext:
    """Retrieval payload used by the orchestrator or prompt builder."""

    query: str
    cards: list[KnowledgeCardHit]
    graph_hints: list[dict[str, Any]] = field(default_factory=list)
    pack_paths: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Serialize the strongest cards into a compact prompt block."""

        lines: list[str] = []
        for index, card in enumerate(self.cards, start=1):
            lines.append(
                f"[{index}] {card.card_type.upper()} | {card.topic} | score={card.score:.3f}\n"
                f"{card.content}"
            )
        if self.graph_hints:
            lines.append("GRAPH HINTS:\n" + "\n".join(
                f"- {hint.get('from_id')} -[{hint.get('relation')}]-> {hint.get('to_id')}"
                for hint in self.graph_hints
            ))
        return "\n\n".join(lines)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9_]{2,}", text.lower())
    return set(tokens)


def _cosine_similarity(left: Sequence[float], right_blob: bytes, expected_dim: int = PACK_VECTOR_DIM) -> float:
    """Compute cosine similarity between an embedding and a packed float32 blob."""

    if not left or not right_blob:
        return 0.0
    if len(right_blob) % 4 != 0:
        return 0.0

    right_dim = len(right_blob) // 4
    if right_dim != expected_dim or len(left) != expected_dim:
        return 0.0

    right = struct.unpack(f"<{right_dim}f", right_blob)
    dot = sum(l * r for l, r in zip(left, right))
    left_mag = math.sqrt(sum(l * l for l in left))
    right_mag = math.sqrt(sum(r * r for r in right))
    if left_mag == 0.0 or right_mag == 0.0:
        return 0.0
    return dot / (left_mag * right_mag)


def _keyword_score(query_terms: set[str], text: str) -> float:
    """Score direct term overlap to preserve exact-name / exact-shape matches."""

    if not query_terms:
        return 0.0
    candidate_terms = _tokenize(text)
    if not candidate_terms:
        return 0.0
    overlap = len(query_terms & candidate_terms)
    if overlap == 0:
        return 0.0
    return overlap / max(len(query_terms), 1)


def _normalize_source_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in raw.split(",") if part.strip()]


def _fts_available(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_cards_fts' LIMIT 1").fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _clean_query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]{2,}", query.lower()) if token]


class KnowledgePackRetriever:
    """Search one or more local pack SQLite files."""

    def __init__(
        self,
        pack_paths: Sequence[str | Path],
        *,
        embedder: Embedder | None = None,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.3,
        confidence_weight: float = 0.1,
        edge_weight: float = 0.15,
    ) -> None:
        self._pack_paths = [str(Path(path)) for path in pack_paths]
        self._embedder = embedder or embed_text
        self._vector_weight = vector_weight
        self._keyword_weight = keyword_weight
        self._confidence_weight = confidence_weight
        self._edge_weight = edge_weight
        # SQLite connection-per-pack pool (Fix #7). Pack files are read-only,
        # so one shared connection per pack is safe across turns; the per-pack
        # lock serializes access because FastAPI may serve across threads.
        self._conn_cache: dict[str, sqlite3.Connection] = {}
        self._conn_locks: dict[str, threading.Lock] = {}
        self._pool_lock = threading.Lock()

    @property
    def pack_paths(self) -> list[str]:
        return list(self._pack_paths)

    def _get_conn(self, pack_path: str) -> tuple[sqlite3.Connection, threading.Lock]:
        """Return the pooled (connection, lock) for a pack, opening it on first use."""
        with self._pool_lock:
            conn = self._conn_cache.get(pack_path)
            if conn is None:
                conn = sqlite3.connect(pack_path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                lock = threading.Lock()
                self._conn_cache[pack_path] = conn
                self._conn_locks[pack_path] = lock
            else:
                lock = self._conn_locks[pack_path]
            return conn, lock

    def close(self) -> None:
        """Close every pooled connection (process teardown / singleton rebuild)."""
        with self._pool_lock:
            for conn in self._conn_cache.values():
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - best-effort teardown
                    pass
            self._conn_cache.clear()
            self._conn_locks.clear()

    def search(
        self,
        query: str,
        *,
        packs: Sequence[str | Path] | None = None,
        max_cards: int = 8,
        min_score: float = 0.25,
        max_tokens: int = 1200,
    ) -> KnowledgeContext:
        """Return the highest-scoring cards from the selected packs."""

        pack_paths = [str(Path(path)) for path in (packs or self._pack_paths)]
        query_vector = self._embedder(query) or []
        query_terms = _tokenize(query)
        query_tokens = _clean_query_tokens(query)
        hits: list[KnowledgeCardHit] = []
        graph_hints: list[dict[str, Any]] = []

        for pack_path in pack_paths:
            if not Path(pack_path).exists():
                logger.warning("knowledge pack missing: %s", pack_path)
                continue

            conn, conn_lock = self._get_conn(pack_path)
            with conn_lock:
                try:
                    cursor = conn.cursor()
                    candidate_ids: set[str] | None = None
                    if _fts_available(conn) and query_tokens:
                        try:
                            fts_query = " OR ".join(f'"{token}"' for token in query_tokens)
                            rows = conn.execute(
                                "SELECT card_id FROM knowledge_cards_fts WHERE knowledge_cards_fts MATCH ? LIMIT 50",
                                (fts_query,),
                            ).fetchall()
                            candidate_ids = {str(row[0]) for row in rows}
                        except sqlite3.Error:
                            candidate_ids = None

                    if candidate_ids:
                        placeholders = ",".join(["?"] * len(candidate_ids))
                        cards = cursor.execute(
                            f"SELECT id, topic, card_type, content, search_text, source_ids, confidence FROM knowledge_cards WHERE id IN ({placeholders})",
                            tuple(candidate_ids),
                        ).fetchall()
                    else:
                        cards = cursor.execute(
                            "SELECT id, topic, card_type, content, search_text, source_ids, confidence "
                            "FROM knowledge_cards"
                        ).fetchall()

                    for card_row in cards:
                        vector_row = cursor.execute(
                            "SELECT vector, vector_dim FROM card_vectors WHERE card_id = ?",
                            (card_row["id"],),
                        ).fetchone()

                        vector_score = 0.0
                        if vector_row is not None:
                            vector_score = _cosine_similarity(
                                query_vector,
                                vector_row["vector"],
                                expected_dim=int(vector_row["vector_dim"] or PACK_VECTOR_DIM),
                            )

                        keyword_text = " ".join(
                            part for part in [card_row["topic"], card_row["card_type"], card_row["search_text"], card_row["content"]] if part
                        )
                        keyword_score = _keyword_score(query_terms, keyword_text)
                        confidence = float(card_row["confidence"] or 0.0)

                        score = (
                            self._vector_weight * vector_score
                            + self._keyword_weight * keyword_score
                            + self._confidence_weight * confidence
                        )
                        if score < min_score:
                            continue

                        hits.append(
                            KnowledgeCardHit(
                                id=str(card_row["id"]),
                                topic=str(card_row["topic"]),
                                card_type=str(card_row["card_type"]),
                                content=str(card_row["content"]),
                                confidence=confidence,
                                score=score,
                                pack_path=pack_path,
                                origin="direct",
                                source_ids=_normalize_source_ids(card_row["source_ids"]),
                            )
                        )

                    expanded_hits, expanded_hints = self._expand_one_hop(conn, pack_path, hits, query_terms)
                    hits.extend(expanded_hits)
                    graph_hints.extend(expanded_hints)
                except sqlite3.Error as exc:
                    logger.warning("failed to read knowledge pack %s: %s", pack_path, exc)

        unique: dict[str, KnowledgeCardHit] = {}
        for hit in hits:
            existing = unique.get(hit.id)
            if existing is None or hit.score > existing.score:
                unique[hit.id] = hit
        hits = list(unique.values())
        hits.sort(key=lambda item: item.score, reverse=True)
        trimmed = self._trim_to_token_budget(hits[:max_cards], max_tokens)
        return KnowledgeContext(query=query, cards=trimmed, graph_hints=graph_hints, pack_paths=pack_paths)

    def _expand_one_hop(
        self,
        conn: sqlite3.Connection,
        pack_path: str,
        direct_hits: list[KnowledgeCardHit],
        query_terms: set[str],
    ) -> tuple[list[KnowledgeCardHit], list[dict[str, Any]]]:
        direct_card_ids = [hit.id for hit in direct_hits]
        if not direct_card_ids:
            return [], []

        placeholders = ",".join(["?"] * len(direct_card_ids))
        source_rows = conn.execute(
            f"SELECT DISTINCT source_id FROM card_sources WHERE card_id IN ({placeholders})",
            tuple(direct_card_ids),
        ).fetchall()
        source_ids = sorted({str(row[0]) for row in source_rows if str(row[0])})
        if not source_ids:
            return [], []

        expanded: list[KnowledgeCardHit] = []
        hints: list[dict[str, Any]] = []

        edge_placeholders = ",".join(["?"] * len(source_ids))
        edge_rows = conn.execute(
            f"SELECT from_id, relation, to_id, weight FROM pack_edges WHERE from_id IN ({edge_placeholders}) OR to_id IN ({edge_placeholders})",
            tuple(source_ids + source_ids),
        ).fetchall()
        neighbor_ids = sorted(
            {
                str(row["from_id"]) if str(row["from_id"]) not in source_ids else str(row["to_id"])
                for row in edge_rows
            }
        )
        for row in edge_rows:
            hints.append(
                {
                    "from_id": str(row["from_id"]),
                    "relation": str(row["relation"]),
                    "to_id": str(row["to_id"]),
                    "weight": float(row["weight"] or 1.0),
                }
            )

        if not neighbor_ids:
            return [], hints

        placeholders = ",".join(["?"] * len(neighbor_ids))
        rows = conn.execute(
            f"SELECT DISTINCT c.id, c.topic, c.card_type, c.content, c.search_text, c.source_ids, c.confidence "
            f"FROM knowledge_cards c JOIN card_sources s ON s.card_id = c.id WHERE s.source_id IN ({placeholders})",
            tuple(neighbor_ids),
        ).fetchall()
        direct_ids = set(direct_card_ids)
        for row in rows:
            card_id = str(row["id"])
            if card_id in direct_ids:
                continue
            confidence = float(row["confidence"] or 0.0)
            candidate_text = " ".join(
                part for part in [str(row["topic"]), str(row["card_type"]), str(row["search_text"]), str(row["content"])] if part
            )
            if _keyword_score(query_terms, candidate_text) <= 0.0:
                continue
            support_sources = _normalize_source_ids(row["source_ids"])
            if not support_sources:
                continue
            expanded.append(
                KnowledgeCardHit(
                    id=card_id,
                    topic=str(row["topic"]),
                    card_type=str(row["card_type"]),
                    content=str(row["content"]),
                    confidence=confidence,
                    score=self._edge_weight * confidence,
                    pack_path=pack_path,
                    origin="edge_expansion",
                    expanded_from=neighbor_ids,
                    source_ids=support_sources,
                )
            )
        return expanded, hints

    def _trim_to_token_budget(self, cards: list[KnowledgeCardHit], max_tokens: int) -> list[KnowledgeCardHit]:
        if max_tokens <= 0:
            return []

        kept: list[KnowledgeCardHit] = []
        used_tokens = 0
        for card in cards:
            approx_tokens = max(1, len(card.content.split()) // 2 + len(card.topic.split()))
            if kept and used_tokens + approx_tokens > max_tokens:
                break
            kept.append(card)
            used_tokens += approx_tokens
        return kept


def pack_card_vector_blob(vector: Sequence[float]) -> bytes:
    """Pack a float32 embedding into a SQLite-ready blob."""

    values = list(vector)
    if len(values) != PACK_VECTOR_DIM:
        raise ValueError(f"Expected {PACK_VECTOR_DIM} floats, got {len(values)}")
    return struct.pack(f"<{PACK_VECTOR_DIM}f", *values)
