"""Bundled CPU embedding service using fastembed (ONNX-backed).

Fails gracefully if the embedding package or model assets are unavailable —
chat and memory retrieval degrade without crashing.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..services.memory_config import EMBEDDING_DIM, EMBEDDING_MODEL_ID

logger = logging.getLogger(__name__)

_model: Optional[object] = None
_initialized: bool = False


def _normalize_text(text: str) -> str:
    """Basic text normalization for embedding consistency."""
    text = text.lower()
    text = re.sub(r'[^\w\s\-_,.;:!?]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text or ""


def initialize() -> bool:
    """Lazy-load the embedding model. Returns True on success."""
    global _model, _initialized
    if _initialized:
        return _model is not None

    _initialized = True
    try:
        from fastembed import TextEmbedding  # noqa: PLC0414
        _model = TextEmbedding(model_name=EMBEDDING_MODEL_ID)  # type: ignore[assignment]
        logger.info("Embedding model loaded successfully.")
        return True
    except ImportError:
        logger.warning("fastembed not installed — memory retrieval disabled.")
        _model = None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load embedding model: %s — memory retrieval disabled.", exc)
        _model = None

    return False


def embed_text(text: str) -> list[float] | None:
    """Return a 384-dim embedding vector for *text*, or None if unavailable."""
    if _model is None:
        if not initialize():
            return None

    try:
        normalized = _normalize_text(text)
        if not normalized:
            return [0.0] * EMBEDDING_DIM
        result = list(_model.embed([normalized]))
        if not result or len(result) < 1:
            return None
        vec = list(result[0])
        if len(vec) != EMBEDDING_DIM:
            logger.warning(
                "Embedding dimension mismatch: got %d, expected %d", len(vec), EMBEDDING_DIM
            )
            return None
        return vec
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding failed: %s", exc)
        return None
