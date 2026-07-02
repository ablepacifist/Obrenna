"""Version-keyed in-process cache for memory retrieval (Fix #7).

Never serves stale data. Every cached artifact is keyed by a version counter
from ``services/memory_versions.py`` that is bumped atomically (same DB
transaction) on any write changing that artifact. If a version counter is
missing or a knowledge-pack file's mtime changes, retrieval falls through to a
full rebuild — an unversioned cache is never shipped.

The account-memory-version counter is the correctness guard for user_locked
facts: any ADD/UPDATE/DELETE of a locked fact bumps it, invalidating the cached
facts block and assembled context, so the next turn re-reads locked facts
fresh. The facts block is therefore cached *by account version* rather than
re-read every turn — the version guard is what makes that safe (the brief's
"full versioned design").

This module is process-wide and thread-safe. It holds detached plain data only
(``MemoryContext`` is built from plain dicts/strings, never ORM objects), so
cached entries are safe to reuse across requests/sessions.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from typing import Any, Optional

_LOCK = threading.RLock()
_MAX_ENTRIES = 256  # per cache; bounded so a long-lived process never grows unbounded

# Assembled MemoryContext cache: composite version key -> MemoryContext.
_context_cache: "OrderedDict[tuple, Any]" = OrderedDict()

# Query embedding cache: (query_hash, embed_model_id) -> vector.
# Hits across the fact search, turn search, and knowledge-pack retriever in a
# single turn (all embed the same normalized user message).
_query_embedding_cache: "OrderedDict[tuple, list[float]]" = OrderedDict()

# Per-row embedding cache: (row_id, embed_model_id, fact_version) -> vector.
# Invalidated for a single row when that fact's own ``version`` bumps.
_row_embedding_cache: "OrderedDict[tuple, list[float]]" = OrderedDict()


def _evict(cache: "OrderedDict") -> None:
    while len(cache) > _MAX_ENTRIES:
        cache.popitem(last=False)


def normalize_query(text: str) -> str:
    """Stable normalization so equivalent queries share a cache key."""
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def query_hash(text: str) -> str:
    """SHA-1 of the normalized query (stable across processes, unlike hash())."""
    return hashlib.sha1(normalize_query(text).encode("utf-8")).hexdigest()


def make_context_key(
    chat_id: str,
    chat_version: int,
    summary_version: int,
    account_version: int,
    qhash: str,
    memory_mode: str,
    max_context_chars: Optional[int],
    pack_signature: tuple,
) -> tuple:
    """Composite key for the assembled memory context cache.

    Any version bump (chat turn, summary fold, account fact write) or query
    change or pack-file change invalidates the cached context.
    """
    return (
        chat_id,
        int(chat_version),
        int(summary_version),
        int(account_version),
        qhash,
        memory_mode,
        max_context_chars,
        pack_signature,
    )


# ── Assembled context cache ──────────────────────────────────────────────────


def get_context(key: tuple) -> Optional[Any]:
    with _LOCK:
        ctx = _context_cache.get(key)
        if ctx is not None:
            _context_cache.move_to_end(key)
        return ctx


def set_context(key: tuple, ctx: Any) -> None:
    with _LOCK:
        _context_cache[key] = ctx
        _context_cache.move_to_end(key)
        _evict(_context_cache)


# ── Query embedding cache ────────────────────────────────────────────────────


def get_query_embedding(qhash: str, embed_model_id: str) -> Optional[list[float]]:
    with _LOCK:
        return _query_embedding_cache.get((qhash, embed_model_id))


def set_query_embedding(qhash: str, embed_model_id: str, vec: list[float]) -> None:
    with _LOCK:
        _query_embedding_cache[(qhash, embed_model_id)] = vec
        _evict(_query_embedding_cache)


# ── Per-row embedding cache ──────────────────────────────────────────────────


def get_row_embedding(
    row_id: str, embed_model_id: str, version: int
) -> Optional[list[float]]:
    with _LOCK:
        return _row_embedding_cache.get((row_id, embed_model_id, int(version)))


def set_row_embedding(
    row_id: str, embed_model_id: str, version: int, vec: list[float]
) -> None:
    with _LOCK:
        _row_embedding_cache[(row_id, embed_model_id, int(version))] = vec
        _evict(_row_embedding_cache)


def invalidate_row(row_id: str) -> None:
    """Drop every cached embedding for a row (all embed-model / version keys)."""
    with _LOCK:
        for key in [k for k in _row_embedding_cache if k[0] == row_id]:
            _row_embedding_cache.pop(key, None)


# ── Test support ─────────────────────────────────────────────────────────────


def reset() -> None:
    """Clear every cache (tests only)."""
    with _LOCK:
        _context_cache.clear()
        _query_embedding_cache.clear()
        _row_embedding_cache.clear()