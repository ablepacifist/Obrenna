"""Reasoning-quality eval harness.

The runtime is instrumented for latency only (``TurnTelemetry`` tracks
time-to-first-token, tool runtimes, token counts) -- nothing measures whether
an answer is *correct*. That makes every "this improved reasoning" claim
unfalsifiable, so this package exists to produce a scorecard that can be
diffed across changes.

Design notes:

* **Offline by default.** A curated seed suite ships in ``suites/`` so the
  harness runs with no network and no dataset downloads. Public benchmarks
  (GSM8K, ARC, BBH) load from external JSONL via ``--cases`` when available.
* **Same call path as production.** Local runs go through
  ``model_runtime.client.chat_completion_sync``, the function the app itself
  uses, so a scorecard reflects the real stack rather than a parallel one.
* **Deterministic grading.** Graders are exact/numeric/multiple-choice rather
  than model-judged, so a score change means the model changed -- not that the
  judge drifted.
"""

from .cases import CaseResult, ReasoningCase, SuiteResult, load_cases
from .scoring import grade

__all__ = [
    "CaseResult",
    "ReasoningCase",
    "SuiteResult",
    "grade",
    "load_cases",
]
