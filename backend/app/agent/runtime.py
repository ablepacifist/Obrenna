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

import json
import logging
import uuid
from typing import Any, AsyncIterator

from sqlalchemy.orm import Session

from ..mcp.client import MCPClient, InMemoryTransport
from ..mcp.tools import list_tools, call_tool
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
    use_workers = workers_enabled and resolved_plan.helper_count > 0 and bool(resolved_plan.utility_model)
    use_summarizer = bool(resolved_plan.summarizer_model)
    orchestration_cfg = get_orchestration_config()
    worker_timeout = orchestration_cfg.get("worker_timeout_seconds", 12)
    max_tool_rounds = orchestration_cfg.get("max_tool_rounds", 5)
    logger.info("=== ORCHESTRATE TURN === chat_id=%s user_message=%r orchestrator_model=%s summarizer_model=%s utility_model=%s workers_enabled=%s", chat_id, user_message, resolved_plan.orchestrator_model, resolved_plan.summarizer_model, resolved_plan.utility_model, workers_enabled)

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
                workers_enabled=workers_enabled,
            )
            evidence_pack = EvidencePack(
                entries=[r.to_evidence_entry() for r in worker_results],
                failure_count=sum(1 for r in worker_results if r.status != WorkerStatus.SUCCESS),
            )
            if use_summarizer and resolved_plan.summarizer_model:
                summary_text, success = await summarize_into_evidence_pack(
                    config, resolved_plan.summarizer_model, evidence_pack,
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

    # Step 3: Build orchestrator messages
    orchestrator_messages = _build_orchestrator_messages(
        user_message, system_parts, evidence_summary, previous_messages or [],
    )
    logger.info("ORCHESTRATOR MESSAGES: %d messages, first_user=%r last_user=%r", len(orchestrator_messages), orchestrator_messages[0]["content"] if orchestrator_messages and len(orchestrator_messages) > 0 else "", orchestrator_messages[-1]["content"] if orchestrator_messages else "")

    # Step 4: Prepare MCP client and tool definitions
    import os
    from ..mcp.client import create_mcp_client
    from ..mcp.tools import acall_tool as _acall_tool

    # Check for MCP proxy URL (set by Rust Tauri when MCP server is available)
    proxy_url = os.getenv("OBRENNA_MCP_PROXY_URL")

    if proxy_url:
        # Use TCP transport to connect to Rust MCP proxy
        mcp_client = create_mcp_client(proxy_url)
    else:
        # Fallback: use in-process transport for dev/testing
        transport = InMemoryTransport()
        transport.register_handler("tools/list", lambda p: {"tools": list_tools()})
        transport.register_handler("tools/call", lambda p: _acall_tool(p["name"], p.get("arguments", {})))
        mcp_client = MCPClient(transport)

    await mcp_client.initialize()

    allowed_tools = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search)
    model_tools = _format_tools_for_model(allowed_tools) if allowed_tools else None

    # Step 5: Stream orchestrator response with tool support
    stream_timeout = orchestration_cfg.get("worker_timeout_seconds", 12) * 10
    tool_round = 0
    all_tokens = []

    while tool_round < max_tool_rounds:
        tool_round += 1
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
            ):
                if event.get("type") == "thinking_delta":
                    text = event.get("content", "") or event.get("text", "")
                    if text:
                        yield thinking_delta_event(chat_id, text=text, message_id=msg_id)
                    continue
                if event.get("type") == "token":
                    text = event.get("content", "")
                    if text:
                        all_tokens.append(text)
                        yield token_event(chat_id, text=text, message_id=msg_id)
                elif event.get("type") == "tool_calls_done":
                    calls = event.get("calls", [])
                    if calls:
                        detected_tool_calls = calls
                        # Yield individual tool_call events for each tool
                        for tc in calls:
                            fn = tc.get("function", {})
                            yield tool_call_event(
                                chat_id=chat_id,
                                tool_name=fn.get("name", ""),
                                call_id=tc.get("id", ""),
                                arguments=fn.get("arguments", {}) if isinstance(fn.get("arguments"), dict) else {},
                                message_id=msg_id,
                            )
                        # Yield progress event
                        yield tool_progress_event(
                            chat_id=chat_id,
                            tool_name=f"({len(calls)} tool(s))",
                            status="running",
                            summary="Executing tool calls...",
                            message_id=msg_id,
                        )

                        # Execute tool calls
                        tool_results = await handle_tool_calls(
                            calls, mcp_client, tool_name_key="function.name",
                            tool_args_key="function.arguments",
                        )
                        tool_round_results = 0
                        for tc, result_text in zip(calls, tool_results):
                            fn = tc.get("function", {})
                            tool_progress_event_sent = False
                            for key, val in result_text.items():
                                if isinstance(val, dict) and "tool_call_id" in val:
                                    tr = val
                                    tool_name = fn.get("name", "unknown")
                                    call_id = tr.get("tool_call_id", "")
                                    content = tr.get("content", "")
                                    # Yield progress for this tool
                                    yield tool_progress_event(
                                        chat_id=chat_id,
                                        tool_name=tool_name,
                                        status="done",
                                        summary=content[:100] if content else "",
                                        message_id=msg_id,
                                    )
                                    tool_progress_event_sent = True
                                    # Yield result event
                                    yield tool_result_event(
                                        chat_id=chat_id,
                                        tool_name=tool_name,
                                        call_id=call_id,
                                        result=content,
                                        message_id=msg_id,
                                    )
                                    # Append tool result to messages
                                    orchestrator_messages.append({
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "content": content,
                                    })
                                    tool_round_results += 1
                            break

                        # Append assistant message with tool calls
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

                        # If tools were executed, break inner loop to re-call model
                        if tool_round_results > 0:
                            break
                    break

        except Exception as exc:
            logger.error("Orchestrator streaming failed: %s", exc)
            yield error_event(
                chat_id,
                error_code="orchestrator_error",
                message=f"Orchestrator generation failed: {exc}",
                recoverable=True,
            )
            break

        # If we detected tool calls, continue loop to feed results back to model
        if detected_tool_calls:
            if tool_round >= max_tool_rounds:
                logger.warning("Max tool rounds (%d) reached — sending answer without tool results", max_tool_rounds)
            # model_tools is set to None on next iteration (no tools on follow-up calls)
            model_tools = None
            all_tokens = []  # Reset for final answer tokens
            continue

        # No tool calls — this is the final answer stream
        break

    logger.info("MODEL RESPONSE COMPLETE: total_tokens=%d", len(all_tokens))
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


