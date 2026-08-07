"""Case/result types for the reasoning eval harness.

Mirrors the dataclass shape already used by
``app/services/knowledge_packs/eval.py`` (frozen case, frozen aggregate
result, pure metric helpers) so there is one eval idiom in the codebase
rather than two.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

SUITES_DIR = Path(__file__).parent / "suites"


@dataclass(frozen=True)
class ReasoningCase:
    """One graded reasoning problem.

    ``grader`` selects how ``answer`` is compared to the model's output:
      ``numeric``  -- final number in the response must equal ``answer``
      ``mcq``      -- final choice letter must equal ``answer``
      ``contains`` -- every term in ``required_terms`` must appear
    See ``scoring.grade``.
    """

    id: str
    category: str
    question: str
    answer: str = ""
    grader: str = "numeric"
    choices: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ReasoningCase":
        return cls(
            id=str(raw["id"]),
            category=str(raw.get("category", "misc")),
            question=str(raw["question"]),
            answer=str(raw.get("answer", "")),
            grader=str(raw.get("grader", "numeric")),
            choices=[str(c) for c in raw.get("choices", []) or []],
            required_terms=[str(t) for t in raw.get("required_terms", []) or []],
        )


@dataclass(frozen=True)
class CaseResult:
    """Outcome of one case against one target."""

    case_id: str
    category: str
    correct: bool
    extracted: str
    expected: str
    latency_ms: float
    response: str = ""
    error: str = ""


@dataclass(frozen=True)
class SuiteResult:
    """Aggregate scorecard for one target over one suite."""

    target: str
    model: str
    cases: int
    correct: int
    accuracy: float
    by_category: dict[str, float]
    avg_latency_ms: float
    p95_latency_ms: float
    errors: int
    results: list[CaseResult] = field(default_factory=list)

    def to_dict(self, *, include_results: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "target": self.target,
            "model": self.model,
            "cases": self.cases,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "by_category": {k: round(v, 4) for k, v in sorted(self.by_category.items())},
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "errors": self.errors,
        }
        if include_results:
            out["results"] = [
                {
                    "case_id": r.case_id,
                    "category": r.category,
                    "correct": r.correct,
                    "extracted": r.extracted,
                    "expected": r.expected,
                    "latency_ms": round(r.latency_ms, 1),
                    "error": r.error,
                }
                for r in self.results
            ]
        return out


def summarize(target: str, model: str, results: Sequence[CaseResult]) -> SuiteResult:
    """Fold per-case results into a scorecard."""
    latencies = [r.latency_ms for r in results]
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r.correct)

    return SuiteResult(
        target=target,
        model=model,
        cases=len(results),
        correct=sum(1 for r in results if r.correct),
        accuracy=(sum(1 for r in results if r.correct) / len(results)) if results else 0.0,
        by_category={
            cat: (sum(1 for c in hits if c) / len(hits)) if hits else 0.0
            for cat, hits in by_cat.items()
        },
        avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
        # Matches the knowledge-pack harness: quantiles need >=2 points.
        p95_latency_ms=(
            statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 2
            else (latencies[0] if latencies else 0.0)
        ),
        errors=sum(1 for r in results if r.error),
        results=list(results),
    )


def load_cases(source: str | Path) -> list[ReasoningCase]:
    """Load cases from a JSONL file, or a bundled suite name.

    A bare name (``"reasoning_seed"``) resolves to ``suites/<name>.jsonl``;
    anything else is treated as a path, so external benchmark dumps work
    without being copied into the package.
    """
    path = Path(source)
    if not path.exists():
        candidate = SUITES_DIR / f"{source}.jsonl"
        if candidate.exists():
            path = candidate
        else:
            raise FileNotFoundError(
                f"No such suite or file: {source!r} "
                f"(looked for {candidate}). Available: {available_suites()}"
            )

    cases: list[ReasoningCase] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                cases.append(ReasoningCase.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{lineno}: bad case — {exc}") from exc
    if not cases:
        raise ValueError(f"{path} contained no cases")
    return cases


def available_suites() -> list[str]:
    if not SUITES_DIR.exists():
        return []
    return sorted(p.stem for p in SUITES_DIR.glob("*.jsonl"))


def filter_cases(
    cases: Iterable[ReasoningCase],
    *,
    category: str | None = None,
    limit: int | None = None,
) -> list[ReasoningCase]:
    out = [c for c in cases if category is None or c.category == category]
    return out[:limit] if limit else out
