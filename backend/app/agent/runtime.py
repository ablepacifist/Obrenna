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
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from sqlalchemy.orm import Session

from ..mcp.client import InMemoryTransport
from ..mcp.tools import list_tools, call_tool, tool_def_by_name
from ..model_runtime.config import RuntimeConfig
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
    max_tool_rounds = orchestration_cfg.get("max_tool_rounds", 5)
    # DEBUG, not INFO: user_message is private local content and must not
    # land in default-level logs on a local-first/private-by-default product.
    logger.debug("=== ORCHESTRATE TURN === chat_id=%s user_message=%r orchestrator_model=%s summarizer_model=%s utility_model=%s workers_enabled=%s", chat_id, user_message, resolved_plan.orchestrator_model, resolved_plan.summarizer_model, resolved_plan.utility_model, workers_enabled)

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
        )
        telemetry.memory_context_runtime_ms = int((time.perf_counter() - _mem_start) * 1000)
        # Fix #1: split the orchestrator's system content into a static,
        # cross-turn cacheable band (Band A) and a dynamic per-turn memory
        # band (Band B). The static band leads so Ollama's prefix cache
        # reuses it across turns; the dynamic, version-stamped band follows.
        static_parts = memory_ctx.to_static_messages()
        dynamic_parts = memory_ctx.to_dynamic_messages()
    except Exception as exc:
        logger.warning("Memory context assembly failed: %s", exc)
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
        if worker_tasks:
            worker_results = await dispatch_workers(
                worker_tasks, config, resolved_plan.utility_model, system_prompt,
                helper_count=resolved_plan.helper_count,
                timeout_seconds=worker_timeout,
                workers_enabled=workers_enabled,
                keep_alive=resolved_plan.utility_keep_alive,
            )
            evidence_pack = EvidencePack(
                entries=[r.to_evidence_entry() for r in worker_results],
                failure_count=sum(1 for r in worker_results if r.status != WorkerStatus.SUCCESS),
            )
            if use_summarizer and resolved_plan.summarizer_model:
                summary_text, success = await summarize_into_evidence_pack(
                    config, resolved_plan.summarizer_model, evidence_pack,
                    keep_alive=resolved_plan.summarizer_keep_alive,
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
    telemetry.workers_done_at = time.perf_counter()

    # Step 3: Resolve allowed tools + tool-call mode, then build orchestrator
    # messages. The prompt-JSON tool contract (if needed) is injected here so the
    # model knows the envelope format before it sees the user request.
    allowed_tools = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search)
    tool_call_mode = resolved_plan.orchestrator_tool_call_mode

    yield tracked(phase_event(chat_id, msg_id, "runtime_context", "Checking local date and time"))

    orchestrator_messages = _build_orchestrator_messages(
        user_message, static_parts, dynamic_parts, evidence_summary, previous_messages or [],
        tool_call_mode=tool_call_mode, allowed_tools=allowed_tools,
    )
    # DEBUG, not INFO: message content is private local content.
    logger.debug("ORCHESTRATOR MESSAGES: %d messages, first_user=%r last_user=%r", len(orchestrator_messages), orchestrator_messages[0]["content"] if orchestrator_messages and len(orchestrator_messages) > 0 else "", orchestrator_messages[-1]["content"] if orchestrator_messages else "")

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
    stream_timeout = orchestration_cfg.get("worker_timeout_seconds", 12) * 10
    tool_round = 0
    finalization_round = False
    last_tool_payloads: list[tuple[str, str]] = []
    all_tokens = []

    yield tracked(phase_event(chat_id, msg_id, "model", "Writing response"))

    while tool_round < max_tool_rounds + 1:
        tool_round += 1
        telemetry.tool_round_count = tool_round
        detected_tool_calls = []

        try:
            logger.info("CALLING MODEL: model=%s temperature=%.1f round=%d tools=%s",
                        resolved_plan.orchestrator_model, 0.2, tool_round,
                        "yes" if model_tools else "no")
            async for event in chat_completion_stream(
                config,
                orchestrator_messages,
                model=resolved_plan.orchestrator_model,
                role="orchestrator",
                temperature=0.2,
                timeout=stream_timeout,
                tools=model_tools,
                think=thinking_enabled,
                tool_call_mode=tool_call_mode,
                keep_alive=resolved_plan.orchestrator_keep_alive,
            ):
                if event.get("type") == "thinking_delta":
                    text = event.get("content", "") or event.get("text", "")
                    if text:
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
                        tool_results = await handle_tool_calls(calls, mcp_client)
                        telemetry.record_tool_runtime(time.perf_counter() - _tool_start)
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

                        # If tools were executed, break inner loop to re-call model
                        if tool_round_results > 0:
                            break
                    break

        except Exception as exc:
            logger.error("Orchestrator streaming failed: %s", exc)
            yield tracked(error_event(
                chat_id,
                error_code="orchestrator_error",
                message=f"Orchestrator generation failed: {exc}",
                recoverable=True,
            ))
            break

        # If we detected tool calls, continue loop to feed results back to model
        if detected_tool_calls:
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
            # model_tools is set to None on next iteration (no tools on follow-up calls)
            model_tools = None
            all_tokens = []  # Reset for final answer tokens
            continue

        # No tool calls — this is the final answer stream
        break

    logger.info("MODEL RESPONSE COMPLETE: total_tokens=%d", len(all_tokens))
    if not all_tokens and last_tool_payloads:
        logger.warning("No final model tokens after tool execution; emitting tool-result fallback.")
        fallback = _fallback_answer_from_tool_results(user_message, last_tool_payloads)
        if fallback:
            all_tokens.append(fallback)
            telemetry.mark_token()
            yield tracked(token_event(chat_id, text=fallback, message_id=msg_id))
    telemetry.model_done_at = time.perf_counter()
    yield tracked(phase_event(chat_id, msg_id, "finalizing", "Finalizing"))
    telemetry.done_at = time.perf_counter()
    logger.info("CHAT TURN TELEMETRY: %s", telemetry.summary())
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
) -> list[dict]:
    """Build the full message sequence for the orchestrator.

    Band layout (Fix #1) — the leading bands are byte-stable across turns so
    Ollama's prefix/KV cache reuses them on turns 2+:

      A.  Static orchestrator identity/role prompt (constant) — ``static_parts``.
      A′. Prompt-JSON tool contract (constant within a tool set) — moved BEFORE
          the dynamic memory so the cacheable prefix includes it.
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
        "After you emit a tool call, the system runs it and replies with a TOOL_RESULT(...) message. Then continue: call another tool with the same envelope, or answer the user directly without the envelope.",
        "Do not use shortcuts like {\"action\":\"web_search\",...}; always use action=tool_call with tool and arguments.",
        "Do not mention or narrate that you are calling a tool — just emit the JSON object.",
        "",
        "Available tools:",
    ]
    for t in allowed_tools:
        name = t.get("name", "")
        canonical = tool_def_by_name(name) or {}
        desc = canonical.get("description") or t.get("description", "")
        schema = canonical.get("inputSchema", {})
        lines.append(f"- {name}: {desc}")
        lines.append(f"    arguments: {_format_tool_arg_spec(schema)}")
    return "\n".join(lines)


def _prompt_json_envelope_text(tool: str, args: dict) -> str:
    """Reconstruct the assistant's tool-call envelope as plain text for history."""
    return json.dumps({"action": "tool_call", "tool": tool, "arguments": args})


