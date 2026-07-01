"""Pydantic-based memory configuration loader.

Loads settings from memory_config.json at import time with graceful
fallback to built-in defaults. All memory subsystem modules import
from this loader rather than reading raw constants.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RetrievalConfig(BaseModel):
    strategy: str = "cosine"
    default_top_k: int = 8
    min_similarity: float = 0.62
    exp0_strategy: str = "recency_only"


class VectorStoreConfig(BaseModel):
    backend: str = "bruteforce_cosine"
    sqlite_vec_enabled: bool = False
    allow_fallback: bool = True


class ExtractionConfig(BaseModel):
    enabled: bool = True
    mode: str = "async_two_phase"
    candidate_limit_per_turn: int = 6


class ReconciliationConfig(BaseModel):
    auto_memory_can_update_unlocked: bool = True
    auto_memory_can_delete_unlocked: bool = True
    auto_memory_can_overwrite_user_locked: bool = False


class UserFactsConfig(BaseModel):
    created_by_user_default_locked: bool = True
    delete_mode: str = "tombstone_locked"


class MemoryConfig(BaseModel):
    version: int = 1
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    reconciliation: ReconciliationConfig = Field(default_factory=ReconciliationConfig)
    user_facts: UserFactsConfig = Field(default_factory=UserFactsConfig)


# Constants that have no config equivalent — kept as module-level defaults.
EMBEDDING_MODEL_ID: str = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM: int = 384
MAX_FACTS_PER_TURN: int = 5

# Context budget tiers (tokens) — maps desired max context -> memory budget for archive retrieval.
CONTEXT_TIERS: dict[int, int] = {
    8192: 2048,
    16384: 4096,
    32768: 8192,
}
DEFAULT_CONTEXT_TIER: int = 16384

# Context budget for archive turns when tight.
TIGHT_ARCHIVE_TOP_K: int = 2
TIGHT_FACT_TOP_K: int = 3


def _find_config() -> Path:
    """Locate memory_config.json relative to this module's package."""
    module_dir = Path(__file__).resolve().parent
    candidate = module_dir / "memory_config.json"
    if candidate.exists():
        return candidate
    fallback = Path.cwd() / "memory_config.json"
    if fallback.exists():
        return fallback
    return candidate


def load_memory_config() -> MemoryConfig:
    """Load memory config from JSON file, falling back to Pydantic defaults."""
    config_path = _find_config()
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return MemoryConfig(**data)
    except FileNotFoundError:
        logger.warning("memory_config.json not found at %s; using defaults", config_path)
        return MemoryConfig()
    except Exception as exc:
        logger.error("Failed to load memory_config.json: %s; using defaults", exc)
        return MemoryConfig()


# Module-level cached config — loaded once at import time.
_config_cache: MemoryConfig | None = None


def get_memory_config() -> MemoryConfig:
    """Return the cached memory config (loaded once)."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_memory_config()
    return _config_cache


# ── Convenience accessors ─────────────────────────────────────────────────────

def get_similarity_threshold() -> float:
    """Return min_similarity from config (used as default threshold)."""
    return get_memory_config().retrieval.min_similarity


def get_default_top_k() -> int:
    """Return default_top_k from config."""
    return get_memory_config().retrieval.default_top_k


def get_extraction_limit() -> int:
    """Return candidate_limit_per_turn from config."""
    return get_memory_config().extraction.candidate_limit_per_turn


def get_vector_backend() -> str:
    """Return vector store backend name."""
    return get_memory_config().vector_store.backend
