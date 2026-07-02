"""Retrieval eval harness for knowledge packs.

Measures retrieval precision/recall, factuality proxy checks, and latency on
the same retriever path used at runtime.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .retriever import KnowledgeContext, KnowledgePackRetriever


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    expected_card_ids: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalEvalResult:
    cases: int
    precision_at_k: float
    recall_at_k: float
    factuality_rate: float
    avg_latency_ms: float
    p95_latency_ms: float


def _precision_at_k(expected: set[str], returned: list[str]) -> float:
    if not returned:
        return 0.0
    return len(expected & set(returned)) / len(returned)


def _recall_at_k(expected: set[str], returned: list[str]) -> float:
    if not expected:
        return 1.0
    return len(expected & set(returned)) / len(expected)


def _factuality_proxy(context: KnowledgeContext, required_terms: list[str]) -> bool:
    if not required_terms:
        return True
    haystack = " ".join(card.content.lower() for card in context.cards)
    return all(term.lower() in haystack for term in required_terms)


def run_retrieval_eval(
    retriever: KnowledgePackRetriever,
    cases: Sequence[RetrievalEvalCase],
    *,
    top_k: int = 5,
) -> RetrievalEvalResult:
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    factuality_hits: list[bool] = []
    latencies_ms: list[float] = []

    for case in cases:
        started = time.perf_counter()
        context = retriever.search(case.query, max_cards=top_k)
        latency_ms = (time.perf_counter() - started) * 1000.0
        latencies_ms.append(latency_ms)

        returned_ids = [card.id for card in context.cards[:top_k]]
        expected_ids = set(case.expected_card_ids)
        precision_scores.append(_precision_at_k(expected_ids, returned_ids))
        recall_scores.append(_recall_at_k(expected_ids, returned_ids))
        factuality_hits.append(_factuality_proxy(context, case.required_terms))

    return RetrievalEvalResult(
        cases=len(cases),
        precision_at_k=statistics.mean(precision_scores) if precision_scores else 0.0,
        recall_at_k=statistics.mean(recall_scores) if recall_scores else 0.0,
        factuality_rate=(sum(1 for hit in factuality_hits if hit) / len(factuality_hits)) if factuality_hits else 0.0,
        avg_latency_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
        p95_latency_ms=statistics.quantiles(latencies_ms, n=20)[-1] if len(latencies_ms) >= 2 else (latencies_ms[0] if latencies_ms else 0.0),
    )
