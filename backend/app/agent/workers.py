"""Worker dispatch and summarizer orchestration.

Handles parallel utility worker execution with timeouts, failure markers,
and summarizer evidence-pack folding.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..model_runtime.config import RuntimeConfig
from ..model_runtime.streaming import chat_completion_stream

logger = logging.getLogger(__name__)


# ── Worker result types ──────────────────────────────────────────────────────


class WorkerStatus(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    INVALID_OUTPUT = "invalid_output"


@dataclass(slots=True)
class WorkerResult:
    """Result from a single utility worker task."""
    worker_id: str
    status: WorkerStatus
    output: Any = None
    error_message: str = ""

    def to_evidence_entry(self) -> dict[str, Any]:
        if self.status == WorkerStatus.SUCCESS:
            return {"worker_id": self.worker_id, "status": "success", "output": self.output}
        return {
            "worker_id": self.worker_id,
            "status": self.status.value,
            "error": self.error_message,
        }


# ── Evidence pack ────────────────────────────────────────────────────────────


@dataclass
class EvidencePack:
    """Compact evidence pack for the summarizer."""
    entries: list[dict] = field(default_factory=list)
    failure_count: int = 0

    def to_compact_string(self) -> str:
        """Format the evidence pack as a compact prompt string."""
        if not self.entries:
            return "No worker results available."
        lines = []
        for entry in self.entries:
            if entry.get("status") == "success":
                output = entry.get("output", "")
                if isinstance(output, dict):
                    lines.append(f"[Worker {entry['worker_id']}]: {json.dumps(output)}")
                elif isinstance(output, str):
                    lines.append(f"[Worker {entry['worker_id']}]: {output}")
            else:
                error = entry.get("error", "unknown error")
                lines.append(f"[Worker {entry['worker_id']}]: FAILED ({entry['status']}) — {error}")
        return "\n".join(lines) if lines else "No worker results available."


# ── Worker dispatch ──────────────────────────────────────────────────────────


async def dispatch_workers(
    tasks: list[dict[str, Any]],
    config: RuntimeConfig,
    utility_model: str,
    system_prompt: str,
    *,
    helper_count: int,
    timeout_seconds: int = 12,
    workers_enabled: bool = True,
) -> list[WorkerResult]:
    """Dispatch utility worker tasks with concurrency control.

    Args:
        tasks: List of {worker_id, user_prompt} dicts.
        config: Runtime config for the model endpoint.
        utility_model: Model name for utility role.
        system_prompt: System prompt for all workers.
        helper_count: Max concurrent workers (from hardware resolver).
        timeout_seconds: Per-worker timeout.
        workers_enabled: If False, return empty results immediately.

    Returns:
        List of WorkerResult, one per task.
        Failed workers get status=timeout/error/invalid_output — never raise.
    """
    if not workers_enabled:
        logger.info("Workers disabled — skipping worker dispatch")
        return []
    
    semaphore = asyncio.Semaphore(helper_count)
    results: list[WorkerResult] = []

    async def _run_single(task: dict) -> WorkerResult:
        wid = task.get("worker_id", uuid.uuid4().hex)
        user_prompt = task.get("user_prompt", "")

        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    _execute_worker(config, utility_model, system_prompt, user_prompt),
                    timeout=timeout_seconds,
                )
                if result is None:
                    return WorkerResult(
                        worker_id=wid,
                        status=WorkerStatus.INVALID_OUTPUT,
                        error_message="Worker returned no output",
                    )
                # Try to parse as JSON if the worker is expected to produce JSON
                if isinstance(result, str):
                    try:
                        parsed = json.loads(result)
                        return WorkerResult(worker_id=wid, status=WorkerStatus.SUCCESS, output=parsed)
                    except json.JSONDecodeError:
                        pass
                return WorkerResult(worker_id=wid, status=WorkerStatus.SUCCESS, output=result)
            except asyncio.TimeoutError:
                return WorkerResult(
                    worker_id=wid,
                    status=WorkerStatus.TIMEOUT,
                    error_message=f"Worker timed out after {timeout_seconds}s",
                )
            except Exception as exc:
                return WorkerResult(
                    worker_id=wid,
                    status=WorkerStatus.ERROR,
                    error_message=str(exc),
                )

    # Run all workers concurrently (semaphore limits concurrency)
    coros = [_run_single(t) for t in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)

    # Handle any unexpected exceptions from gather
    final_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            wid = tasks[i].get("worker_id", uuid.uuid4().hex)
            final_results.append(WorkerResult(
                worker_id=wid, status=WorkerStatus.ERROR, error_message=str(r),
            ))
        else:
            final_results.append(r)

    return final_results


async def _execute_worker(
    config: RuntimeConfig,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str | None:
    """Execute a single worker task via streaming."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    collected = []
    try:
        async for event in chat_completion_stream(
            config, messages, model=model, role="utility",
            temperature=0.1, timeout=15.0,
        ):
            if isinstance(event, dict) and event.get("type") == "token":
                collected.append(event["content"])
            elif isinstance(event, str):
                collected.append(event)
    except Exception as exc:
        logger.warning("Worker execution failed: %s", exc)
        return None

    return "".join(collected) if collected else None


# ── Summarizer ───────────────────────────────────────────────────────────────


async def summarize_into_evidence_pack(
    config: RuntimeConfig,
    summarizer_model: str,
    evidence_pack: EvidencePack,
    *,
    summarizer_prompt: str | None = None,
) -> tuple[str, bool]:
    """Fold worker results through the summarizer.

    Args:
        config: Runtime config.
        summarizer_model: Model name for summarizer role.
        evidence_pack: The compiled evidence pack.
        summarizer_prompt: Optional custom system prompt.

    Returns:
        (summary_text, success) — success=False means summarizer failed.
        On failure, the caller should hard-abort the turn.
    """
    if summarizer_prompt is None:
        summarizer_prompt = (
            "You are a summarizer for an AI assistant. "
            "Read the following worker results and produce a concise, "
            "structured summary that the assistant can use as context.\n\n"
            "Include only what is relevant. Mark clearly any workers that failed.\n"
            "Output plain text only."
        )

    evidence_str = evidence_pack.to_compact_string()
    messages = [
        {"role": "system", "content": summarizer_prompt},
        {"role": "user", "content": f"Worker results:\n{evidence_str}"},
    ]

    try:
        summary = await _collect_from_stream(
            config, messages, model=summarizer_model, role="summarizer",
            temperature=0.1, timeout=30.0,
        )
        return summary.strip(), True
    except Exception as exc:
        logger.error("Summarizer failed: %s", exc)
        return "", False


async def _collect_from_stream(
    config: RuntimeConfig,
    messages: list[dict],
    *,
    model: str,
    role: str,
    temperature: float,
    timeout: float,
) -> str:
    """Collect all tokens from a streaming call into one string."""
    collected = []
    try:
        async for event in chat_completion_stream(
            config, messages, model=model, role=role,
            temperature=temperature, timeout=timeout,
        ):
            if isinstance(event, dict) and event.get("type") == "token":
                collected.append(event["content"])
            elif isinstance(event, str):
                collected.append(event)
    except Exception as exc:
        raise RuntimeError(f"Stream collection failed: {exc}") from exc
    return "".join(collected)
