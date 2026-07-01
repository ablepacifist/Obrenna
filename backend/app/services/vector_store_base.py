"""Abstract base class for vector store backends.

Defines the interface that all vector store implementations must satisfy.
This allows swapping backends (brute-force cosine, sqlite-vec, etc.)
without changing retrieval call sites in memory.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class VectorHit:
    """A single hit from a vector similarity search."""
    id: str
    score: float


class VectorStore(ABC):
    """Abstract vector store interface."""

    @abstractmethod
    def upsert(self, item_id: str, embedding: Sequence[float], record_type: str) -> None:
        """Insert or update an embedding for the given item."""
        ...

    @abstractmethod
    def delete(self, item_id: str, record_type: str) -> None:
        """Remove an embedding from the store."""
        ...

    @abstractmethod
    def search(
        self,
        query_embedding: Sequence[float],
        record_type: str,
        top_k: int,
        min_similarity: float,
    ) -> list[VectorHit]:
        """Search for similar embeddings.

        Args:
            query_embedding: The query vector.
            record_type: The type of records to search (e.g. "turn", "fact").
            top_k: Maximum number of results to return.
            min_similarity: Minimum similarity score to include in results.

        Returns:
            List of VectorHit, sorted by score descending.
        """
        ...
