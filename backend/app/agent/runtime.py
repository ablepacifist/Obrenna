"""Agent runtime orchestration entry point.

This module orchestrates a single chat turn:
1. Assembles memory context
2. Optionally dispatches utility workers
3. Runs summarizer evidence-pack folding
4. Runs the orchestrator with MCP tool support
5. Emits typed streaming events
6. Returns the final response text
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from sqlalchemy.orm import Session

from ..mcp.client import InMemoryTransport
from ..mcp.tools import list_tools, call_tool, tool_def_by_name
from ..mcp.custom_tool_dispatch import (
    call_custom_tool,
    get_custom_tool_by_name,
    list_enabled_custom_tool_defs,
)
from ..mcp.codebase_tool_dispatch import (
    call_codebase_tool,
    get_active_codebase_project,
    list_enabled_codebase_tool_defs,
)
from ..model_runtime.config import RuntimeConfig
from .tool_narration import gather_narrations, narration_desc
from ..model_runtime.streaming import chat_completion_stream
from ..services.architecture_config import (
    get_config,
    get_orchestration_config,
    get_mcp_tools_config,
)
from ..services.hardware_resolver import choose_and_validate, build_fingerprint, build_live
from ..services.hardware_resolver import HardwareFingerprint, LiveFreeResources
from ..services.memory import assemble_context, MemoryContext
from ..services.telemetry import write_turn_telemetry
from ..services.runtime_context import (
    build_runtime_context_message,
    build_relative_date_hint_message,
)
from ..services.trace_logging import trace_event
from .events import (
    done_event,
    error_event,
    new_message_id,
    phase_event,
    telemetry_event,
    thinking_delta_event,
    token_event,
    tool_call_event,
    tool_progress_event,
    tool_result_event,
    StreamEvent,
)
from .workers import (
    dispatch_workers,
    EvidencePack,
    summarize_into_evidence_pack,
    WorkerStatus,
)

logger = logging.getLogger(__name__)


# ── ResolvedPlan adapter ─────────────────────────────────────────────────────


class ResolvedPlan:
    """Maps hardware_resolver.choose_and_validate() response to runtime fields."""

    def __init__(self, resolver_result: dict[str, Any]):
        self.raw = resolver_result
        self.path = resolver_result.get("path", "unknown")
        self.plan_id = resolver_result.get("plan_id", "")
        self.ctx = resolver_result.get("ctx", 8192)
        self.helper_count = resolver_result.get("helper_count", 1)
        self.orchestrator = resolver_result.get("orchestrator") or {}
        self.summarizer = resolver_result.get("summarizer") or {}
        self.utility = resolver_result.get("utility") or {}

    @property
    def orchestrator_model(self) -> str:
        return self.orchestrator.get("model", "")

    @property
    def orchestrator_tool_call_mode(self) -> str:
        """How this orchestrator emits tool calls.

        ``openai_native`` — the model emits OpenAI delta.tool_calls (parsed in
        streaming.py). ``prompt_json`` — the model lacks a native tool-call
        template, so the runtime injects a tool contract into the prompt and the
        streaming layer scans the text stream for a JSON envelope. Defaults to
        ``openai_native`` when the resolver didn't populate the field.
        """
        mode = self.orchestrator.get("tool_call_mode", "openai_native")
        return mode if mode in ("openai_native", "prompt_json") else "openai_native"

    @property
    def reasoning_distilled(self) -> bool:
        """Whether the orchestrator is a reasoning-distilled (always-CoT) model.

        Discriminator for the per-round thinking-effort lever: distilled models
        need in-stream CoT to form tool-call envelopes, stock models emit them
        structurally. Sourced from the catalog via the resolver (model identity),
        not inferred from ``tool_call_mode`` (transport). Defaults to False.
        """
        return bool(self.orchestrator.get("reasoning_distilled", False))

    @property
    def max_tool_rounds(self) -> int:
        """Per-orchestrator cap on chained tool calls in a single turn.

        Sourced from the catalog model_definition (via the resolver). Defaults to
        3 — a safe mid-tier value — when the resolver didn't populate it.
        """
        val = self.orchestrator.get("max_tool_rounds", 3)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
        return 3

    @property
    def tool_result_budget(self) -> int:
        """Per-orchestrator char budget for compacting a single tool result.

        Sourced from the catalog model_definition (via the resolver). Defaults to
        4000 chars when the resolver didn't populate it.
        """
        val = self.orchestrator.get("tool_result_budget", 4000)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
        return 4000

    @property
    def summarizer_model(self) -> str:
        return self.summarizer.get("model", "")

    @property
    def utility_model(self) -> str:
        return self.utility.get("model", "")

    @property
    def orchestrator_keep_alive(self):
        """Ollama keep_alive for the orchestrator (``-1`` = pin for the session).

        Sourced from the catalog via the resolver (never hardcoded here) so the
        orchestrator stays resident in VRAM/RAM across turns and avoids
        repeated cold-loads. ``None`` means the resolver didn't populate it.
        """
        return self.orchestrator.get("keep_alive")

    @property
    def orchestrator_stream_timeout(self) -> int | None:
        """Optional per-orchestrator stream read-timeout (seconds).

        A large model on constrained hardware (e.g. a 27B spilling past VRAM
        into RAM) can take far longer than the default to cold-load and to
        generate. When the plan/override sets this, it overrides the default
        ``worker_timeout_seconds * 10`` so the request isn't killed mid-answer.
        ``None`` = use the default.
        """
        val = self.orchestrator.get("stream_timeout_seconds")
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            return int(val)
        return None

    @property
    def utility_keep_alive(self):
        """Ollama keep_alive for utility workers (e.g. ``"5m"`` — evictable).

        Lazy residency: keep a worker loaded briefly after its last call, then
        evict to free RAM/VRAM for the orchestrator. ``None`` = don't send it.
        """
        return self.utility.get("keep_alive")

    @property
    def summarizer_keep_alive(self):
        """Ollama keep_alive for the summarizer (e.g. ``"10m"`` — evictable)."""
        return self.summarizer.get("keep_alive")


def build_resolved_plan(resolver_result: dict[str, Any]) -> ResolvedPlan:
    """Create a ResolvedPlan from the hardware resolver output."""
    return ResolvedPlan(resolver_result)


def is_exp0_plan(hardware_plan: dict[str, Any] | ResolvedPlan) -> bool:
    """Return True for the minimal 0.8B orchestrator plan."""
    plan = hardware_plan.raw if isinstance(hardware_plan, ResolvedPlan) else hardware_plan
    orchestrator = plan.get("orchestrator") or {}
    model = orchestrator.get("model") or plan.get("orchestrator_model") or ""
    tier = plan.get("tier") or plan.get("tier_class") or plan.get("plan_id") or ""
    return "exp0" in str(tier).lower() or "0.8b" in str(model).lower()


def classify_intent_fast(message: str, files: list[str] | None = None) -> str:
    """Classify only obvious routes without asking the small orchestrator."""
    text = message.lower()
    has_files = bool(files)
    if has_files and any(word in text for word in ("dashboard", "chart", "graph", "csv")):
        return "artifact_dashboard"
    if has_files and any(word in text for word in ("pdf", "report", "proposal", "brief")):
        return "artifact_report"
    if any(word in text for word in ("summarize", "summary")):
        return "summarize"
    if any(word in text for word in ("search", "research", "sources")):
        return "web_research"
    return "chat"


def route_requires_workers(intent: str) -> bool:
    """Worker fan-out is reserved for routes that benefit from extra evidence."""
    return intent in {"web_research", "artifact_dashboard", "artifact_report"}


# ── Deterministic per-turn routing ───────────────────────────────────────────
#
# Small distilled orchestrators are unreliable at choosing tools on their own,
# so obviously-classifiable requests are routed deterministically:
#   current/news queries  → web_search (or a clear "web is off" answer)
#   plain arithmetic      → calculator (expression normalised from prose)
#   time/date questions   → get_time
# The routed tool is executed BEFORE the first model pass and its result is fed
# in as tool evidence; the model still writes the final prose answer.

_NEWS_QUERY_RE = re.compile(r"\b(news|headlines?)\b", re.IGNORECASE)
_TIME_QUERY_RE = re.compile(
    r"\b(what time is it|current time|what'?s the time|time is it right now|"
    r"what day is (it|today)|today'?s date|what'?s the date|current date)\b",
    re.IGNORECASE,
)
_MATH_VERB_RE = re.compile(
    r"\b(calculate|compute|solve|evaluate|math|nearest (decimal|integer|whole))\b",
    re.IGNORECASE,
)
# "6*25+90 all divided by 4" → divide the ENTIRE preceding expression by 4.
_ALL_DIVIDED_RE = re.compile(
    r"\b(?:all|everything|the whole thing|the total)\s+divided\s+by\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_WORD_OPS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bmultiplied\s+by\b", re.IGNORECASE), " * "),
    (re.compile(r"\btimes\b", re.IGNORECASE), " * "),
    (re.compile(r"\bdivided\s+by\b", re.IGNORECASE), " / "),
    (re.compile(r"\bplus\b", re.IGNORECASE), " + "),
    (re.compile(r"\bminus\b", re.IGNORECASE), " - "),
]
_MATH_EXPR_RE = re.compile(r"[\d.(][\d\s.+\-*/%()]*")


def is_current_news_query(message: str) -> bool:
    """True for queries about news/headlines — inherently current information."""
    return bool(_NEWS_QUERY_RE.search(message or ""))


def extract_math_expression(message: str) -> str | None:
    """Deterministically normalise a natural-language arithmetic ask.

    Returns a pure calculator expression, or None when the message is not an
    unambiguous arithmetic request. "X all divided by N" parenthesises the
    whole preceding expression — "6*25+90 all divided by 4" → "(6*25+90)/4"
    (= 60.0), never the operator-precedence reading 6*25 + 90/4 (= 172.5).
    """
    text = message or ""
    divisor = None
    m = _ALL_DIVIDED_RE.search(text)
    if m:
        divisor = m.group(1)
        text = text[: m.start()] + " " + text[m.end():]
    for rx, sym in _WORD_OPS:
        text = rx.sub(sym, text)

    best: str | None = None
    for cand in _MATH_EXPR_RE.finditer(text):
        s = cand.group(0).strip()
        if re.search(r"\d", s) and re.search(r"[+\-*/%]", s):
            if best is None or len(s) > len(best):
                best = s
    if best is None:
        return None
    expr = best.strip().rstrip("+-*/%(. ")
    # Guard against prose false-positives (dates, ranges like "2-3pm"): route
    # only when the expression has 2+ operators, or the user explicitly asked
    # for a computation, or we saw an "all divided by" construction.
    op_count = len(re.findall(r"[+\-*/%]", expr))
    explicit = bool(_MATH_VERB_RE.search(message or "")) or divisor is not None
    if op_count < 2 and not explicit:
        return None
    if not re.fullmatch(r"[\d\s.+\-*/%()]+", expr):
        return None
    if divisor:
        expr = f"({expr})/{divisor}"
    return expr


def classify_deterministic_route(
    message: str,
    *,
    web_search_enabled: bool,
) -> tuple[str, dict] | None:
    """Return a forced (tool_name, arguments) route for obvious intents.

    ``("web_search_disabled", {})`` is a pseudo-route: the user asked for
    current news but web access is off — the runtime must answer that web
    access is needed instead of letting the model guess or replay stale text.
    """
    text = (message or "").strip()
    if not text:
        return None
    expr = extract_math_expression(text)
    if expr is not None:
        return ("calculator", {"expression": expr})
    if is_current_news_query(text):
        if web_search_enabled:
            return ("web_search", {"query": text})
        return ("web_search_disabled", {})
    if _TIME_QUERY_RE.search(text):
        return ("get_time", {})
    return None


WEB_DISABLED_NEWS_ANSWER = (
    "I can't look up current news right now because web search is turned off "
    "for this chat. Enable the web toggle and ask again, and I'll fetch the "
    "latest for you."
)

# Injected as a system message whenever the user has the web-search toggle ON.
# The model is already told the tool *exists* (via the prompt-JSON contract or
# the OpenAI tools field), but small distilled orchestrators tend to answer from
# memory unless pushed. This is the active nudge: the user explicitly opted into
# web access for this chat, so prefer `web_search` for anything that benefits
# from fresh or external information. Kept out of the deterministic router so it
# still applies to general factual/recent queries, not just obvious news asks.
CODEBASE_PROJECT_HINT_TEMPLATE = (
    "A codebase project named '{name}' is connected for this chat. You have real, "
    "live codebase_* tools available (codebase_list_directory, codebase_read_file, "
    "codebase_search, and possibly codebase_edit_file, codebase_write_file, "
    "codebase_delete_file, codebase_move_file, codebase_run_command) that act on "
    "actual files — and run real shell commands — in that project right now. This is "
    "not a placeholder or a description of a capability, it is a live connection. "
    "When the user refers to 'the project', 'the codebase', "
    "'the workspace', 'this repo', asks what you can see or access, or says they have "
    "'attached' something, they mean this connected project. Call a codebase_* tool "
    "to check before answering — never assume you lack access without having tried a "
    "tool call first.\n"
    "\n"
    "RULES FOR FILE ACTIONS — these prevent you from misleading the user:\n"
    "1. NEVER claim you created, edited, moved, or deleted a file unless a tool "
    "result in THIS turn confirmed it succeeded. If you have not called the tool "
    "yet, call it now — do not say 'Done!' first.\n"
    "2. Report file paths EXACTLY as they appear in the tool result's 'path' field, "
    "never from memory or assumption. If unsure where a file is, call "
    "codebase_list_directory or codebase_search to find it before naming a path.\n"
    "3. To MOVE or RENAME a file, use codebase_move_file — do not write a copy and "
    "leave the original. To DELETE a file, use codebase_delete_file — do not try to "
    "blank it with codebase_edit_file. To create a new file at the project root, use "
    "codebase_write_file with a bare filename like 'README.md' (no leading folder).\n"
    "4. Do not end your reply by promising to do something ('let me check…', 'I'll "
    "create it now'). Either call the tool in this same turn, or give the finished "
    "answer. A promise with no tool call is a failure.\n"
    "4b. When asked to BUILD or RUN something, write the files with "
    "codebase_write_file/codebase_edit_file, THEN actually run it with "
    "codebase_run_command and read the output. If exit_code is non-zero or stderr "
    "has an error, fix the code and run it again — iterate until it works before you "
    "report success. Never claim code runs without having run it.\n"
    "5. You DO have memory of your earlier actions this conversation: assistant "
    "turns are annotated with an '[Actions you actually performed this turn: …]' log "
    "of the real files you changed. Trust that log — never tell the user you have no "
    "record of files you created earlier."
)

WEB_SEARCH_HINT = (
    "The user has explicitly enabled web search for this chat, which signals "
    "they want answers grounded in fresh, external information rather than from "
    "your training memory alone. You have the `web_search` tool available — "
    "prefer to call it whenever the user's question would benefit from current, "
    "verifiable, or external facts: news, recent events, prices, releases, "
    "people, statistics, documentation, or anything where your knowledge could "
    "be stale or uncertain. When in doubt about whether a fact is current, "
    "search. Do NOT search for things you can compute or determine locally "
    "(arithmetic, the current time, the user's own files) or for pure opinion/"
    "creative tasks. After searching, cite the source URLs in your answer."
)


@dataclass
class TurnTelemetry:
    started_at: float
    first_event_at: float | None = None
    first_token_at: float | None = None
    context_done_at: float | None = None
    workers_done_at: float | None = None
    model_done_at: float | None = None
    done_at: float | None = None
    token_count: int = 0
    # ── Performance-pass instrumentation ───────────────────────────────────
    # Wall-clock around assemble_context() so retrieval caching (Fix #7) is
    # measurable.
    memory_context_runtime_ms: int | None = None
    # Per-tool-call wall-clock (ms), in execution order.
    tool_runtimes_ms: list[int] = None  # type: ignore[assignment]
    tool_round_count: int = 0
    # Total typed stream events emitted this turn (for coalescer before/after).
    stream_event_count: int = 0
    # Per-round Ollama eval counters captured from the terminal stream chunk.
    # Round 1 = first orchestrator call; keys: prompt_eval_count,
    # prompt_eval_duration, eval_count, eval_duration, usage.
    ollama_stats: dict[int, dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tool_runtimes_ms is None:
            self.tool_runtimes_ms = []
        if self.ollama_stats is None:
            self.ollama_stats = {}

    def mark_event(self) -> None:
        if self.first_event_at is None:
            self.first_event_at = time.perf_counter()
        self.stream_event_count += 1

    def mark_token(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()
        self.token_count += 1

    def record_tool_runtime(self, elapsed_s: float) -> None:
        self.tool_runtimes_ms.append(int(elapsed_s * 1000))

    def record_ollama_stats(self, round_no: int, stats: dict[str, Any]) -> None:
        if stats:
            self.ollama_stats[round_no] = stats

    def summary(self) -> dict[str, Any]:
        end = self.done_at or time.perf_counter()
        total = end - self.started_at
        # Derived prefix-cache indicator: if round 2 prefilled materially fewer
        # tokens than round 1, the Ollama prefix cache is hitting across rounds.
        prefix_cache_hit: bool | None = None
        if len(self.ollama_stats) >= 2:
            r1 = self.ollama_stats.get(1, {}).get("prompt_eval_count")
            r2 = self.ollama_stats.get(2, {}).get("prompt_eval_count")
            if isinstance(r1, (int, float)) and isinstance(r2, (int, float)) and r1 > 0:
                prefix_cache_hit = r2 < r1
        return {
            "time_to_first_event_ms": int(((self.first_event_at or end) - self.started_at) * 1000),
            "time_to_first_token_ms": (
                int((self.first_token_at - self.started_at) * 1000)
                if self.first_token_at
                else None
            ),
            "total_turn_ms": int(total * 1000),
            "context_assembly_ms": (
                int((self.context_done_at - self.started_at) * 1000)
                if self.context_done_at
                else None
            ),
            "worker_dispatch_ms": (
                int((self.workers_done_at - (self.context_done_at or self.started_at)) * 1000)
                if self.workers_done_at
                else None
            ),
            "model_request_ms": (
                int((self.model_done_at - (self.workers_done_at or self.context_done_at or self.started_at)) * 1000)
                if self.model_done_at
                else None
            ),
            "token_count": self.token_count,
            "tokens_per_second": round(self.token_count / total, 2) if total > 0 else None,
            "memory_context_runtime_ms": self.memory_context_runtime_ms,
            "tool_round_count": self.tool_round_count,
            "tool_runtime_ms": self.tool_runtimes_ms,
            "stream_event_count": self.stream_event_count,
            "prefix_cache_hit": prefix_cache_hit,
            "ollama_stats": self.ollama_stats,
        }


# ── Main orchestration ──────────────────────────────────────────────────────


async def _execute_with_narration(
    config: RuntimeConfig,
    calls: list[dict],
    exec_coro: "Any",
    *,
    narr_timeout: float = 2.0,
) -> tuple[list[dict], list]:
    """Run tool execution concurrently with helper-model narration.

    Narration starts the moment we know the calls and races the tool
    execution; after execution returns we give narration a short bounded
    moment to finish so the description usually lands before the result
    event flips the card to done. Returns (exec_results, narrations).
    """
    narration_task = asyncio.create_task(gather_narrations(config, calls))
    results = await exec_coro
    try:
        narrations = await asyncio.wait_for(narration_task, timeout=narr_timeout)
    except asyncio.TimeoutError:
        narration_task.cancel()
        narrations = [None] * len(calls)
    return results, narrations


async def orchestrate_turn(
    user_message: str,
    chat_id: str,
    db: Session,
    config: RuntimeConfig,
    resolved_plan: ResolvedPlan,
    *,
    file_ids: list[str] | None = None,
    previous_messages: list[dict] | None = None,
    assistant_message_id: str | None = None,
    web_search: bool = False,
    workers_enabled: bool = True,
    thinking_enabled: bool = False,
) -> AsyncIterator[StreamEvent]:
    """Orchestrate a single chat turn through the agent runtime.

    Yields typed StreamEvents (token, done, error, tool_call, tool_result, tool_progress)
    as the turn progresses. The caller should render these events to the UI
    and persist the final message.

    Tool invocation flow:
    1. Model called with tools → may return tool_calls
    2. Tool calls detected → execute each tool, yield progress/result events
    3. Tool results fed back as messages → call model again (no tools)
    4. Model streams final answer → yield token events

    Args:
        user_message: The user's input text.
        chat_id: The chat session ID.
        db: SQLAlchemy session.
        config: Runtime config for the model endpoint.
        resolved_plan: Hardware-resolved plan with model assignments.
        file_ids: Optional file IDs attached to the message.
        previous_messages: Optional prior conversation messages (for stateful turns).
        assistant_message_id: Optional pre-assigned message ID.
        web_search: Whether to include web_search tool in the allowed set.
        workers_enabled: Whether to enable worker models for this turn.

    Yields:
        StreamEvent instances for token/done/error/tool_call/tool_result/tool_progress.
    """
    msg_id = assistant_message_id or new_message_id()
    telemetry = TurnTelemetry(started_at=time.perf_counter())

    def tracked(event: StreamEvent) -> StreamEvent:
        telemetry.mark_event()
        return event

    async def _handle_tool_calls_with_trace(
        calls: list[dict],
        mcp_client: Any,
        ctx: dict[str, Any],
    ) -> list[dict]:
        try:
            return await handle_tool_calls(
                calls, mcp_client, trace_context=ctx, user_message=user_message, chat_id=chat_id,
            )
        except TypeError as exc:
            if "trace_context" not in str(exc):
                raise
            return await handle_tool_calls(calls, mcp_client)

    exp0_fast_path = is_exp0_plan(resolved_plan)
    fast_intent = classify_intent_fast(user_message, file_ids)
    skip_workers = exp0_fast_path and not route_requires_workers(fast_intent)
    use_workers = (
        workers_enabled
        and not skip_workers
        and resolved_plan.helper_count > 0
        and bool(resolved_plan.utility_model)
    )
    use_summarizer = bool(resolved_plan.summarizer_model)
    orchestration_cfg = get_orchestration_config()
    worker_timeout = orchestration_cfg.get("worker_timeout_seconds", 12)
    # Per-orchestrator-model cap on chained tool calls, sourced from the catalog
    # via the resolver (not the global config). The legacy
    # architecture_config.json::mcp_tools.max_tool_rounds key was miswired (read
    # from agent_runtime.orchestration, which never held it) and always fell back
    # to the hardcoded 5; it is now superseded by the resolved per-model value.
    max_tool_rounds = resolved_plan.max_tool_rounds
    # DEBUG, not INFO: user_message is private local content and must not
    # land in default-level logs on a local-first/private-by-default product.
    logger.debug("=== ORCHESTRATE TURN === chat_id=%s user_message=%r orchestrator_model=%s summarizer_model=%s utility_model=%s workers_enabled=%s", chat_id, user_message, resolved_plan.orchestrator_model, resolved_plan.summarizer_model, resolved_plan.utility_model, workers_enabled)
    trace_context = {"chat_id": chat_id, "message_id": msg_id}
    trace_event(
        "turn_start",
        **trace_context,
        user_message=user_message,
        file_ids=file_ids or [],
        previous_messages=previous_messages or [],
        web_search=web_search,
        workers_enabled=workers_enabled,
        thinking_enabled=thinking_enabled,
        fast_intent=fast_intent,
        skip_workers=skip_workers,
        use_workers=use_workers,
        use_summarizer=use_summarizer,
        plan={
            "path": resolved_plan.path,
            "ctx": resolved_plan.ctx,
            "helper_count": resolved_plan.helper_count,
            "orchestrator_model": resolved_plan.orchestrator_model,
            "summarizer_model": resolved_plan.summarizer_model,
            "utility_model": resolved_plan.utility_model,
            "tool_call_mode": resolved_plan.orchestrator_tool_call_mode,
        },
    )

    yield tracked(phase_event(chat_id, msg_id, "accepted", "Starting"))

    # Step 1: Assemble memory context
    try:
        if exp0_fast_path:
            yield tracked(phase_event(
                chat_id,
                msg_id,
                "exp0_fast_path",
                "Using lightweight local mode",
                "Recent context only",
            ))
        else:
            yield tracked(phase_event(chat_id, msg_id, "resolving_context", "Checking context"))
        yield tracked(phase_event(chat_id, msg_id, "memory", "Loading memory"))
        _mem_start = time.perf_counter()
        memory_ctx = assemble_context(
            db,
            type("Chat", (), {"id": chat_id})(),
            user_message,
            memory_mode="exp0_recency_only" if exp0_fast_path else "default",
            max_context_chars=4000 if exp0_fast_path else None,
            # When real conversation turns are already in the prompt, do NOT
            # also inject recent assistant replies as system context — the
            # duplicated previous answer is what small orchestrators replay.
            include_recency=not bool(previous_messages),
        )
        telemetry.memory_context_runtime_ms = int((time.perf_counter() - _mem_start) * 1000)
        # Fix #1: split the orchestrator's system content into a static,
        # cross-turn cacheable band (Band A) and a dynamic per-turn memory
        # band (Band B). The static band leads so Ollama's prefix cache
        # reuses it across turns; the dynamic, version-stamped band follows.
        static_parts = memory_ctx.to_static_messages()
        dynamic_parts = memory_ctx.to_dynamic_messages()
        trace_event(
            "memory_context_built",
            **trace_context,
            runtime_ms=telemetry.memory_context_runtime_ms,
            static_parts=static_parts,
            dynamic_parts=dynamic_parts,
        )
    except Exception as exc:
        logger.warning("Memory context assembly failed: %s", exc)
        trace_event("memory_context_error", **trace_context, error=str(exc))
        static_parts = []
        dynamic_parts = []
    telemetry.context_done_at = time.perf_counter()
    # The runtime only needs the DB for initial context assembly. End the
    # read transaction before slow worker/model/tool calls so SQLite does not
    # keep a shared lock open for the duration of generation.
    try:
        if db is not None and hasattr(db, "rollback"):
            db.rollback()
    except Exception as exc:
        logger.debug("Could not close context assembly DB transaction: %s", exc)

    # Step 2: Optional worker dispatch
    evidence_summary = ""
    if skip_workers:
        trace_event("workers_skipped", **trace_context, reason="exp0_lightweight_route")
        yield tracked(phase_event(
            chat_id,
            msg_id,
            "workers_skipped",
            "Skipping helper workers",
            "Lightweight route",
        ))
    if use_workers and previous_messages:
        yield tracked(phase_event(chat_id, msg_id, "workers", "Preparing helper tasks"))
        worker_tasks, system_prompt = _prepare_worker_tasks(
            user_message, dynamic_parts, resolved_plan
        )
        trace_event(
            "worker_tasks_prepared",
            **trace_context,
            system_prompt=system_prompt,
            tasks=worker_tasks,
        )
        if worker_tasks:
            worker_results = await dispatch_workers(
                worker_tasks, config, resolved_plan.utility_model, system_prompt,
                helper_count=resolved_plan.helper_count,
                timeout_seconds=worker_timeout,
                workers_enabled=workers_enabled,
                keep_alive=resolved_plan.utility_keep_alive,
                trace_context=trace_context,
            )
            evidence_pack = EvidencePack(
                entries=[r.to_evidence_entry() for r in worker_results],
                failure_count=sum(1 for r in worker_results if r.status != WorkerStatus.SUCCESS),
            )
            trace_event(
                "evidence_pack_built",
                **trace_context,
                entries=evidence_pack.entries,
                failure_count=evidence_pack.failure_count,
            )
            if use_summarizer and resolved_plan.summarizer_model:
                summary_text, success = await summarize_into_evidence_pack(
                    config, resolved_plan.summarizer_model, evidence_pack,
                    keep_alive=resolved_plan.summarizer_keep_alive,
                    trace_context=trace_context,
                )
                if success:
                    evidence_summary = summary_text
                else:
                    # Fallback: compact raw evidence
                    compact = evidence_pack.to_compact_string()
                    if compact and compact != "No worker results available.":
                        evidence_summary = compact
                    else:
                        yield error_event(
                            chat_id,
                            error_code="summarizer_failure",
                            message="Summarizer failed — aborting turn.",
                            recoverable=False,
                        )
                        return
            else:
                evidence_summary = evidence_pack.to_compact_string()
            trace_event("worker_evidence_summary", **trace_context, evidence_summary=evidence_summary)
    telemetry.workers_done_at = time.perf_counter()

    # Step 3: Resolve allowed tools + tool-call mode, then build orchestrator
    # messages. The prompt-JSON tool contract (if needed) is injected here so the
    # model knows the envelope format before it sees the user request.
    allowed_tools = (
        _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search)
        + list_enabled_custom_tool_defs()
        + list_enabled_codebase_tool_defs(chat_id)
    )
    tool_call_mode = resolved_plan.orchestrator_tool_call_mode
    trace_event(
        "tools_resolved",
        **trace_context,
        web_search_enabled=web_search,
        tool_call_mode=tool_call_mode,
        allowed_tools=allowed_tools,
    )

    # Deterministic routing for obvious intents (math/current-news/time). This
    # runs BEFORE any model call so a small orchestrator can't misroute them.
    forced_route = classify_deterministic_route(user_message, web_search_enabled=web_search)
    if forced_route:
        trace_event("deterministic_route", **trace_context, route=forced_route)
    if forced_route and forced_route[0] == "web_search_disabled":
        # Current-news ask with web off: answer honestly and deterministically —
        # never let the model guess or replay stale content.
        telemetry.mark_token()
        trace_event(
            "deterministic_response_complete",
            **trace_context,
            response=WEB_DISABLED_NEWS_ANSWER,
        )
        yield tracked(token_event(chat_id, text=WEB_DISABLED_NEWS_ANSWER, message_id=msg_id))
        telemetry.model_done_at = time.perf_counter()
        yield tracked(phase_event(chat_id, msg_id, "finalizing", "Finalizing"))
        telemetry.done_at = time.perf_counter()
        yield tracked(done_event(chat_id, message_id=msg_id))
        try:
            write_turn_telemetry(chat_id, telemetry.summary())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Telemetry sink write failed: %s", exc)
        return

    yield tracked(phase_event(chat_id, msg_id, "runtime_context", "Checking local date and time"))

    active_codebase_project = get_active_codebase_project(chat_id)
    orchestrator_messages = _build_orchestrator_messages(
        user_message, static_parts, dynamic_parts, evidence_summary, previous_messages or [],
        tool_call_mode=tool_call_mode, allowed_tools=allowed_tools,
        web_search_enabled=web_search,
        codebase_project_name=active_codebase_project.name if active_codebase_project else None,
    )
    # DEBUG, not INFO: message content is private local content.
    logger.debug("ORCHESTRATOR MESSAGES: %d messages, first_user=%r last_user=%r", len(orchestrator_messages), orchestrator_messages[0]["content"] if orchestrator_messages and len(orchestrator_messages) > 0 else "", orchestrator_messages[-1]["content"] if orchestrator_messages else "")
    trace_event(
        "orchestrator_messages_built",
        **trace_context,
        message_count=len(orchestrator_messages),
        messages=orchestrator_messages,
    )

    # Step 4: Prepare MCP client and tool definitions
    import os
    from ..mcp.client import get_mcp_manager, make_tcp_transport_factory
    from ..mcp.tools import acall_tool as _acall_tool

    # Check for MCP proxy URL (set by Rust Tauri when MCP server is available)
    proxy_url = os.getenv("OBRENNA_MCP_PROXY_URL")

    # Fix #6: one persistent MCP client per server for the process lifetime,
    # managed by MCPClientManager. The transport factory (re)builds the
    # transport on connect/reconnect; the manager caches the client and the
    # tools/list result so the per-turn initialize()+tools/list handshake only
    # happens once across the whole session.
    async def _dev_tools_call(params: dict) -> dict:
        result = await _acall_tool(params["name"], params.get("arguments", {}))
        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": bool(result.get("error", False)) if isinstance(result, dict) else False,
        }

    def _dev_transport_factory():
        # In-process transport for dev/testing. Wrap the raw tool result in
        # the same {content:[{type,text}], isError} envelope the stdio server
        # produces, so MCPClient.call_tool's parsing path behaves identically
        # to production. Handlers are stateless; registering per (re)build is
        # safe and cheap.
        transport = InMemoryTransport()
        transport.register_handler("tools/list", lambda p: {"tools": list_tools()})
        transport.register_handler("tools/call", _dev_tools_call)
        return transport

    if proxy_url:
        transport_factory = make_tcp_transport_factory(proxy_url)
    else:
        transport_factory = _dev_transport_factory

    mcp_client = await get_mcp_manager().connect("obrenna-mcp", transport_factory)

    # Native tool calling sends OpenAI tool definitions via the `tools` field;
    # prompt-JSON relies on the contract injected into the messages and the
    # streaming envelope scanner, so it never sends the OpenAI tools field.
    if tool_call_mode == "prompt_json":
        model_tools = None
    else:
        model_tools = _format_tools_for_model(allowed_tools) if allowed_tools else None

    # Step 5: Stream orchestrator response with tool support
    stream_timeout = resolved_plan.orchestrator_stream_timeout or orchestration_cfg.get("worker_timeout_seconds", 12) * 10
    tool_round = 0
    finalization_round = False
    last_tool_payloads: list[tuple[str, str]] = []
    all_tokens = []
    had_malformed_tool_call = False
    narration_nudge_used = False
    # Anti-loop state for repeated identical failing run_command calls.
    last_failed_run_cmd: str | None = None
    repeated_run_fail_count = 0
    run_fix_nudge_used = False

    # Step 4½: Execute a deterministically-routed tool BEFORE the first model
    # pass and feed its result in as tool evidence. The model still writes the
    # final prose; if it produces nothing, the existing tool-result fallback
    # guarantees a non-empty answer grounded in the tool output.
    if forced_route and forced_route[0] != "web_search_disabled":
        forced_name, forced_args = forced_route
        forced_call = {
            "id": "call_" + uuid.uuid4().hex[:12],
            "type": "function",
            "function": {"name": forced_name, "arguments": forced_args},
        }
        yield tracked(tool_call_event(
            chat_id=chat_id, tool_name=forced_name, call_id=forced_call["id"],
            arguments=forced_args, message_id=msg_id,
        ))
        _tool_start = time.perf_counter()
        forced_results, forced_narrations = await _execute_with_narration(
            config,
            [forced_call],
            _handle_tool_calls_with_trace(
                [forced_call],
                mcp_client,
                {**trace_context, "round": 0, "deterministic_route": True},
            ),
        )
        telemetry.record_tool_runtime(time.perf_counter() - _tool_start)
        # Emit a helper-model narration of what this tool is doing, landing
        # while the card is still `running` (before the result flips it done).
        forced_desc = narration_desc(forced_narrations[0], forced_name)
        if forced_desc:
            yield tracked(tool_progress_event(
                chat_id=chat_id, tool_name=forced_name, call_id=forced_call["id"],
                status="running", stage="narrating", summary=forced_desc,
                message_id=msg_id,
            ))
        forced_content = forced_results[0].get("content", "")
        yield tracked(tool_result_event(
            chat_id=chat_id, tool_name=forced_name, call_id=forced_call["id"],
            result=forced_content, message_id=msg_id,
        ))
        last_tool_payloads.append((forced_name, forced_content))
        if tool_call_mode == "prompt_json":
            orchestrator_messages.append({
                "role": "assistant",
                "content": _prompt_json_envelope_text(forced_name, forced_args),
            })
            orchestrator_messages.append({
                "role": "user",
                "content": _prompt_json_tool_result(forced_name, forced_content),
            })
            orchestrator_messages.append({
                "role": "user",
                "content": (
                    "Answer the latest user message now in natural language using the "
                    "TOOL_RESULT above. Do not repeat earlier answers and do not call "
                    "the same tool again."
                ),
            })
        else:
            orchestrator_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": forced_call["id"],
                    "type": "function",
                    "function": {
                        "name": forced_name,
                        "arguments": json.dumps(forced_args),
                    },
                }],
            })
            orchestrator_messages.append({
                "role": "tool",
                "tool_call_id": forced_call["id"],
                "content": forced_content,
            })

    yield tracked(phase_event(chat_id, msg_id, "model", "Writing response"))

    while tool_round < max_tool_rounds + 1:
        tool_round += 1
        telemetry.tool_round_count = tool_round
        detected_tool_calls = []
        malformed_retry = False

        try:
            logger.info("CALLING MODEL: model=%s temperature=%.1f round=%d tools=%s",
                        resolved_plan.orchestrator_model, 0.2, tool_round,
                        "yes" if model_tools else "no")
            reasoning_effort = _round_reasoning_effort(
                thinking_enabled, tool_round, finalization_round,
                resolved_plan.reasoning_distilled,
            )
            trace_event(
                "orchestrator_call_start",
                **trace_context,
                round=tool_round,
                finalization_round=finalization_round,
                model=resolved_plan.orchestrator_model,
                temperature=0.2,
                timeout=stream_timeout,
                tools_enabled=bool(model_tools),
                model_tools=model_tools,
                reasoning_effort=reasoning_effort,
                messages=orchestrator_messages,
            )
            async for event in chat_completion_stream(
                config,
                orchestrator_messages,
                model=resolved_plan.orchestrator_model,
                role="orchestrator",
                temperature=0.2,
                timeout=stream_timeout,
                tools=model_tools,
                think=reasoning_effort,
                tool_call_mode=tool_call_mode,
                keep_alive=resolved_plan.orchestrator_keep_alive,
                num_ctx=resolved_plan.ctx,
            ):
                if event.get("type") == "thinking_delta":
                    text = event.get("content", "") or event.get("text", "")
                    if text:
                        trace_event("orchestrator_thinking_delta", **trace_context, round=tool_round, text=text)
                        yield thinking_delta_event(chat_id, text=text, message_id=msg_id)
                    continue
                if event.get("type") == "stream_stats":
                    # Terminal Ollama eval/usage counters for this round.
                    telemetry.record_ollama_stats(tool_round, event.get("stats", {}))
                    continue
                if event.get("type") == "token":
                    text = event.get("content", "")
                    if text:
                        all_tokens.append(text)
                        telemetry.mark_token()
                        yield tracked(token_event(chat_id, text=text, message_id=msg_id))
                elif event.get("type") == "tool_calls_done":
                    calls = event.get("calls", [])
                    if calls:
                        trace_event("orchestrator_tool_calls", **trace_context, round=tool_round, calls=calls)
                        if finalization_round:
                            # The finalization pass exists only to turn already
                            # collected tool evidence into natural language. If
                            # the model tries to call tools again, do not run an
                            # unbounded loop or finish empty; emit a safe answer
                            # from the tool results we already have.
                            logger.warning(
                                "Model requested tools during forced finalization; using tool-result fallback."
                            )
                            fallback = _fallback_answer_from_tool_results(user_message, last_tool_payloads)
                            if fallback:
                                all_tokens.append(fallback)
                                telemetry.mark_token()
                                yield tracked(token_event(chat_id, text=fallback, message_id=msg_id))
                            detected_tool_calls = []
                            break
                        detected_tool_calls = calls
                        # Yield individual tool_call events for each tool
                        for tc in calls:
                            fn = tc.get("function", {})
                            yield tracked(tool_call_event(
                                chat_id=chat_id,
                                tool_name=fn.get("name", ""),
                                call_id=tc.get("id", ""),
                                arguments=fn.get("arguments", {}) if isinstance(fn.get("arguments"), dict) else {},
                                message_id=msg_id,
                            ))
                        # Yield progress event
                        yield tracked(tool_progress_event(
                            chat_id=chat_id,
                            tool_name=f"({len(calls)} tool(s))",
                            status="running",
                            summary="Executing tool calls...",
                            message_id=msg_id,
                            stage="executing",
                            current=0,
                            total=len(calls),
                        ))

                        # Execute tool calls
                        _tool_start = time.perf_counter()
                        tool_results, narrations = await _execute_with_narration(
                            config,
                            calls,
                            _handle_tool_calls_with_trace(
                                calls,
                                mcp_client,
                                {**trace_context, "round": tool_round},
                            ),
                        )
                        telemetry.record_tool_runtime(time.perf_counter() - _tool_start)
                        # Emit per-call helper-model narration before the
                        # result events so each card describes what it is
                        # doing while still `running`.
                        for tc, narration in zip(calls, narrations):
                            _fn = tc.get("function", {})
                            _name = _fn.get("name", "")
                            _desc = narration_desc(narration, _name)
                            if _desc:
                                yield tracked(tool_progress_event(
                                    chat_id=chat_id, tool_name=_name,
                                    call_id=tc.get("id", ""), status="running",
                                    stage="narrating", summary=_desc,
                                    message_id=msg_id,
                                ))
                        # Compact tool results before feed-back: structural trim
                        # bounds context growth (the "blows context" anti-pattern
                        # that model_tools=None was compensating for). Both feed-back
                        # branches and last_tool_payloads read result.content, so this
                        # single chokepoint covers every path. Per-result budget is
                        # sourced from the catalog via resolved_plan.tool_result_budget.
                        raw_chars, compacted_chars = _compact_tool_results(
                            tool_results, calls, resolved_plan.tool_result_budget,
                        )
                        trace_event(
                            "tool_result_compaction",
                            **trace_context,
                            round=tool_round,
                            raw_chars=raw_chars,
                            compacted_chars=compacted_chars,
                            per_result_budget=resolved_plan.tool_result_budget,
                        )
                        tool_round_results = 0
                        executed = []  # (tool_call, call_id, content)
                        for tc, result in zip(calls, tool_results):
                            tool_name = result.get("tool_name") or tc.get("function", {}).get("name", "unknown")
                            call_id = result.get("tool_call_id", "")
                            content = result.get("content", "")
                            # Yield progress + result events
                            yield tracked(tool_progress_event(
                                chat_id=chat_id,
                                tool_name=tool_name,
                                status="done",
                                summary=content[:100] if content else "",
                                message_id=msg_id,
                                stage="complete",
                                current=tool_round_results + 1,
                                total=len(calls),
                            ))
                            yield tracked(tool_result_event(
                                chat_id=chat_id,
                                tool_name=tool_name,
                                call_id=call_id,
                                result=content,
                                message_id=msg_id,
                            ))
                            executed.append((tc, call_id, content))
                            last_tool_payloads.append((tool_name, content))
                            tool_round_results += 1

                        # Feed tool results back into conversation history. The
                        # message format depends on how the orchestrator calls tools.
                        if tool_call_mode == "prompt_json":
                            # Prompt-JSON models have no OpenAI tool_calls message
                            # format: record the assistant's envelope as plain text
                            # and the tool result as a user message it can read, then
                            # re-invoke so it can continue or answer.
                            for tc, _call_id, content in executed:
                                fn = tc.get("function", {})
                                orchestrator_messages.append({
                                    "role": "assistant",
                                    "content": _prompt_json_envelope_text(
                                        fn.get("name", ""), fn.get("arguments", {}),
                                    ),
                                })
                                orchestrator_messages.append({
                                    "role": "user",
                                    "content": _prompt_json_tool_result(
                                        fn.get("name", ""), content,
                                    ),
                                })
                            orchestrator_messages.append({
                                "role": "user",
                                "content": (
                                    "If the TOOL_RESULT messages above are sufficient, answer the original user now "
                                    "in natural language. Do not repeat the same tool call. Only call another tool "
                                    "if the current results are clearly insufficient."
                                ),
                            })
                        else:
                            # Native OpenAI tool-call message format: the assistant
                            # message announcing the tool_calls MUST precede the
                            # tool-result messages that answer them.
                            orchestrator_messages.append({
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": tc.get("id", ""),
                                        "type": tc.get("type", "function"),
                                        "function": {
                                            "name": tc.get("function", {}).get("name", ""),
                                            "arguments": json.dumps(tc.get("function", {}).get("arguments", {})),
                                        },
                                    }
                                    for tc in calls
                                ],
                            })
                            for _tc, call_id, content in executed:
                                orchestrator_messages.append({
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "content": content,
                                })

                        # Anti-loop: a model that runs the SAME command, watches
                        # it fail the same way, and just runs it again (seen in
                        # the wild re-running a crashing script ~10x until the
                        # round cap) is stuck. Track repeated identical failing
                        # run_command calls and, once it repeats, tell it plainly
                        # to fix the file instead of re-running unchanged.
                        edited_this_round = any(
                            (tc.get("function", {}).get("name", "")) in
                            ("codebase_edit_file", "codebase_write_file")
                            for tc in calls
                        )
                        if edited_this_round:
                            last_failed_run_cmd = None
                            repeated_run_fail_count = 0
                        for tc, _call_id, content in executed:
                            if tc.get("function", {}).get("name", "") != "codebase_run_command":
                                continue
                            cmd = str(tc.get("function", {}).get("arguments", {}).get("command", ""))
                            if _run_command_failed(content):
                                if cmd and cmd == last_failed_run_cmd:
                                    repeated_run_fail_count += 1
                                else:
                                    last_failed_run_cmd = cmd
                                    repeated_run_fail_count = 1
                            elif cmd == last_failed_run_cmd:
                                last_failed_run_cmd = None
                                repeated_run_fail_count = 0
                        if repeated_run_fail_count >= 2:
                            orchestrator_messages.append({
                                "role": "user",
                                "content": (
                                    f"STOP re-running the same command — you have run "
                                    f"`{last_failed_run_cmd}` {repeated_run_fail_count} times and it "
                                    "fails the same way every time. Running it again will not help. "
                                    "Read the error output above, open the file with codebase_read_file "
                                    "if needed, then use codebase_edit_file to FIX the specific line "
                                    "that caused the error. Only after editing the file should you run "
                                    "the command again."
                                ),
                            })
                            repeated_run_fail_count = 0  # one nudge per stuck streak

                        # If tools were executed, break inner loop to re-call model
                        if tool_round_results > 0:
                            break
                    break
                elif event.get("type") == "tool_call_malformed":
                    # The model attempted a tool call whose JSON envelope
                    # never closed or failed to parse (typically a large
                    # codebase_edit_file new_string that got cut off or
                    # mis-escaped). streaming.py already suppressed the raw
                    # fragment from the visible answer; feed back an
                    # actionable retry hint instead of silently ending the
                    # turn with nothing (or looping the same failure blind).
                    had_malformed_tool_call = True
                    raw_preview = (event.get("raw") or "")[:500]
                    logger.warning(
                        "Malformed tool-call envelope from orchestrator (round %d): %r",
                        tool_round, raw_preview,
                    )
                    trace_event(
                        "orchestrator_tool_call_malformed",
                        **trace_context, round=tool_round, raw_preview=raw_preview,
                    )
                    if finalization_round:
                        logger.warning(
                            "Malformed tool call during forced finalization; using tool-result fallback."
                        )
                        # Only fall back to the generic tool-results summary if
                        # some earlier round actually succeeded. With zero real
                        # results, leave all_tokens empty and let the terminal
                        # had_malformed_tool_call branch below give the user an
                        # accurate explanation instead of a misleading "I
                        # gathered tool results" message.
                        if last_tool_payloads:
                            fallback = _fallback_answer_from_tool_results(user_message, last_tool_payloads)
                            if fallback:
                                all_tokens.append(fallback)
                                telemetry.mark_token()
                                yield tracked(token_event(chat_id, text=fallback, message_id=msg_id))
                        break
                    malformed_retry = True
                    orchestrator_messages.append({
                        "role": "user",
                        "content": _malformed_tool_call_guidance(raw_preview),
                    })
                    break

        except Exception as exc:
            # Never surface an empty error. asyncio.TimeoutError (the common
            # case when a large generation exceeds stream_timeout) stringifies
            # to "" — which reached the UI as a blank/invisible toast and left
            # the turn ending on a dangling narration fragment. Build a
            # human-readable message from the exception type when str() is empty
            # and name the timeout case explicitly.
            import asyncio as _asyncio
            exc_text = str(exc).strip()
            if isinstance(exc, _asyncio.TimeoutError):
                friendly = (
                    f"The model took longer than {int(stream_timeout)}s to respond and timed out. "
                    "This usually means the request was too large — try a smaller or simpler ask."
                )
            elif exc_text:
                friendly = f"Model generation failed: {exc_text}"
            else:
                friendly = f"Model generation failed ({type(exc).__name__})."
            logger.error("Orchestrator streaming failed (%s): %s", type(exc).__name__, exc_text or "<no message>")
            trace_event(
                "orchestrator_call_error", **trace_context, round=tool_round,
                error=exc_text, error_type=type(exc).__name__,
            )
            yield tracked(error_event(
                chat_id,
                error_code="orchestrator_error",
                message=friendly,
                recoverable=True,
            ))
            # If nothing substantive streamed this turn, surface the reason as
            # visible reply text too, so the persisted message isn't an empty
            # or half-finished fragment the user has to guess about.
            if not "".join(all_tokens).strip():
                if last_tool_payloads:
                    fb = _fallback_answer_from_tool_results(user_message, last_tool_payloads)
                    if fb:
                        all_tokens.append(fb)
                        telemetry.mark_token()
                        yield tracked(token_event(chat_id, text=fb, message_id=msg_id))
                if not "".join(all_tokens).strip():
                    all_tokens.append(friendly)
                    telemetry.mark_token()
                    yield tracked(token_event(chat_id, text=friendly, message_id=msg_id))
            break

        # If we detected tool calls (or a malformed attempt worth retrying),
        # continue the loop to feed results/guidance back to the model.
        if detected_tool_calls or malformed_retry:
            if tool_round >= max_tool_rounds:
                logger.warning("Max tool rounds (%d) reached — forcing final answer from tool results", max_tool_rounds)
                finalization_round = True
                orchestrator_messages.append({
                    "role": "user",
                    "content": (
                        "Tool limit reached. You must now answer the original user using the TOOL_RESULT "
                        "messages already provided. Do not output JSON. Do not call any more tools."
                    ),
                })
            # Keep tools available on continuation rounds so the orchestrator can
            # chain (say something -> tool -> reason -> tool) — bounded by
            # max_tool_rounds, the per-tier tool_result_budget compaction above, and
            # the cheap continuation-round reasoning_effort. Only drop tools on the
            # finalization round, where the model must turn collected evidence into
            # prose with no further tool calls. (The finalization pass at the loop
            # top also refuses tool calls and falls back to tool results, so this is
            # belt-and-suspenders, not the only guard.) prompt_json models keep
            # model_tools=None throughout — they chain via the in-message contract.
            if finalization_round:
                model_tools = None
            all_tokens = []  # Reset for final answer tokens
            continue

        # No tool calls this round. Before accepting it as the final answer,
        # guard the specific failure seen in the wild: the model writes a
        # preamble that PROMISES an action ("You're right — let me check that
        # directory:", "I'll read the file now:") and then stops, having called
        # no tool. That dangling fragment gets persisted as the whole reply.
        # Nudge exactly once — either call the tool or actually answer — while
        # rounds and tools remain. Bounded to one retry so a model that just
        # writes colon-ended prose can't loop.
        if (
            not finalization_round
            and not narration_nudge_used
            and tool_round <= max_tool_rounds
            and (allowed_tools or model_tools)
            and _looks_like_unfinished_narration("".join(all_tokens))
        ):
            narration_nudge_used = True
            logger.warning(
                "Orchestrator ended on an action-promising fragment with no tool call; nudging once."
            )
            trace_event(
                "orchestrator_narration_nudge", **trace_context, round=tool_round,
                fragment="".join(all_tokens)[:200],
            )
            orchestrator_messages.append({
                "role": "user",
                "content": (
                    "You said you would take an action (e.g. read, list, edit, or create a file) "
                    "but you did not actually call any tool — you stopped after the preamble. "
                    "Either call the tool now, or, if you already have what you need, give the "
                    "complete final answer in plain language. Do not narrate an intention "
                    "without following through."
                ),
            })
            all_tokens = []  # Reset; the nudge response becomes the real answer.
            # Boundary marker so the collector drops the discarded preamble from
            # the PERSISTED reply (there's no tool_call between the fragment and
            # the retried answer to signal it otherwise).
            yield tracked(phase_event(chat_id, msg_id, "model", "Writing response"))
            continue

        # Guard the opposite failure: the model ran a command, it FAILED, and now
        # it's ending the turn without fixing it (seen: ran a crashing script once
        # then gave up, or worse claimed success). If the most recent run_command
        # failed and nothing edited the file since, push once to fix-or-be-honest
        # while rounds/tools remain. One-shot, so a genuinely unfixable error
        # still terminates.
        if (
            not finalization_round
            and not run_fix_nudge_used
            and last_failed_run_cmd is not None
            and tool_round <= max_tool_rounds
            and (allowed_tools or model_tools)
        ):
            run_fix_nudge_used = True
            logger.warning("Turn ending after a failed run_command with no fix; nudging once.")
            trace_event("orchestrator_run_fix_nudge", **trace_context, round=tool_round,
                        failed_cmd=last_failed_run_cmd)
            orchestrator_messages.append({
                "role": "user",
                "content": (
                    f"The last command you ran (`{last_failed_run_cmd}`) FAILED — see the error "
                    "output above. Do NOT tell the user it works or that you are done. Read the "
                    "error, use codebase_read_file / codebase_edit_file to fix the specific line "
                    "that caused it, then run the command again to confirm. If after trying you "
                    "truly cannot fix it, explain honestly what is still broken and why — never "
                    "claim success for code that does not run."
                ),
            })
            all_tokens = []
            yield tracked(phase_event(chat_id, msg_id, "model", "Writing response"))
            continue

        # No tool calls — this is the final answer stream
        break

    logger.info("MODEL RESPONSE COMPLETE: total_tokens=%d", len(all_tokens))
    final_response = "".join(all_tokens)
    trace_event(
        "orchestrator_response_complete",
        **trace_context,
        total_token_chunks=len(all_tokens),
        response=final_response,
        tool_payloads=last_tool_payloads,
    )
    if not all_tokens and last_tool_payloads:
        logger.warning("No final model tokens after tool execution; emitting tool-result fallback.")
        fallback = _fallback_answer_from_tool_results(user_message, last_tool_payloads)
        if fallback:
            all_tokens.append(fallback)
            telemetry.mark_token()
            yield tracked(token_event(chat_id, text=fallback, message_id=msg_id))
    elif not all_tokens and had_malformed_tool_call:
        # Every attempt this turn was a tool call whose JSON never parsed, and
        # none produced a usable result to fall back on — say so plainly
        # instead of ending the turn with an empty reply.
        fallback = (
            "I wasn't able to complete that — the change was too large or complex "
            "for me to format correctly in one step. Could you ask for a smaller, "
            "more targeted edit (e.g. one section at a time) instead of a full "
            "rewrite?"
        )
        all_tokens.append(fallback)
        telemetry.mark_token()
        yield tracked(token_event(chat_id, text=fallback, message_id=msg_id))
    telemetry.model_done_at = time.perf_counter()
    yield tracked(phase_event(chat_id, msg_id, "finalizing", "Finalizing"))
    telemetry.done_at = time.perf_counter()
    logger.info("CHAT TURN TELEMETRY: %s", telemetry.summary())
    trace_event("turn_complete", **trace_context, telemetry=telemetry.summary(), response="".join(all_tokens))
    yield tracked(done_event(chat_id, message_id=msg_id))
    if os.getenv("OBRENNA_CHAT_TELEMETRY") == "1":
        yield tracked(telemetry_event(chat_id, msg_id, telemetry.summary()))
    # Persist structured per-turn telemetry to a local JSONL sink so performance
    # changes can be measured before/after. Never blocks or breaks the turn.
    try:
        write_turn_telemetry(chat_id, telemetry.summary())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Telemetry sink write failed: %s", exc)


def _prepare_worker_tasks(
    user_message: str,
    system_parts: list[dict],
    plan: ResolvedPlan,
) -> tuple[list[dict], str]:
    """Prepare worker task dicts and a shared system prompt."""
    worker_system = (
        "You are a utility worker in an AI assistant. "
        "Perform the task described and return structured output (JSON preferred)."
    )

    # Collect relevant file IDs from system context
    file_text = ""
    for part in system_parts:
        content = part.get("content", "")
        if "stored memories" in content.lower() or "past conversation" in content.lower():
            pass  # Skip memory/archive for workers
        # Workers get user_message directly

    tasks = []
    # Single worker: analyze the user message for context extraction
    tasks.append({
        "worker_id": "context_extract",
        "user_prompt": (
            f"Analyze this user message and extract any key entities, "
            f"file references, or domain context. Return as JSON.\n\n"
            f"User message: {user_message}"
        ),
    })

    return tasks, worker_system


def _build_orchestrator_messages(
    user_message: str,
    static_parts: list[dict],
    dynamic_parts: list[dict],
    evidence_summary: str,
    previous_messages: list[dict],
    *,
    tool_call_mode: str = "openai_native",
    allowed_tools: list[dict] | None = None,
    web_search_enabled: bool = False,
    codebase_project_name: str | None = None,
) -> list[dict]:
    """Build the full message sequence for the orchestrator.

    Band layout (Fix #1) — the leading bands are byte-stable across turns so
    Ollama's prefix/KV cache reuses them on turns 2+:

      A.  Static orchestrator identity/role prompt (constant) — ``static_parts``.
      A′. Prompt-JSON tool contract (constant within a tool set) — moved BEFORE
          the dynamic memory so the cacheable prefix includes it.
      A″. Web-search usage hint — present only when the user has the web toggle
          on. Applies to both tool-call modes (native models only get a bare tool
          description otherwise). Stable within a chat, so still prefix-cached.
      B.  Per-turn memory block, version-stamped — ``dynamic_parts``.
      C.  Runtime clock + relative-date hint (per-turn, dynamic).
      D.  Worker evidence summary (per-turn, dynamic).
      Then ``previous_messages`` and the final user message.

    For ``prompt_json`` models, the tool contract (Band A′) teaches the JSON
    envelope format for calling tools (no native tool-call template). Native
    models learn tools via the OpenAI ``tools`` field and get no contract.
    """
    from ..services.memory import canonicalise_system_content

    # Band A: static identity/role prompt (leads → prefix-cached across turns).
    messages = list(static_parts)

    # Band A′: prompt-JSON tool contract. Placed before the dynamic memory so
    # the cacheable prefix includes it. Canonicalised to a byte-stable string.
    if tool_call_mode == "prompt_json" and allowed_tools:
        messages.append({
            "role": "system",
            "content": canonicalise_system_content(_build_prompt_json_tool_contract(allowed_tools)),
        })

    # Band A″: web-search usage hint. Active nudge (not just an "it exists"
    # listing) so the orchestrator prefers `web_search` for fresh/external
    # facts. Stable within a chat, so it stays in the cacheable prefix. Applies
    # to both tool-call modes — native models otherwise only see the bare tool
    # description via the OpenAI tools field.
    if web_search_enabled:
        messages.append({
            "role": "system",
            "content": canonicalise_system_content(WEB_SEARCH_HINT),
        })

    # Band A‴: codebase-project usage hint, same rationale as the web-search
    # hint above — the model is told the tools exist via allowed_tools/the
    # contract, but tends to reason its way out of using them for indirect
    # phrasing ("can you see the attached project?") rather than just calling
    # a tool to check. Stable within a chat while the binding doesn't change,
    # so still prefix-cacheable.
    if codebase_project_name:
        messages.append({
            "role": "system",
            "content": canonicalise_system_content(
                CODEBASE_PROJECT_HINT_TEMPLATE.format(name=codebase_project_name)
            ),
        })

    # Band B: per-turn memory block (version-stamped, dynamic).
    messages.extend(dynamic_parts)

    # Band C: per-turn runtime clock context so small models stay grounded.
    runtime_clock_msg = build_runtime_context_message(
        compact=(tool_call_mode == "prompt_json"),
    )
    messages.append(runtime_clock_msg)

    relative_date_hint = build_relative_date_hint_message(user_message)
    if relative_date_hint:
        messages.append(relative_date_hint)

    # Band D: evidence summary (per-turn, dynamic).
    if evidence_summary:
        messages.append({
            "role": "system",
            "content": f"**Worker evidence pack summary:**\n{evidence_summary}",
        })

    # Append previous conversation messages (if stateful turn)
    messages.extend(previous_messages)

    # Final user message
    messages.append({"role": "user", "content": user_message})

    return messages


def _format_tool_arg_spec(input_schema: dict | None) -> str:
    """Render a tool's input schema as a compact argument hint for the contract."""
    if not isinstance(input_schema, dict):
        return "{}"
    props = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    if not props:
        return "{}"
    parts = []
    for name, spec in props.items():
        typ = spec.get("type", "any") if isinstance(spec, dict) else "any"
        tag = "required" if name in required else "optional"
        parts.append(f'"{name}": {typ} ({tag})')
    return "{" + ", ".join(parts) + "}"


def _build_prompt_json_tool_contract(allowed_tools: list[dict]) -> str:
    """System-message contract teaching a non-native model how to call tools.

    The tool schemas are read from the canonical ``TOOL_DEFS`` so the contract
    stays in sync with the allowlist + real input schemas.
    """
    lines = [
        "You have access to tools. To call a tool, output a single JSON object on its own line in EXACTLY this format and nothing else on that line:",
        '{"action":"tool_call","tool":"<tool_name>","arguments":{<arguments as a JSON object>}}',
        'Example: {"action":"tool_call","tool":"web_search","arguments":{"query":"latest AI news","max_results":5}}',
        'Example: {"action":"tool_call","tool":"get_time","arguments":{}}',
        "To call several independent tools at once in a single turn, use the plural form with a calls array:",
        '{"action":"tool_calls","calls":[{"tool":"<tool_name>","arguments":{<args>}}, ...]}',
        'Example: {"action":"tool_calls","calls":[{"tool":"get_time","arguments":{}},{"tool":"web_search","arguments":{"query":"weather today","max_results":3}}]}',
        "Prefer the plural form only when the calls are genuinely independent. If one call's arguments depend on another's result, emit one call, wait for its TOOL_RESULT, then emit the next.",
        "After you emit a tool call, the system runs it and replies with a TOOL_RESULT(...) message. Then continue: call another tool with the same envelope, or answer the user directly without the envelope.",
        "Do not use shortcuts like {\"action\":\"web_search\",...}; always use action=tool_call or action=tool_calls with tool and arguments.",
        "Do not mention or narrate that you are calling a tool — just emit the JSON object.",
        "",
        "Available tools:",
    ]
    for t in allowed_tools:
        name = t.get("name", "")
        canonical = tool_def_by_name(name) or {}
        desc = canonical.get("description") or t.get("description", "")
        schema = canonical.get("inputSchema") or t.get("inputSchema", {})
        lines.append(f"- {name}: {desc}")
        lines.append(f"    arguments: {_format_tool_arg_spec(schema)}")
    return "\n".join(lines)


def _prompt_json_envelope_text(tool: str, args: dict) -> str:
    """Reconstruct the assistant's tool-call envelope as plain text for history."""
    return json.dumps({"action": "tool_call", "tool": tool, "arguments": args})


def _prompt_json_tool_result(tool: str, content: str) -> str:
    """Format a tool result as a user message a prompt-JSON model can read."""
    return f"TOOL_RESULT({tool}): {content}"


def _round_reasoning_effort(
    thinking_enabled: bool,
    tool_round: int,
    finalization_round: bool,
    reasoning_distilled: bool,
) -> str:
    """Per-round Ollama ``reasoning_effort`` level for the orchestrator tool loop.

    Keys on ``reasoning_distilled`` (model identity from the resolver), NOT
    ``tool_call_mode`` (transport): distilled models form their tool-call
    envelopes as reasoned output and need in-stream CoT even on continuation, so
    they downshift ``medium``->``low`` rather than going dark. Stock models emit
    tool calls structurally, so continuation rounds (a mechanical sufficiency
    check) get no reasoning.

    Finalization is NOT a continuation round — it turns collected evidence into
    prose with no further tools, so reasoning is off for everyone: the reasoning
    trace is the highest hallucination-risk surface and must not re-deliberate at
    the point it should just write the answer. When thinking is disabled for the
    turn, every round is ``"none"`` (preserves the opt-in behavior).

    Returns one of ``"none" | "low" | "medium"``.
    """
    if not thinking_enabled:
        return "none"
    if finalization_round:
        return "none"
    if tool_round <= 1:
        return "medium"
    # Continuation round (round > 1, not finalization).
    return "low" if reasoning_distilled else "none"


# Tools whose results are small and deterministic — folding them through any
# compaction is pure overhead, so they pass through unchanged.
_PASSTHROUGH_TRIM_TOOLS = frozenset({"calculator", "get_time", "get_location"})


def _head_truncate(content: str, budget: int) -> str:
    if len(content) <= budget:
        return content
    return content[:budget] + "\n...[truncated]"


def _trim_web_search(content: str, per_result_budget: int) -> str:
    """Structurally trim a web_search result, preserving the sufficiency shape.

    web_search returns ``{"results":[{"title","snippet","url"},...]}``. The shape
    — all N titles + urls — is what tells the orchestrator whether it has enough,
    so we keep every entry and budget each snippet body rather than
    head-truncating the concatenated blob (which drops snippet #4, often the
    relevant one). Falls back to head-truncation if the payload isn't JSON.
    """
    try:
        obj = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return _head_truncate(content, per_result_budget)
    results = obj.get("results") if isinstance(obj, dict) else None
    if not isinstance(results, list) or not results:
        return _head_truncate(content, per_result_budget)
    per_snippet = max(120, per_result_budget // len(results))
    trimmed = []
    for r in results:
        if not isinstance(r, dict):
            trimmed.append(r)
            continue
        nr = dict(r)
        snip = nr.get("snippet")
        if isinstance(snip, str) and len(snip) > per_snippet:
            nr["snippet"] = snip[:per_snippet].rstrip() + "…"
        trimmed.append(nr)
    return json.dumps({"results": trimmed}, ensure_ascii=False)


def _trim_file_read(content: str, per_result_budget: int) -> str:
    """Head+tail trim for file_read so file structure (imports/exports) stays visible."""
    if len(content) <= per_result_budget:
        return content
    head = int(per_result_budget * 0.6)
    tail = per_result_budget - head
    return content[:head] + "\n...[middle truncated]...\n" + content[-tail:]


def _trim_tool_result(tool_name: str, content: str, per_result_budget: int) -> str:
    """Per-tool structural trim. NOT a blanket head-truncation — the shape carries
    the sufficiency information the orchestrator needs to decide whether it has
    enough. Small deterministic tools pass through (tens of tokens — folding them
    is pure overhead).
    """
    if not content or tool_name in _PASSTHROUGH_TRIM_TOOLS:
        return content
    if tool_name == "web_search":
        return _trim_web_search(content, per_result_budget)
    if tool_name == "file_read":
        return _trim_file_read(content, per_result_budget)
    return _head_truncate(content, per_result_budget)


def _compact_tool_results(
    tool_results: list[dict],
    calls: list[dict],
    per_result_budget: int,
) -> tuple[int, int]:
    """Compact each tool result's ``content`` in place before feed-back.

    Single chokepoint: both the prompt_json and openai_native feed-back branches
    (plus ``last_tool_payloads`` and the finalization fallback) read ``content``
    from these result dicts, so mutating them here bounds context growth for
    every path. v1 applies structural trim only — the summarizer fold is gated
    off (see plan Step 2: wire it only if real results starve the model after
    trimming). Never raises: on any parse failure the original content is kept.

    Returns ``(raw_chars, compacted_chars)`` for trace visibility.
    """
    raw_chars = 0
    compacted_chars = 0
    for result, tc in zip(tool_results, calls):
        if not isinstance(result, dict):
            continue
        tool_name = result.get("tool_name") or (
            tc.get("function", {}).get("name", "") if isinstance(tc.get("function"), dict) else ""
        )
        content = result.get("content", "")
        if not isinstance(content, str):
            continue
        raw_chars += len(content)
        compacted = _trim_tool_result(tool_name, content, per_result_budget)
        compacted_chars += len(compacted)
        result["content"] = compacted
    return raw_chars, compacted_chars


# Cues that a reply is a promise-to-act preamble rather than a real answer:
# it ends mid-thought on a colon, or is a short line built around a first-person
# intention verb ("let me read...", "I'll check..."). Kept deliberately narrow
# so a genuine short answer ("Yes, that file exists.") is never misclassified.
_NARRATION_INTENT_RE = re.compile(
    r"\b("
    r"let me|i'?ll|i will|i'?m going to|i am going to|let'?s|"
    r"first,? (?:i|let)|now (?:i|let)|checking|reading|listing|"
    r"looking (?:at|into)|let me check|let me look|let me read|let me see"
    r")\b",
    re.IGNORECASE,
)


_MALFORMED_TOOL_RE = re.compile(r'"tool"\s*:\s*"([a-zA-Z0-9_]+)"')
_MALFORMED_PATH_RE = re.compile(r'"path"\s*:\s*"([^"]{1,200})"')


def _malformed_tool_call_guidance(raw_preview: str) -> str:
    """Craft a recovery message tuned to WHICH tool's envelope broke.

    A cut-off ``codebase_write_file`` (the common failure when the model tries to
    dump a whole file in one call and the JSON never closes) needs different
    advice than a broken ``edit_file`` — 'write a tiny file first, then grow it
    with edits' vs 'make the old_string/new_string smaller'. Generic advice made
    the model retry the same oversized write and fail again.
    """
    tool_match = _MALFORMED_TOOL_RE.search(raw_preview or "")
    path_match = _MALFORMED_PATH_RE.search(raw_preview or "")
    tool = tool_match.group(1) if tool_match else ""
    path = path_match.group(1) if path_match else "that file"

    if tool == "codebase_write_file":
        return (
            f"Your codebase_write_file for '{path}' was too long to send in one message "
            "and got cut off, so nothing was written. Do NOT resend the whole file. "
            f"Instead: FIRST create '{path}' with codebase_write_file containing only a "
            "SHORT minimal skeleton (a few lines that already run — e.g. the imports and "
            "one function stub or a `pass`). THEN add the rest incrementally with several "
            "small codebase_edit_file calls, one function or section at a time. Keep every "
            "single tool call's content short."
        )
    if tool == "codebase_edit_file":
        return (
            f"Your codebase_edit_file for '{path}' could not be parsed — the JSON was "
            "incomplete or invalid, most likely because new_string was too long or had an "
            "unescaped quote or newline. Retry with a SMALLER edit: keep old_string and "
            "new_string just long enough to be unique, and if you need to change most of "
            "the file, make several separate small codebase_edit_file calls instead of one "
            "big one."
        )
    return (
        "Your last tool call could not be parsed — the JSON was incomplete or invalid, "
        "most likely because an argument was too long or contained an unescaped quote or "
        "newline. Retry with a smaller, more targeted call, and split large content into "
        "several small calls instead of one big one."
    )


def _run_command_failed(result_content: str) -> bool:
    """True if a codebase_run_command result represents a failure — a non-zero
    exit_code, a timeout, or a dispatch error. Used to detect a model stuck
    re-running the same broken command instead of fixing the code."""
    if not result_content:
        return False
    try:
        data = json.loads(result_content)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    if data.get("error") or data.get("timed_out"):
        return True
    exit_code = data.get("exit_code")
    return exit_code is not None and exit_code != 0


def _looks_like_unfinished_narration(text: str) -> bool:
    """True when ``text`` reads as an action-promise preamble, not an answer.

    Targets the observed failure where the model writes "…let me check that
    directory:" and stops without calling any tool. Two independent signals,
    both scoped to short outputs (a long substantive answer is never a
    dangling preamble even if it happens to contain "let me"):

      1. Ends on a colon (the classic "here's what I'll do:" cut-off), OR
      2. Is short AND contains a first-person intention verb.
    """
    stripped = (text or "").strip()
    if not stripped:
        # Genuinely empty output is handled by the tool-result / empty-reply
        # fallbacks, not here — don't claim it as narration.
        return False
    # Long answers are real answers, not preambles.
    if len(stripped) > 320:
        return False
    ends_on_colon = stripped.endswith(":") or stripped.endswith(":**") or stripped.endswith(":”")
    has_intent = bool(_NARRATION_INTENT_RE.search(stripped))
    # A trailing colon alone is enough (it's the strongest signal); otherwise
    # require an intention verb in a short line.
    if ends_on_colon:
        return True
    return has_intent and len(stripped) <= 200


def _fallback_answer_from_tool_results(
    user_message: str,
    tool_payloads: list[tuple[str, str]],
) -> str:
    """Build a non-empty answer if the model exhausts tool rounds.

    This is a last-resort safety net for prompt-JSON models that repeatedly ask
    for the same tool instead of converting the final TOOL_RESULT into prose.
    The normal path is still a final model pass; this only prevents a completed
    empty assistant message.
    """
    search_items: list[dict[str, Any]] = []
    other_notes: list[str] = []

    for tool_name, raw in tool_payloads[-5:]:
        parsed: Any = None
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None

        candidates: list[Any] = []
        if isinstance(parsed, dict):
            if isinstance(parsed.get("results"), list):
                candidates = parsed["results"]
            elif isinstance(parsed.get("items"), list):
                candidates = parsed["items"]
        elif isinstance(parsed, list):
            candidates = parsed

        for item in candidates:
            if isinstance(item, dict) and (item.get("title") or item.get("snippet")):
                search_items.append(item)

        if not candidates and raw:
            other_notes.append(f"{tool_name}: {raw[:300]}")

    if search_items:
        lines = [
            f"Here are the most relevant results I found for: {user_message}",
            "",
        ]
        for item in search_items[:5]:
            title = str(item.get("title") or "Result").strip()
            snippet = str(item.get("snippet") or "").strip()
            url = str(item.get("url") or "").strip()
            line = f"- {title}"
            if snippet:
                line += f": {snippet}"
            if url:
                line += f" ({url})"
            lines.append(line)
        return "\n".join(lines)

    if other_notes:
        return "I gathered tool results, but the model did not produce a final response. Relevant tool output:\n\n" + "\n".join(
            f"- {note}" for note in other_notes[:5]
        )

    return "I gathered tool results, but could not produce a final response."


# ── MCP tool call handling ────────────────────────────────────────────────────


def _is_gather_eligible(tool_name: str) -> bool:
    """Whether a tool call may run concurrently with others in the same batch.

    A call is gather-eligible only when the tool is read-only, takes no user
    prompt, and declares no dependency on another tool's output. The flags come
    from ``mcp/tools.py::TOOL_DEFS`` (mirrored in ``architecture_config.json``);
    fail closed (serial) when the tool is unknown or any flag is missing.

    ``get_location`` is ALWAYS serial: it is sensitive/broker-routed (the
    broker is not actually wired today — keep the hard name exclusion).
    """
    if tool_name == "get_location":
        return False
    tdef = tool_def_by_name(tool_name)
    if not tdef:
        return False
    if not tdef.get("is_read_only", False):
        return False
    if tdef.get("requires_user_prompt", False):
        return False
    depends_on = tdef.get("depends_on") or []
    if depends_on:
        return False
    return True


# ── Tool-argument validation + repair ────────────────────────────────────────
#
# The orchestrator (often a sub-1B distilled model on the low tiers) authors
# tool calls itself when the deterministic router doesn't force one. It fairly
# routinely omits required arguments — e.g. a ``web_search`` call with no
# ``query``. That call would otherwise reach the MCP server (Rust proxy *or* the
# in-memory Python handler) and fail with an opaque hard error mid-turn.
#
# This layer runs in ``handle_tool_calls`` — the transport-agnostic dispatch
# point — so it covers every backend uniformly. For each call we validate the
# arguments against the canonical ``inputSchema`` (single source of truth in
# ``mcp/tools.py::TOOL_DEFS``, reached via ``tool_def_by_name``). When a required
# argument is missing or blank we attempt a per-tool *repair strategy*; if that
# fails we short-circuit with a structured, retryable tool result fed back into
# the loop rather than dispatching a call we know will fail.


def _is_arg_blank(value: Any) -> bool:
    """A required argument is unsatisfied if absent, ``None``, or blank text."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _missing_required_args(name: str, args: dict) -> list[str]:
    """Return the required arg names for ``name`` that are missing/blank in ``args``."""
    tdef = tool_def_by_name(name)
    if not tdef:
        return []  # unknown tool — let the MCP backend decide
    schema = tdef.get("inputSchema") or {}
    required = schema.get("required") or []
    return [r for r in required if _is_arg_blank(args.get(r))]


def _repair_web_search_args(args: dict, context: dict[str, Any]) -> dict | None:
    """Backfill a missing ``web_search.query`` from the turn's user message.

    A repair *strategy*, not a special case in the dispatch path: registered in
    ``_TOOL_ARG_REPAIRS`` and invoked generically by :func:`_repair_tool_args`.
    """
    user_message = (context.get("user_message") or "").strip()
    if not user_message:
        return None
    repaired = dict(args)
    repaired["query"] = user_message
    return repaired


# Per-tool repair strategies: ``(args, context) -> repaired_args | None``.
# ``context`` carries at least ``user_message``. Return ``None`` to signal the
# call is unrepairable, in which case dispatch is short-circuited with an error.
_TOOL_ARG_REPAIRS: dict[str, Any] = {
    "web_search": _repair_web_search_args,
}


def _repair_tool_args(
    name: str, args: dict, context: dict[str, Any]
) -> tuple[dict, str | None]:
    """Validate ``args`` against the tool schema; repair missing required args.

    Returns ``(args, error)``:
      * ``error is None`` — ``args`` (possibly repaired) satisfy the schema and
        the call may be dispatched.
      * ``error`` is a message — the call must NOT be dispatched; feed the error
        back into the loop as a retryable tool result.
    """
    missing = _missing_required_args(name, args)
    if not missing:
        return args, None

    repair = _TOOL_ARG_REPAIRS.get(name)
    if repair is not None:
        repaired = repair(args, context)
        if repaired is not None and not _missing_required_args(name, repaired):
            return repaired, None

    return args, (
        f"Missing required argument(s) for {name}: {', '.join(missing)}. "
        f"Call {name} again with all required arguments."
    )


async def handle_tool_calls(
    tool_calls: list[dict],
    mcp_client: Any,
    *,
    trace_context: dict[str, Any] | None = None,
    user_message: str | None = None,
    chat_id: str | None = None,
) -> list[dict]:
    """Execute tool calls returned by the orchestrator.

    Args:
        tool_calls: List of tool_call dicts from the model response, each
            shaped like ``{"id": ..., "type": "function", "function":
            {"name": ..., "arguments": ...}}`` (OpenAI tool-call shape, also
            used by the prompt-JSON scanner's synthesized calls).
        mcp_client: MCP client instance (transport-agnostic).

    Returns:
        List of tool result dicts with keys: tool_call_id, tool_name, content.
        ``content`` is always a string — the MCP client result (which may be
        a dict/list) is JSON-stringified so callers can treat it uniformly.
        Results are returned in the SAME ORDER as ``tool_calls``.

    Dispatch policy: gather-eligible (read-only, no-dependency) calls run
    concurrently via ``asyncio.gather``; the rest run serially in order.
    Independently-eligible tools therefore overlap in wall-clock, while
    stateful / sensitive / dependent tools stay sequential.
    """
    # Pre-resolve args + gather-eligibility per call, preserving original order.
    repair_context = {"user_message": user_message or ""}
    plan: list[dict] = []
    for idx, tc in enumerate(tool_calls):
        fn = tc.get("function", {})
        tool_name = fn.get("name", "")
        tool_args = fn.get("arguments", {})
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                tool_args = {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        call_id = tc.get("id", tc.get("call_id", ""))
        # Validate against the canonical schema before dispatch. A missing
        # required arg is repaired if a strategy exists (e.g. web_search.query
        # backfilled from the user message); otherwise the call is marked so
        # ``_exec`` returns a retryable error instead of hitting the MCP.
        tool_args, arg_error = _repair_tool_args(tool_name, tool_args, repair_context)
        plan.append({
            "idx": idx,
            "name": tool_name,
            "args": tool_args,
            "call_id": call_id,
            "arg_error": arg_error,
            "parallel": _is_gather_eligible(tool_name),
        })

    trace_event("tool_plan_built", **(trace_context or {}), plan=plan)

    results: list[dict | None] = [None] * len(tool_calls)

    async def _exec(item: dict) -> dict:
        tool_name = item["name"]
        # Schema validation failed and no repair applied — feed a structured,
        # retryable error back into the loop rather than dispatching a call the
        # MCP backend will reject with an opaque hard error.
        if item.get("arg_error"):
            trace_event(
                "tool_call_arg_invalid",
                **(trace_context or {}),
                tool_name=tool_name,
                call_id=item["call_id"],
                arguments=item["args"],
                error=item["arg_error"],
            )
            return {
                "tool_call_id": item["call_id"],
                "tool_name": tool_name,
                "content": json.dumps({"error": True, "message": item["arg_error"], "retryable": True}),
            }
        try:
            trace_event(
                "tool_call_start",
                **(trace_context or {}),
                tool_name=tool_name,
                call_id=item["call_id"],
                arguments=item["args"],
                parallel=item["parallel"],
            )
            if tool_name.startswith("codebase_") and chat_id is not None:
                codebase_project = get_active_codebase_project(chat_id)
                if codebase_project is not None:
                    result = await call_codebase_tool(chat_id, codebase_project, tool_name, item["args"])
                else:
                    result = {"error": True, "message": "No active codebase project is bound to this chat."}
            else:
                custom_tool = get_custom_tool_by_name(tool_name)
                if custom_tool is not None:
                    result = await call_custom_tool(custom_tool, item["args"])
                else:
                    result = await mcp_client.call_tool(tool_name, item["args"])
            content = result if isinstance(result, str) else json.dumps(result)
            trace_event(
                "tool_call_result",
                **(trace_context or {}),
                tool_name=tool_name,
                call_id=item["call_id"],
                arguments=item["args"],
                result=content,
            )
            return {
                "tool_call_id": item["call_id"],
                "tool_name": tool_name,
                "content": content,
            }
        except Exception as exc:
            logger.warning("MCP tool call '%s' failed: %s", tool_name, exc)
            trace_event(
                "tool_call_error",
                **(trace_context or {}),
                tool_name=tool_name,
                call_id=item["call_id"],
                arguments=item["args"],
                error=str(exc),
            )
            return {
                "tool_call_id": item["call_id"],
                "tool_name": tool_name,
                "content": f"Tool error: {exc}",
            }

    # Parallel batch: gather-eligible calls run concurrently. Exceptions are
    # caught inside ``_exec`` (never re-raised), so each gathered result is a
    # well-formed result dict; the ``return_exceptions=True`` guard below only
    # covers the unexpected case where ``_exec`` itself raised before its
    # try/except (e.g. an async-cancelled coroutine).
    parallel_items = [p for p in plan if p["parallel"]]
    if parallel_items:
        gathered = await asyncio.gather(
            *[_exec(p) for p in parallel_items], return_exceptions=True,
        )
        for p, g in zip(parallel_items, gathered):
            if isinstance(g, Exception):
                g = {
                    "tool_call_id": p["call_id"],
                    "tool_name": p["name"],
                    "content": f"Tool error: {g}",
                }
            results[p["idx"]] = g

    # Serial batch: remaining calls run in original order.
    for p in plan:
        if p["parallel"]:
            continue
        results[p["idx"]] = await _exec(p)

    return results


# ── Tool formatting helpers ──────────────────────────────────────────────────

# Schema mapping: inputSchema (JSON Schema) → OpenAI parameters (JSON Schema)
# The formats are nearly identical — just rename "inputSchema" → "parameters"
# and "required" stays the same.


def _input_schema_to_openai_params(input_schema: dict) -> dict:
    """Convert inputSchema from TOOL_DEFS to OpenAI parameters format."""
    if not input_schema:
        return {"type": "object", "properties": {}}
    return {
        "type": input_schema.get("type", "object"),
        "properties": input_schema.get("properties", {}),
        "required": input_schema.get("required", []),
    }


def _format_tools_for_model(allowed_tools: list[dict]) -> list[dict]:
    """Convert architecture_config tool defs to OpenAI tools format.

    ``architecture_config.json`` is an allowlist only — its entries carry
    name/description/category but no ``inputSchema``. The canonical tool schemas
    live in ``mcp/tools.py::TOOL_DEFS``; we merge them in by name so the model is
    told each tool's real parameters (e.g. that ``web_search`` requires ``query``).

    A tool allowed in config but absent from ``TOOL_DEFS`` is a config error: we
    raise loudly rather than silently shipping an empty-parameter definition that
    the model cannot use.
    """
    formatted = []
    for t in allowed_tools:
        name = t.get("name", "")
        if not name:
            raise ValueError("architecture_config allowed tool entry has no 'name'")
        canonical = tool_def_by_name(name)
        if canonical is None and not t.get("inputSchema"):
            raise ValueError(
                f"Allowed tool '{name}' is not defined in mcp/tools.py::TOOL_DEFS and "
                f"carries no inline schema. Either add the tool to TOOL_DEFS, register "
                f"it as a custom tool, or remove it from the allowlist."
            )
        canonical = canonical or {}
        # Prefer the canonical TOOL_DEFS schema; fall back to the entry's own
        # inline schema — this is how custom (DB-backed) tools are described,
        # since they have no TOOL_DEFS entry at all.
        input_schema = canonical.get("inputSchema") or t.get("inputSchema", {})
        formatted.append({
            "type": "function",
            "function": {
                "name": name,
                "description": canonical.get("description") or t.get("description", ""),
                "parameters": _input_schema_to_openai_params(input_schema),
            }
        })
    return formatted


# ── Tool filtering helpers ───────────────────────────────────────────────────


def _get_allowed_tools_for_request(
    allowed: list[dict],
    web_search_enabled: bool = False,
) -> list[dict]:
    """Filter allowed tools based on request settings.

    Web search tool is only included when web_search_enabled=True.
    All other allowed tools are always included.
    """
    tools = []
    for t in allowed:
        name = t.get("name", "")
        if name == "web_search" and not web_search_enabled:
            continue
        tools.append(t)
    return tools


def allowed_mcp_tools_config() -> list[dict]:
    """Return the list of allowed tool definitions from config."""
    config = get_mcp_tools_config()
    return config.get("allowed", [])


# ── Config loader helpers ────────────────────────────────────────────────────


def load_architecture_config() -> dict[str, Any]:
    """Load the architecture config (cached at module level)."""
    return get_config()


def get_allowed_mcp_tool_names() -> list[str]:
    """Return the list of allowed MCP tool names from config."""
    config = get_mcp_tools_config()
    return [t["name"] for t in config.get("allowed", [])]


def is_worker_tool_restricted(tool_name: str) -> bool:
    """Check if a tool is restricted (e.g. spawn_worker)."""
    config = get_mcp_tools_config()
    restricted = config.get("restricted_worker_tools", [])
    return tool_name in restricted