def _prompt_json_tool_result(tool: str, content: str) -> str:
    """Format a tool result as a user message a prompt-JSON model can read."""
    return f"TOOL_RESULT({tool}): {content}"


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


async def handle_tool_calls(
    tool_calls: list[dict],
    mcp_client: Any,
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
        call_id = tc.get("id", tc.get("call_id", ""))
        plan.append({
            "idx": idx,
            "name": tool_name,
            "args": tool_args,
            "call_id": call_id,
            "parallel": _is_gather_eligible(tool_name),
        })

    results: list[dict | None] = [None] * len(tool_calls)

    async def _exec(item: dict) -> dict:
        tool_name = item["name"]
        try:
            result = await mcp_client.call_tool(tool_name, item["args"])
            content = result if isinstance(result, str) else json.dumps(result)
            return {
                "tool_call_id": item["call_id"],
                "tool_name": tool_name,
                "content": content,
            }
        except Exception as exc:
            logger.warning("MCP tool call '%s' failed: %s", tool_name, exc)
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
        if canonical is None:
            raise ValueError(
                f"Allowed tool '{name}' is not defined in mcp/tools.py::TOOL_DEFS. "
                f"Either add the tool to TOOL_DEFS or remove it from the allowlist."
            )
        # Prefer the canonical TOOL_DEFS schema; fall back to any inline schema
        # on the allowlist entry (defensive — allowlist should not carry one).
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
