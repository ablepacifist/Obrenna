"""Runs a suite against a target and produces a scorecard."""

from __future__ import annotations

import time
from typing import Callable, Sequence

from .cases import CaseResult, ReasoningCase, SuiteResult, summarize
from .scoring import grade
from .targets import Target, build_prompt


def run_suite(
    target: Target,
    cases: Sequence[ReasoningCase],
    *,
    on_case: Callable[[CaseResult], None] | None = None,
) -> SuiteResult:
    """Score every case against ``target``.

    A failing case is recorded, never raised: one model error (timeout, refusal,
    dead endpoint) must not discard the other 30 results, and "how often did it
    error" is itself a quality signal worth having on the scorecard.
    """
    results: list[CaseResult] = []

    for case in cases:
        started = time.perf_counter()
        response = ""
        error = ""
        try:
            response = target.generate(build_prompt(case))
        except Exception as exc:  # noqa: BLE001 - a bad case must not kill the run
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0

        if error:
            correct, extracted = False, ""
        else:
            correct, extracted = grade(
                response,
                grader=case.grader,
                expected=case.answer,
                required_terms=case.required_terms,
                forbidden_terms=case.forbidden_terms,
            )

        result = CaseResult(
            case_id=case.id,
            category=case.category,
            correct=correct,
            extracted=extracted,
            expected=case.answer,
            latency_ms=latency_ms,
            response=response,
            error=error,
        )
        results.append(result)
        if on_case is not None:
            on_case(result)

    return summarize(target.name, target.model, results)


def format_scorecard(result: SuiteResult) -> str:
    """Human-readable single-target scorecard."""
    lines = [
        f"  target      {result.target} ({result.model})",
        f"  accuracy    {result.accuracy:.1%}  ({result.correct}/{result.cases})",
        f"  latency     {result.avg_latency_ms / 1000:.1f}s avg, "
        f"{result.p95_latency_ms / 1000:.1f}s p95",
    ]
    if result.errors:
        lines.append(f"  errors      {result.errors}")
    lines.append("  by category:")
    for cat, acc in sorted(result.by_category.items()):
        lines.append(f"    {cat:<14} {acc:.1%}")
    return "\n".join(lines)


def format_comparison(a: SuiteResult, b: SuiteResult) -> str:
    """Side-by-side scorecard — the point of the whole harness.

    The delta column is what makes "better than X" a measurable claim instead
    of an impression.
    """
    cats = sorted(set(a.by_category) | set(b.by_category))
    width = max([14] + [len(c) for c in cats])
    lines = [
        f"  {'':<{width}}  {a.target:>10}  {b.target:>10}  {'delta':>8}",
        f"  {'overall':<{width}}  {a.accuracy:>9.1%}  {b.accuracy:>9.1%}  "
        f"{a.accuracy - b.accuracy:>+8.1%}",
        "",
    ]
    for cat in cats:
        av = a.by_category.get(cat, 0.0)
        bv = b.by_category.get(cat, 0.0)
        lines.append(
            f"  {cat:<{width}}  {av:>9.1%}  {bv:>9.1%}  {av - bv:>+8.1%}"
        )
    lines += [
        "",
        f"  {'avg latency':<{width}}  {a.avg_latency_ms / 1000:>9.1f}s  "
        f"{b.avg_latency_ms / 1000:>9.1f}s",
    ]
    if a.errors or b.errors:
        lines.append(f"  {'errors':<{width}}  {a.errors:>10}  {b.errors:>10}")
    return "\n".join(lines)
