"""Knowledge pack runtime primitives.

The v1 implementation keeps knowledge packs local, signed, versioned, and
read-only at runtime. Retrieval is handled by SQLite + pure Python scoring so
older CPUs do not need extra native extensions.
"""

from .eval import RetrievalEvalCase, RetrievalEvalResult, run_retrieval_eval
from .retriever import KnowledgeCardHit, KnowledgeContext, KnowledgePackRetriever
from .schema import PACK_SCHEMA_VERSION, PACK_VECTOR_DIM, create_pack_schema_sql

__all__ = [
    "KnowledgeCardHit",
    "KnowledgeContext",
    "KnowledgePackRetriever",
    "RetrievalEvalCase",
    "RetrievalEvalResult",
    "PACK_SCHEMA_VERSION",
    "PACK_VECTOR_DIM",
    "create_pack_schema_sql",
    "run_retrieval_eval",
]