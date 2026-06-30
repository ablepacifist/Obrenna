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

import logging
import uuid
from typing import Any, AsyncIterator

from sqlalchemy.orm import Session

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
from .events import (
    done_event,
    error_event,
    new_message_id,
    token_event,
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
    def summarizer_model(self) -> str:
        return self.summarizer.get("model", "")

    @property
    def utility_model(self) -> str:
        return self.utility.get("model", "")


def build_resolved_plan(resolver_result: dict[str, Any]) -> ResolvedPlan:
    """Create a ResolvedPlan from the hardware resolver output."""
    return ResolvedPlan(resolver_result)


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
) -> AsyncIterator[StreamEvent]:
    """Orchestrate a single chat turn through the agent runtime.

    Yields typed StreamEvents (token, done, error) as the turn progresses.
    The caller should render these events to the UI and persist the final message.

    Args:
        user_message: The user's input text.
        chat_id: The chat session ID.
        db: SQLAlchemy session.
        config: Runtime config for the model endpoint.
        resolved_plan: Hardware-resolved plan with model assignments.
        file_ids: Optional file IDs attached to the message.
        previous_messages: Optional prior conversation messages (for stateful turns).
        assistant_message_id: Optional pre-assigned message ID.

    Yields:
        StreamEvent instances for token/done/error events.
    """
    msg_id = assistant_message_id or new_message_id()
    use_workers = resolved_plan.helper_count > 0 and bool(resolved_plan.utility_model)
    use_summarizer = bool(resolved_plan.summarizer_model)
    orchestration_cfg = get_orchestration_config()
    worker_timeout = orchestration_cfg.get("worker_timeout_seconds", 12)
    logger.info("=== ORCHESTRATE TURN === chat_id=%s user_message=%r orchestrator_model=%s summarizer_model=%s utility_model=%s", chat_id, user_message, resolved_plan.orchestrator_model, resolved_plan.summarizer_model, resolved_plan.utility_model)

    # Step 1: Assemble memory context
    try:
        memory_ctx = assemble_context(db, type("Chat", (), {"id": chat_id})(), user_message)
        system_parts = memory_ctx.to_messages()
    except Exception as exc:
        logger.warning("Memory context assembly failed: %s", exc)
        system_parts = []

    # Step 2: Optional worker dispatch
    evidence_summary = ""
    if use_workers and previous_messages:
        worker_tasks, system_prompt = _prepare_worker_tasks(
            user_message, system_parts, resolved_plan
        )
        if worker_tasks:
            worker_results = await dispatch_workers(
                worker_tasks, config, resolved_plan.utility_model, system_prompt,
                helper_count=resolved_plan.helper_count,
                timeout_seconds=worker_timeout,
            )
            evidence_pack = EvidencePack(
                entries=[r.to_evidence_entry() for r in worker_results],
                failure_count=sum(1 for r in worker_results if r.status != WorkerStatus.SUCCESS),
            )
            if use_summarizer and resolved_plan.summarizer_model:
                summary_text, success = await summarize_into_evidence_pack(
                    config, resolved_plan.summarizer_model, evidence_pack,
                )
                if not success:
                    yield error_event(
                        chat_id,
                        error_code="summarizer_failure",
                        message="Summarizer failed — aborting turn.",
                        recoverable=False,
                    )
                    return
                evidence_summary = summary_text
            else:
                evidence_summary = evidence_pack.to_compact_string()

    # Step 3: Build orchestrator messages
    orchestrator_messages = _build_orchestrator_messages(
        user_message, system_parts, evidence_summary, previous_messages or [],
    )
    logger.info("ORCHESTRATOR MESSAGES: %d messages, first_user=%r last_user=%r", len(orchestrator_messages), orchestrator_messages[0]["content"] if orchestrator_messages and len(orchestrator_messages) > 0 else "", orchestrator_messages[-1]["content"] if orchestrator_messages else "")

    # Step 4: Stream orchestrator response
    try:
        logger.info("CALLING MODEL: model=%s temperature=%.1f", resolved_plan.orchestrator_model, 0.2)
        all_tokens = []
        async for token in chat_completion_stream(
            config,
            orchestrator_messages,
            model=resolved_plan.orchestrator_model,
            role="orchestrator",
            temperature=0.2,
            timeout=orchestration_cfg.get("worker_timeout_seconds", 12) * 10,
        ):
            all_tokens.append(token)
            yield token_event(chat_id, text=token, message_id=msg_id)
        logger.info("MODEL RESPONSE COMPLETE: total_tokens=%d text=%r", len(all_tokens), "".join(all_tokens))
    except Exception as exc:
        logger.error("Orchestrator streaming failed: %s", exc)
        yield error_event(
            chat_id,
            error_code="orchestrator_error",
            message=f"Orchestrator generation failed: {exc}",
            recoverable=True,
        )

    yield done_event(chat_id, message_id=msg_id)


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
    system_parts: list[dict],
    evidence_summary: str,
    previous_messages: list[dict],
) -> list[dict]:
    """Build the full message sequence for the orchestrator."""
    messages = list(system_parts)

    # Inject evidence summary if available
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


# ── MCP tool call handling stub ──────────────────────────────────────────────


async def handle_tool_calls(
    tool_calls: list[dict],
    mcp_client: Any,
) -> list[dict]:
    """Execute tool calls returned by the orchestrator.

    Args:
        tool_calls: List of tool_call dicts from the model response.
        mcp_client: MCP client instance (transport-agnostic).

    Returns:
        List of tool result dicts keyed by tool_call ID.
    """
    results = []
    for tc in tool_calls:
        tool_name = tc.get("function", {}).get("name", tc.get("name", ""))
        tool_args = tc.get("function", {}).get("arguments", tc.get("arguments", "{}"))
        if isinstance(tool_args, str):
            import json
            try:
                tool_args = json.loads(tool_args)
            except json.JSONDecodeError:
                tool_args = {}

        try:
            result = await mcp_client.call_tool(tool_name, tool_args)
            results.append({
                "tool_call_id": tc.get("id", tc.get("call_id", "")),
                "content": result,
            })
        except Exception as exc:
            logger.warning("MCP tool call '%s' failed: %s", tool_name, exc)
            results.append({
                "tool_call_id": tc.get("id", tc.get("call_id", "")),
                "content": f"Tool error: {exc}",
            })

    return results


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