# ── MCP tool call handling ────────────────────────────────────────────────────


async def handle_tool_calls(
    tool_calls: list[dict],
    mcp_client: Any,
    *,
    tool_name_key: str = "name",
    tool_args_key: str = "arguments",
) -> list[dict]:
    """Execute tool calls returned by the orchestrator.

    Args:
        tool_calls: List of tool_call dicts from the model response.
        mcp_client: MCP client instance (transport-agnostic).
        tool_name_key: Key path for tool name (e.g. "name" or "function.name").
        tool_args_key: Key path for tool arguments
            (e.g. "arguments" or "function.arguments").

    Returns:
        List of tool result dicts with keys: tool_call_id, content.
    """
    results = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        tool_name = fn.get(tool_name_key, tc.get(tool_name_key, ""))
        tool_args = fn.get(tool_args_key, tc.get(tool_args_key, {}))
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except (json.JSONDecodeError, TypeError):
                tool_args = {}

        call_id = tc.get("id", tc.get("call_id", ""))

        try:
            result = await mcp_client.call_tool(tool_name, tool_args)
            results.append({
                "tool_call_id": call_id,
                "content": result,
            })
        except Exception as exc:
            logger.warning("MCP tool call '%s' failed: %s", tool_name, exc)
            results.append({
                "tool_call_id": call_id,
                "content": f"Tool error: {exc}",
            })

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
    """Convert architecture_config tool defs to OpenAI tools format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": _input_schema_to_openai_params(t.get("inputSchema", {})),
            }
        }
        for t in allowed_tools
    ]


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
