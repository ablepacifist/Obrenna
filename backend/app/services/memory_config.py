"""Constants for the memory subsystem."""
from __future__ import annotations

# Cosine similarity threshold for retrieval
SIMILARITY_THRESHOLD: float = 0.60

# Default retrieval top-k
ARCHIVE_TOP_K: int = 3
FACT_TOP_K: int = 5

# Embedding model settings
EMBEDDING_MODEL_ID: str = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM: int = 384

# Context budget tiers (tokens) — maps desired max context → memory budget for archive retrieval
CONTEXT_TIERS: dict[int, int] = {
    8192: 2048,
    16384: 4096,
    32768: 8192,
}

# Default fallback tier
DEFAULT_CONTEXT_TIER: int = 16384

# Fact extraction max facts per turn
MAX_FACTS_PER_TURN: int = 5

# Context budget for archive turns when tight
TIGHT_ARCHIVE_TOP_K: int = 2
TIGHT_FACT_TOP_K: int = 3
