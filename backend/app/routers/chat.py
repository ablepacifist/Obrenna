"""P6 chat routing: intent detection → appropriate artifact builder or model response.

Integrates the agent runtime for normal chat while preserving deterministic
artifact generation paths (dashboard, report, chart, table, summary).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..agent.events import (
    StreamEvent,
    artifact_plan_event,
    artifact_skeleton_event,
    artifact_update_event,
    done_event,
    new_message_id,
    phase_event,
)
from ..agent.emitter import get_emitter, TokenCoalescer
from ..agent.runtime import (
    build_resolved_plan,
    get_allowed_mcp_tool_names,
    is_exp0_plan,
    load_architecture_config,
    orchestrate_turn,
)
from ..db import get_db
from ..models import AppSettings, Artifact, Chat, ChatMessage, CodebaseProject, File, ModelEndpoint
from ..model_runtime.client import chat_completion_sync
from ..model_runtime.config import RuntimeConfig
from ..agent.approvals import (
    cancel_chat_approvals,
    list_pending_for_chat,
    resolve_approval,
)
from ..agent.questions import (
    list_pending_for_chat as list_pending_questions,
    resolve_question,
)
from ..schemas.api import (
    AnswerQuestionRequest,
    AnswerQuestionResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ChatMessageDTO,
    ChatRequest,
    ChatResponse,
    PendingApprovalDTO,
    PendingQuestionDTO,
)
from ..schemas.artifact import validate_artifact
from ..services import csv_profiler, dashboard_builder, summarize
from ..services.hardware_resolver import (
    choose_and_validate,
    HardwareFingerprint,
    LiveFreeResources,
    build_fingerprint,
    build_live,
)
from ..services.memory import (
    assemble_context,
    extract_and_reconcile_facts,
    get_active_facts,
    record_turn_after_response,
)
from ..services.storage import artifact_pdf_path
from ..services.trace_logging import trace_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")


def _commit_or_http_error(db: Session, *, phase: str) -> None:
    """Commit request-scoped chat state or fail the request cleanly."""
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Chat DB commit failed during %s: %s", phase, exc)
        raise HTTPException(status_code=503, detail=f"Could not persist chat state: {exc}") from exc


# ── Tool-event capture (grounds the model's memory of its own file actions) ──

# Codebase tools that touch the filesystem. Only these are worth replaying into
# later turns' history — read-only calls (list/read/search) don't need grounding
# and would just bloat the context.
_MUTATING_TOOLS = {
    "codebase_write_file", "codebase_edit_file",
    "codebase_delete_file", "codebase_move_file",
}
_MUTATING_VERB = {
    "codebase_write_file": "created",
    "codebase_edit_file": "edited",
    "codebase_delete_file": "deleted",
    "codebase_move_file": "moved",
}


def _summarize_tool_event(tool: str, arguments: dict, result: str) -> dict:
    """Reduce a call→result pair to a compact, JSON-serialisable record.

    ``ok`` is derived from the result payload: dispatch returns
    ``{"error": true, ...}`` on failure, otherwise a success dict. The summary
    is a short human string used both in the UI and in the history trailer.
    """
    ok = True
    detail = ""
    if isinstance(result, str) and result:
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                ok = not parsed.get("error", False)
                if not ok:
                    detail = str(parsed.get("message", ""))[:200]
        except (json.JSONDecodeError, ValueError):
            # Non-JSON result (rare) — treat presence as success, no detail.
            pass
    path = arguments.get("path") if isinstance(arguments, dict) else None
    new_path = arguments.get("new_path") if isinstance(arguments, dict) else None
    return {
        "tool": tool,
        "path": path,
        "new_path": new_path,
        "ok": ok,
        "detail": detail,
    }


# Per-field cap on what goes into a persisted block. A whole-file
# codebase_write_file body (or a giant diff) would otherwise land verbatim in
# the row and be replayed into the UI on every load. Generous enough that real
# edits survive intact; the live view already showed the untruncated version.
_BLOCK_ARG_MAX_CHARS = 8000
_BLOCK_SUMMARY_MAX_CHARS = 400
# Arguments worth keeping for rendering. Everything needed to draw a diff or
# name the target; anything else is noise in the transcript.
_BLOCK_KEEP_ARGS = (
    "path", "new_path", "old_string", "new_string", "content", "command",
    # ask_user renders as the question it asked, not as a tool invocation.
    "question", "options",
    # The read-only tools' own arguments. Without these a search or a read
    # persisted with empty args, so the reloaded card was a bare tool name with
    # nothing under it -- the user could see that it did something, but never
    # what.
    "pattern", "regex", "cwd", "offset", "limit", "recursive",
)
# How much of a command's output to keep for the transcript. Enough to see what
# happened without replaying a whole build log on every page load.
_BLOCK_OUTPUT_MAX_CHARS = 2000
_BLOCK_MAX_RESULT_PATHS = 8
# Reasoning is worth keeping but is the longest thing in a turn; bounded so a
# reloaded transcript doesn't replay megabytes of CoT.
_BLOCK_THINKING_MAX_CHARS = 12000


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "\n… (truncated)"
    return value


def _render_args_for_block(tool: str, arguments: dict) -> dict:
    """Keep only the args the UI renders, each capped."""
    if not isinstance(arguments, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _BLOCK_KEEP_ARGS:
        if key in arguments:
            out[key] = _truncate(arguments[key], _BLOCK_ARG_MAX_CHARS)
    return out


def _tail(value: Any, limit: int) -> str:
    """Keep the END of a stream. An error is at the bottom of a log, not the top."""
    text = value if isinstance(value, str) else ""
    if len(text) <= limit:
        return text
    return "… (earlier output trimmed)\n" + text[-limit:]


def _render_result_for_block(tool: str, parsed: dict) -> dict | None:
    """What a tool produced, in the shape the transcript renders.

    Only ``status`` and an error ``message`` used to be kept. codebase_run_command
    has no ``message`` on success, so its exit code and output had nowhere to
    live and the card could never show what the command printed -- the user
    watched it run a command and was never shown the result.
    """
    if tool == "codebase_run_command":
        out: dict[str, Any] = {}
        if "exit_code" in parsed:
            out["exitCode"] = parsed.get("exit_code")
        for key, field in (("stdout", "stdout"), ("stderr", "stderr")):
            text = _tail(parsed.get(key), _BLOCK_OUTPUT_MAX_CHARS)
            if text:
                out[field] = text
        if parsed.get("timed_out"):
            out["timedOut"] = True
        return out or None

    if tool == "codebase_search":
        matches = parsed.get("matches")
        if not isinstance(matches, list):
            return None
        paths: list[str] = []
        for match in matches:
            path = match.get("path") if isinstance(match, dict) else None
            if isinstance(path, str) and path not in paths:
                paths.append(path)
            if len(paths) >= _BLOCK_MAX_RESULT_PATHS:
                break
        return {
            "matchCount": len(matches),
            "paths": paths,
            "truncated": bool(parsed.get("truncated")),
        }

    if tool == "codebase_read_file":
        lines = parsed.get("content")
        out = {"path": str(parsed.get("path") or "")}
        if isinstance(lines, str):
            out["lineCount"] = len(lines.splitlines())
        if parsed.get("truncated"):
            out["truncated"] = True
        return out

    if tool == "codebase_list_directory":
        entries = parsed.get("entries")
        if not isinstance(entries, list):
            return None
        return {"entryCount": len(entries), "truncated": bool(parsed.get("truncated"))}

    return None


class _BlockAccumulator:
    """Builds the ordered render blocks for an assistant turn.

    Mirrors what ChatThread does live (text runs and tool cards interleaved in
    arrival order) so a reloaded transcript looks like what the user watched,
    instead of collapsing to flat text with the diffs thrown away.

    Note it does NOT clear text at round boundaries the way the persisted flat
    ``text`` does. That truncation exists so the saved reply is just the final
    answer; here the preamble prose is part of the cadence the user saw, so it
    is kept.
    """

    def __init__(self) -> None:
        self.blocks: list[dict] = []
        self._by_call: dict[str, dict] = {}

    def add_token(self, text: str) -> None:
        if not text:
            return
        if self.blocks and self.blocks[-1].get("kind") == "text":
            self.blocks[-1]["text"] += text
        else:
            self.blocks.append({"kind": "text", "text": text})

    def add_thinking(self, text: str) -> None:
        if not text:
            return
        if self.blocks and self.blocks[-1].get("kind") == "thinking":
            block = self.blocks[-1]
            # Bounded: a long reasoning trace is worth keeping, an unbounded one
            # would replay megabytes into the UI on every load.
            if len(block["text"]) < _BLOCK_THINKING_MAX_CHARS:
                block["text"] += text
        else:
            self.blocks.append({"kind": "thinking", "text": text})

    def add_tool_call(self, call_id: str, tool_name: str, arguments: dict) -> None:
        block = {
            "kind": "tool",
            "callId": call_id,
            "toolName": tool_name,
            "args": _render_args_for_block(tool_name, arguments),
            "status": "running",
        }
        self.blocks.append(block)
        if call_id:
            self._by_call[call_id] = block

    def add_narration(self, call_id: str, description: str) -> None:
        block = self._by_call.get(call_id)
        if block is not None and description:
            block["description"] = _truncate(description, _BLOCK_SUMMARY_MAX_CHARS)

    def finish_tool(self, call_id: str, result: str) -> None:
        block = self._by_call.get(call_id)
        if block is None:
            return
        ok = True
        summary = ""
        parsed: Any = None
        if isinstance(result, str) and result:
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    ok = not parsed.get("error", False)
                    summary = str(parsed.get("message", "") or "")
            except (json.JSONDecodeError, ValueError):
                parsed = None
        block["status"] = "done" if ok else "error"
        if summary:
            block["summary"] = _truncate(summary, _BLOCK_SUMMARY_MAX_CHARS)
        if isinstance(parsed, dict):
            outcome = _render_result_for_block(block.get("toolName", ""), parsed)
            if outcome:
                block["result"] = outcome

    def result(self) -> list[dict]:
        # Drop whitespace-only prose/reasoning runs so a reloaded message
        # doesn't render empty bubbles.
        return [
            b for b in self.blocks
            if b.get("kind") not in ("text", "thinking") or (b.get("text") or "").strip()
        ]


def _tool_events_history_trailer(events: list[dict]) -> str:
    """One-line factual log of the mutating file actions an assistant turn took.

    Appended to that assistant message's content in later turns' history so the
    model cannot truthfully claim it "never created/edited/deleted any file" —
    the single most damaging failure in the reviewed transcript, where amnesia
    about its own actions made it gaslight the user.
    """
    parts: list[str] = []
    for ev in events:
        if ev.get("tool") not in _MUTATING_TOOLS:
            continue
        verb = _MUTATING_VERB.get(ev.get("tool", ""), "changed")
        path = ev.get("path") or "?"
        if ev.get("tool") == "codebase_move_file" and ev.get("new_path"):
            target = f"{path} → {ev['new_path']}"
        else:
            target = path
        status = "ok" if ev.get("ok") else f"FAILED: {ev.get('detail') or 'error'}"
        parts.append(f"{verb} {target} ({status})")
    if not parts:
        return ""
    return "[Actions you actually performed this turn: " + "; ".join(parts) + "]"

# ── Intent keywords ──────────────────────────────────────────────────────────

_DASHBOARD_KEYWORDS = {"dashboard", "csv", "visualize", "visualise", "chart it", "graph it"}
_REPORT_KEYWORDS = {"report", "proposal", "write up", "write-up"}
_CHART_KEYWORDS = {"chart", "bar chart", "line chart", "plot", "forecast"}
_TABLE_KEYWORDS = {"table", "tabulate", "list all", "show all"}
_SUMMARY_KEYWORDS = {"summary", "summarise", "summarize", "notes", "brief", "tldr", "tl;dr"}


def _detect_intent(text: str) -> str:
    lower = text.lower()
    for kw in _DASHBOARD_KEYWORDS:
        if kw in lower:
            return "dashboard"
    for kw in _REPORT_KEYWORDS:
        if kw in lower:
            return "report"
    for kw in _CHART_KEYWORDS:
        if kw in lower:
            return "chart"
    for kw in _TABLE_KEYWORDS:
        if kw in lower:
            return "table"
    for kw in _SUMMARY_KEYWORDS:
        if kw in lower:
            return "summary"
    return "chat"


def _save_artifact(spec: dict, db: Session) -> Artifact:
    # Validate against the canonical artifact schema (shared/artifact-schema.json
    # via schemas/artifact.py) before persisting. Builders are deterministic
    # today so this should never fail — but nothing previously caught a
    # spec that drifted from the schema (e.g. a builder bug producing a
    # malformed chart), so a corrupt artifact could reach the DB and only
    # surface as a confusing frontend rendering error. Log and continue
    # rather than reject: this is a safety net for a currently-trusted
    # deterministic path, not a hard boundary against untrusted input.
    try:
        validate_artifact(spec)
    except ValidationError as exc:
        logger.warning("Artifact spec failed schema validation (saving anyway): %s", exc)

    record = Artifact(
        id=spec["id"],
        artifact_type=spec["artifact_type"],
        title=spec["title"],
        summary=spec.get("summary"),
        source_file_id=spec.get("source_file_id"),
        spec=spec["spec"],
    )
    db.add(record)
    db.flush()
    return record


def _get_hardware_plan(db: Session, workers_enabled: bool = True) -> dict:
    """Resolve the hardware plan. Returns a fallback plan if resolution fails.

    Uses the SAME resolution path as the setup flow and the Local status pill
    (``resolve_managed_plan`` → ``probe_all``). The earlier implementation fed
    the display-summary dict from ``detect_hardware()`` into ``build_fingerprint``,
    which expects raw probe keys (gpu_vendor, ram_total_gb, cpu_physical_cores…).
    That produced an all-zero fingerprint that always resolved to "reject", so
    the orchestrator model came back empty and chat failed with
    "No model configured for this request."
    """
    ep = db.get(ModelEndpoint, 1)
    runtime_base_url = ep.base_url if ep else None
    try:
        from ..services.hardware import resolve_managed_plan
        plan = resolve_managed_plan(runtime_base_url=runtime_base_url)
        if isinstance(plan.get("orchestrator"), dict) and plan["orchestrator"].get("model"):
            return plan
        logger.warning("Managed plan resolved without an orchestrator model: path=%s", plan.get("path"))
    except Exception as exc:
        logger.warning("Hardware resolution failed: %s", exc)

    # Fallback: use the current model endpoint settings
    if ep and ep.models:
        orchestrator_model = ep.models.get("orchestrator") or ep.models.get("main_reasoner", "")
        return {
            "path": "fallback",
            "ctx": 8192,
            "helper_count": 0 if not workers_enabled else 1,
            "orchestrator": {
                "model": orchestrator_model,
                "tool_call_mode": _lookup_tool_call_mode(orchestrator_model),
            },
            "summarizer": {},
            "utility": {} if workers_enabled else {},
        }
    return {
        "path": "fallback",
        "ctx": 8192,
        "helper_count": 0 if not workers_enabled else 1,
        "orchestrator": {"model": "", "tool_call_mode": "openai_native"},
        "summarizer": {},
        "utility": {},
    }


def _apply_orchestrator_override(db: Session, plan: dict) -> dict:
    """If AppSettings.orchestrator_override is set, force that catalog slug as the
    orchestrator, pulling its capabilities (tool_call_mode / reasoning_distilled /
    max_tool_rounds / tool_result_budget) from the catalog. Lets the user run a
    bigger model than the hardware resolver would auto-pick — they accept the
    slower inference. Summarizer/utility stay as resolved."""
    override = ""
    try:
        row = db.get(AppSettings, 1)
        override = (getattr(row, "orchestrator_override", None) or "").strip()
    except Exception:
        return plan
    if not override:
        return plan
    try:
        from ..services.hardware_catalog import (
            load_catalog, tool_call_mode_for, reasoning_distilled_for,
            max_tool_rounds_for, tool_result_budget_for,
        )
        cat = load_catalog()
        plan = dict(plan)
        plan["orchestrator"] = {
            "model": override,  # catalog slug; _apply_runtime_model_refs → ollama ref
            "tool_call_mode": tool_call_mode_for(cat, override),
            "reasoning_distilled": reasoning_distilled_for(cat, override),
            "max_tool_rounds": max_tool_rounds_for(cat, override),
            "tool_result_budget": tool_result_budget_for(cat, override),
            # A forced-bigger model is usually running past its hardware tier
            # (e.g. a 27B spilling to RAM). Pin it resident so the ~1min cold-load
            # is paid once, and give it a long stream timeout so slow generation
            # isn't killed mid-answer (the user opted into "slow but bigger").
            "keep_alive": -1,
            "stream_timeout_seconds": 900,
        }
        plan["orchestrator_override_applied"] = override
        logger.info("ORCHESTRATOR OVERRIDE active: %s", override)
    except Exception as exc:
        logger.warning("Could not apply orchestrator override %r: %s", override, exc)
    return plan


def _lookup_tool_call_mode(model_slug: str) -> str:
    """Look up a model's tool_call_mode from the catalog for the fallback plan.

    The fallback plan (used when hardware resolution fails or is unavailable)
    previously omitted tool_call_mode entirely, so ResolvedPlan defaulted to
    "openai_native" regardless of the actual model. The DB-seeded default
    orchestrator is a prompt-JSON distill (see db.py init_db) — without this
    lookup, that model would be driven as if it emitted native OpenAI
    tool_calls, and its JSON tool-call envelope would leak into the chat as
    literal text instead of being parsed by the prompt-JSON scanner.
    """
    if not model_slug:
        return "openai_native"
    try:
        from ..services.hardware_catalog import load_catalog, tool_call_mode_for
        return tool_call_mode_for(load_catalog(), model_slug)
    except Exception as exc:
        logger.warning("Could not resolve tool_call_mode for '%s': %s", model_slug, exc)
        return "openai_native"


def _get_global_workers_setting(db: Session) -> bool:
    """Get the global workers setting from AppSettings."""
    settings = db.get(AppSettings, 1)
    return settings.workers_enabled if settings else True


def _apply_runtime_model_refs(plan: dict, config: RuntimeConfig) -> None:
    """Translate catalog model slugs to runtime pull refs, in place.

    The catalog assigns models by a short slug (e.g.
    ``qwen3.5-0.8b-claude-opus-reasoning-distilled``) but the local runtime
    serves the model under its pull ref (e.g.
    ``radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF``).
    Provisioning pulls the ref, so generation must request the ref too —
    otherwise the runtime returns a model-not-found error.
    """
    if config.runtime_kind != "ollama":
        return
    try:
        from ..services.hardware_catalog import load_catalog, resolve_ollama_pull_ref
        catalog = load_catalog()
    except Exception as exc:
        logger.warning("Could not load catalog for model-ref translation: %s", exc)
        return
    for role in ("orchestrator", "summarizer", "utility"):
        ref = plan.get(role)
        if isinstance(ref, dict) and ref.get("model"):
            ref["model"] = resolve_ollama_pull_ref(catalog, ref["model"])


def _get_runtime_config(db: Session) -> RuntimeConfig:
    """Build a RuntimeConfig from the model endpoint settings."""
    ep = db.get(ModelEndpoint, 1)
    if not ep or not ep.base_url:
        raise ValueError("No model endpoint configured")
    return RuntimeConfig(
        provider=ep.provider,
        base_url=ep.base_url,
        api_key=ep.api_key or "",
        models=ep.models or {},
    )


# ── Artifact generation routes (deterministic, unchanged) ────────────────────

@router.post("", response_model=ChatResponse)
def send_message(payload: ChatRequest, db: Session = Depends(get_db)):
    """Backward-compatible chat endpoint — checks intent first.

    For artifact intents (dashboard, report, chart, table, summary) with
    a CSV file, generates the artifact and returns immediately.

    For normal chat, delegates to the agent runtime.

    Thin wrapper around ``_process_chat_message`` — kept as its own function
    (rather than inlined) because ``router.add_api_route("/artifact", ...)``
    below aliases this exact function object to a second route.
    """
    return _process_chat_message(payload, db)


# One turn at a time per chat. Ollama serializes generations anyway, so two
# concurrent turns in one chat (a user double-sending into a slow reply) just
# meant the second request sat silent until it timed out, interleaving two
# half-finished answers into the history. Serializing here keeps turn order
# and lets the second turn see the first one's completed exchange. Threading
# (not asyncio) locks because both routes execute this in worker threads.
_chat_turn_locks: dict[str, threading.Lock] = {}
_chat_turn_locks_guard = threading.Lock()


def _turn_lock_for_chat(chat_id: str) -> threading.Lock:
    with _chat_turn_locks_guard:
        lock = _chat_turn_locks.get(chat_id)
        if lock is None:
            lock = _chat_turn_locks[chat_id] = threading.Lock()
        return lock


def _process_chat_message(
    payload: ChatRequest,
    db: Session,
    *,
    event_sink: Callable[[StreamEvent], None] | None = None,
) -> ChatResponse:
    """Serialized entry point: waits for any in-flight turn on the same chat."""
    if not payload.chat_id:
        # Brand-new chat gets a fresh id inside — no contention possible.
        return _process_chat_message_inner(payload, db, event_sink=event_sink)
    lock = _turn_lock_for_chat(payload.chat_id)
    if not lock.acquire(timeout=600):
        raise HTTPException(
            status_code=409,
            detail="Still working on the previous message in this chat — try again in a moment.",
        )
    try:
        return _process_chat_message_inner(payload, db, event_sink=event_sink)
    finally:
        lock.release()


def _process_chat_message_inner(
    payload: ChatRequest,
    db: Session,
    *,
    event_sink: Callable[[StreamEvent], None] | None = None,
) -> ChatResponse:
    """Shared implementation behind both ``POST /api/chat`` and
    ``POST /api/chat/stream``. ``event_sink``, when provided, receives every
    orchestrator ``StreamEvent`` live (in addition to — not instead of — the
    stdout/Tauri emitter path) so a caller can relay them over HTTP.
    """
    # DEBUG, not INFO: message content is private local content and must not
    # land in default-level logs on a local-first/private-by-default product.
    logger.debug("=== CHAT REQUEST === chat_id=%s message=%r file_ids=%s", payload.chat_id, payload.message, payload.file_ids)
    trace_event(
        "chat_request_received",
        chat_id=payload.chat_id,
        assistant_message_id=payload.assistant_message_id,
        user_message=payload.message,
        file_ids=payload.file_ids,
        workers_enabled=payload.workers_enabled,
        web_search=payload.web_search,
        thinking_enabled=payload.thinking_enabled,
    )
    ep = db.get(ModelEndpoint, 1)
    logger.info("MODEL ENDPOINT: provider=%s base_url=%s api_key_set=%s models=%s", ep.provider if ep else None, ep.base_url if ep else None, bool(ep.api_key) if ep else None, ep.models if ep else None)

    # Resolve or create chat
    if payload.chat_id:
        chat = db.get(Chat, payload.chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found.")
    else:
        # Attach the codebase chosen in the composer before the chat existed.
        # Validated against the table so a stale/bogus id can't be persisted
        # (the tool dispatch would then silently find no project).
        new_project_id: Optional[str] = None
        if payload.active_codebase_project_id:
            if db.get(CodebaseProject, payload.active_codebase_project_id):
                new_project_id = payload.active_codebase_project_id
            else:
                logger.warning(
                    "Ignoring unknown active_codebase_project_id=%s on new chat",
                    payload.active_codebase_project_id,
                )
        chat = Chat(
            id=uuid.uuid4().hex,
            title=payload.message[:60] or "New chat",
            active_codebase_project_id=new_project_id,
            agent_mode=payload.agent_mode or "auto",
        )
        db.add(chat)
        db.flush()

    # Resolve file records — only include text-based files (skip images, binaries)
    _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.svg', '.ico', '.apng'}
    file_records: list[File] = []
    skipped_images: list[str] = []
    for fid in payload.file_ids:
        fr = db.get(File, fid)
        if fr:
            _, ext = os.path.splitext(fr.filename.lower())
            if ext in _IMAGE_EXTS:
                skipped_images.append(fr.filename)
            else:
                file_records.append(fr)
    if skipped_images:
        logger.warning("Skipping non-text files in chat: %s", skipped_images)

    # Persist user message
    user_msg = ChatMessage(
        id=uuid.uuid4().hex,
        chat_id=chat.id,
        role="user",
        text=payload.message,
        files=[{"name": f.filename, "size": f.size_bytes} for f in file_records],
    )
    db.add(user_msg)
    db.flush()
    trace_event(
        "user_message_persisted",
        chat_id=chat.id,
        user_message_id=user_msg.id,
        user_message=user_msg.text,
        files=user_msg.files,
    )

    intent = _detect_intent(payload.message)
    logger.info("INTENT DETECTED: %s", intent)
    trace_event("chat_intent_detected", chat_id=chat.id, user_message_id=user_msg.id, intent=intent)
    artifact_ids: list[str] = []
    tool_events: list[dict] = []
    reply_text = ""
    msg_id: str = payload.assistant_message_id or new_message_id()
    used_runtime = False
    is_exp0 = False
    effective_workers_enabled = (
        payload.workers_enabled
        if payload.workers_enabled is not None
        else _get_global_workers_setting(db)
    )

    csv_file = next((f for f in file_records if f.filename.lower().endswith(".csv")), None)

    if intent in ("dashboard", "report", "chart", "table", "summary") and csv_file:
        logger.info("ARTIFACT PATH: intent=%s csv_file=%s", intent, csv_file.filename)
        reply_text, artifact_ids = _handle_artifact_intent(
            intent, csv_file, payload.message, db, chat.id, msg_id
        )
    elif intent in ("summary",) and file_records:
        logger.info("TEXT SUMMARY PATH: files=%s", [f.filename for f in file_records])
        reply_text, artifact_ids = _handle_text_summary(file_records, db, chat.id, msg_id)
    else:
        logger.info("NORMAL CHAT PATH: delegating to agent runtime")
        used_runtime = True
        # The model/tool path can take seconds. Do not hold SQLite's write lock
        # from the chat/user INSERTs while orchestration runs, or concurrent UI
        # requests/new chats fail with `database is locked`.
        _commit_or_http_error(db, phase="initial user message")
        # Normal chat — use agent runtime
        reply_text, msg_id, is_exp0, tool_events, reply_blocks = _handle_normal_chat(db, chat, user_msg, payload,
                                                  assistant_message_id=msg_id,
                                                  web_search=payload.web_search,
                                                  workers_enabled=effective_workers_enabled,
                                                  thinking_enabled=payload.thinking_enabled,
                                                  event_sink=event_sink)

    # DEBUG, not INFO: reply text is private local content.
    logger.debug("CHAT RESPONSE: reply=%r artifact_ids=%s msg_id=%s", reply_text, artifact_ids, msg_id)
    trace_event(
        "chat_response_ready",
        chat_id=chat.id,
        user_message_id=user_msg.id,
        assistant_message_id=msg_id,
        used_runtime=used_runtime,
        is_exp0=is_exp0,
        reply_text=reply_text,
        artifact_ids=artifact_ids,
    )

    # Persist assistant message
    asst_msg = ChatMessage(
        id=msg_id or uuid.uuid4().hex,
        chat_id=chat.id,
        role="assistant",
        text=reply_text,
        artifacts=artifact_ids,
        tool_events=tool_events,
        blocks=reply_blocks,
    )
    db.add(asst_msg)

    # Update chat metadata
    if not chat.title or chat.title == "New chat":
        chat.title = payload.message[:60]
    chat.updated_at = datetime.now(timezone.utc)

    # Record turn and build memory events. record_turn_after_response may commit
    # the assistant message, chat metadata, and ChatTurn together; the explicit
    # commit below is still required for paths where turn recording is skipped or
    # fails after the assistant message has been added.
    memory_events: list[dict] = []
    try:
        turn_id = record_turn_after_response(db, chat, user_msg, asst_msg)
        if turn_id:
            active_facts = get_active_facts(db)
            memory_events = [{"type": "MEMORY_ACTIVE", "count": len(active_facts)}]
    except Exception as exc:
        logger.warning("Turn recording failed: %s", exc)

    _commit_or_http_error(db, phase="assistant response")
    db.refresh(asst_msg)
    trace_event(
        "assistant_message_persisted",
        chat_id=chat.id,
        user_message_id=user_msg.id,
        assistant_message_id=asst_msg.id,
        assistant_text=asst_msg.text,
        artifact_ids=asst_msg.artifacts or [],
        memory_events=memory_events,
    )

    # Dispatch fact extraction in background. Pass only IDs — the request's
    # SQLAlchemy Session is not thread-safe and must never be shared with a
    # background thread that outlives the request (see CRIT-004 in the
    # audit: the request thread closes this session when the request ends,
    # while the daemon thread may still be reading/writing through it).
    #
    # EXP0 (experimental_opt_in_tiers.EXP0.memory_subsystem_override in the
    # catalog) explicitly forbids loading the embedding model and disables
    # the retrieval gate entirely — recency-only, no persistent memory. Fact
    # extraction calls embed_text() (lazy-loading the ONNX embedder) and
    # makes background LLM calls, both of which violate that tier's budget.
    if is_exp0:
        logger.info("Skipping background fact extraction: EXP0 plan (recency-only, no embeddings).")
    else:
        try:
            t = threading.Thread(
                target=_run_fact_extraction,
                args=(chat.id, user_msg.id, asst_msg.id),
                daemon=True,
            )
            t.start()
        except Exception as exc:
            logger.warning("Failed to start fact extraction: %s", exc)

    if not used_runtime:
        get_emitter().emit(done_event(chat.id, message_id=asst_msg.id))

    return ChatResponse(
        chat_id=chat.id,
        message=ChatMessageDTO(
            id=asst_msg.id,
            role=asst_msg.role,
            text=asst_msg.text,
            artifacts=asst_msg.artifacts or [],
            files=asst_msg.files or [],
            tool_events=asst_msg.tool_events or [],
            created_at=asst_msg.created_at.isoformat(),
        ),
        memory_events=memory_events,
    )


router.add_api_route("/artifact", send_message, methods=["POST"], response_model=ChatResponse)


@router.get("/approvals/{chat_id}", response_model=list[PendingApprovalDTO])
async def list_chat_approvals(chat_id: str):
    """Approvals currently blocking this chat's turn.

    A client that reloaded mid-turn has missed the approval_request event and
    would otherwise show a turn that looks hung. This lets it recover the card.
    """
    # Wire shape keeps ``approval_id`` (what the client knows it as); the
    # registry calls it request_id since it also carries ask_user questions.
    return [
        PendingApprovalDTO(
            approval_id=a.request_id,
            chat_id=a.chat_id,
            message_id=a.message_id,
            tool_name=a.payload.get("tool_name", ""),
            call_id=a.payload.get("call_id", ""),
            arguments=a.payload.get("arguments", {}) or {},
            created_at=a.created_at,
        )
        for a in list_pending_for_chat(chat_id)
    ]


@router.get("/questions/{chat_id}", response_model=list[PendingQuestionDTO])
async def list_chat_questions(chat_id: str):
    """ask_user questions currently blocking this chat's turn (reload recovery)."""
    return [
        PendingQuestionDTO(
            question_id=q.request_id,
            chat_id=q.chat_id,
            message_id=q.message_id,
            call_id=q.payload.get("call_id", ""),
            question=q.payload.get("question", ""),
            options=q.payload.get("options", []) or [],
            created_at=q.created_at,
        )
        for q in list_pending_questions(chat_id)
    ]


@router.post("/questions/{question_id}", response_model=AnswerQuestionResponse)
async def answer_question(question_id: str, payload: AnswerQuestionRequest):
    """Answer a suspended ask_user question, resuming the turn.

    Same loop-crossing and lock-avoidance rules as ``decide_approval``.
    """
    try:
        question = resolve_question(question_id, payload.answer)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if question is None:
        raise HTTPException(
            status_code=404,
            detail="No such pending question — it may have already been answered, timed out, or its turn ended.",
        )
    return AnswerQuestionResponse(question_id=question_id, chat_id=question.chat_id)


@router.post("/approvals/{approval_id}", response_model=ApprovalDecisionResponse)
async def decide_approval(approval_id: str, payload: ApprovalDecisionRequest):
    """Approve or reject a suspended tool call, resuming the turn.

    Async (main loop) while the turn it unblocks sleeps on the runtime's own
    loop -- ``resolve_approval`` marshals the wakeup across. It deliberately
    does NOT take the chat's turn lock: the suspended turn still holds it, so
    acquiring it here would deadlock the very turn we're trying to release.
    """
    try:
        approval = resolve_approval(approval_id, payload.decision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if approval is None:
        raise HTTPException(
            status_code=404,
            detail="No such pending approval — it may have already been decided, timed out, or its turn ended.",
        )
    return ApprovalDecisionResponse(
        approval_id=approval_id,
        decision=payload.decision,
        chat_id=approval.chat_id,
    )


class _StreamDone:
    """Terminal sentinel: the chat turn finished successfully."""

    def __init__(self, response: ChatResponse) -> None:
        self.response = response


class _StreamError:
    """Terminal sentinel: the chat turn failed."""

    def __init__(self, message: str) -> None:
        self.message = message


@router.post("/stream")
async def send_message_stream(payload: ChatRequest):
    """SSE variant of ``POST /api/chat`` for browser clients.

    Plain HTTP clients (unlike the Tauri desktop app, which gets live
    progress via stdout -> Rust IPC, see ``agent/emitter.py``) otherwise see
    nothing until the whole turn completes — which routinely exceeds
    Cloudflare's ~100s idle timeout over the public tunnel, producing a 524.
    This streams the same orchestrator events as Server-Sent Events so bytes
    keep flowing and the browser can render progress live via the same
    ``handleAgentEvent`` reducer the desktop app already uses.

    Deliberately does not take ``db: Session = Depends(get_db)`` — the
    worker thread below opens its own session, decoupled from the request
    lifecycle. A client disconnect mid-stream unwinds FastAPI's dependency
    stack through an exception path that closes a ``Depends()``-injected
    session immediately, which would race the worker thread still using it.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _push(item) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:
            pass  # event loop already gone (server shutdown)

    def _worker() -> None:
        from ..db import SessionLocal

        db = SessionLocal()
        try:
            response = _process_chat_message(payload, db, event_sink=_push)
            _push(_StreamDone(response))
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            logger.error("Streaming chat orchestration failed: %s", exc)
            _push(_StreamError(str(detail)))
        finally:
            db.close()

    future = loop.run_in_executor(None, _worker)

    async def _event_gen():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if isinstance(item, _StreamDone):
                    yield f"event: response\ndata: {item.response.model_dump_json()}\n\n"
                    break
                if isinstance(item, _StreamError):
                    yield f"event: error\ndata: {json.dumps({'message': item.message})}\n\n"
                    break
                yield f"event: agent_event\ndata: {json.dumps(item.to_envelope())}\n\n"
        finally:
            # Join the worker thread before returning so Depends()-free db
            # usage above is fully done, and any unhandled exception in the
            # executor future surfaces (rather than being silently dropped).
            await future

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _handle_artifact_intent(
    intent: str, csv_file: File, message: str, db: Session, chat_id: str, message_id: str
) -> tuple[str, list[str]]:
    """Handle deterministic artifact generation."""
    emitter = get_emitter()
    artifact_type = "dashboard" if intent == "dashboard" else intent
    title = f"Preparing {artifact_type}"
    emitter.emit(phase_event(chat_id, message_id, "accepted", "Starting"))
    emitter.emit(phase_event(chat_id, message_id, "artifact_build", "Building artifact"))
    emitter.emit(artifact_plan_event(
        chat_id,
        message_id,
        artifact_type,
        title,
        ["profile_csv", "build_cards", "build_charts", "build_table"],
    ))
    emitter.emit(artifact_skeleton_event(
        chat_id,
        message_id,
        artifact_type,
        title,
        [
            {"kind": "metric_row", "status": "loading"},
            {"kind": "chart", "status": "loading"},
            {"kind": "table", "status": "loading"},
        ],
    ))
    try:
        emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "profile_csv", "running"))
        df = csv_profiler.load_csv(csv_file.stored_path)
        profile = csv_profiler.profile_dataframe(df)
        emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "profile_csv", "done"))

        if intent == "dashboard":
            emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "dashboard_spec", "running"))
            spec = dashboard_builder.build_dashboard(
                df, profile, file_id=csv_file.id, filename=csv_file.filename,
                instruction=message,
            )
            reply_text = f"Here's your dashboard for **{csv_file.filename}**."
        elif intent == "report":
            emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "report_spec", "running"))
            spec = summarize.build_report_from_csv(
                df, profile, file_id=csv_file.id, filename=csv_file.filename
            )
            reply_text = f"Here's a report generated from **{csv_file.filename}**."
        elif intent == "chart":
            spec = dashboard_builder.build_chart_artifact(
                df, profile, file_id=csv_file.id, filename=csv_file.filename
            )
            reply_text = f"Here's a chart from **{csv_file.filename}**."
        elif intent == "table":
            spec = dashboard_builder.build_table_artifact(
                df, profile, file_id=csv_file.id, filename=csv_file.filename
            )
            reply_text = f"Here's a table from **{csv_file.filename}**."
        else:  # summary
            emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "summary", "running"))
            spec = summarize.summarize_csv(
                profile, file_id=csv_file.id, filename=csv_file.filename
            )
            reply_text = f"Here's a summary of **{csv_file.filename}**."

        record = _save_artifact(spec, db)
        emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "artifact", "done", record.id))
        emitter.emit(phase_event(chat_id, message_id, "finalizing", "Finalizing"))
        return reply_text, [record.id]
    except Exception as exc:
        emitter.emit(artifact_update_event(chat_id, message_id, artifact_type, "artifact", "error"))
        return f"I ran into a problem processing your file: {exc}", []


def _handle_text_summary(file_records: list[File], db: Session, chat_id: str, message_id: str) -> tuple[str, list[str]]:
    """Handle non-CSV summary (extractive)."""
    fr = file_records[0]
    emitter = get_emitter()
    emitter.emit(phase_event(chat_id, message_id, "accepted", "Starting"))
    emitter.emit(artifact_skeleton_event(
        chat_id,
        message_id,
        "document",
        "Preparing summary",
        [{"kind": "document", "status": "loading"}],
    ))
    try:
        emitter.emit(artifact_update_event(chat_id, message_id, "document", "read_file", "running"))
        with open(fr.stored_path, "r", errors="replace") as fh:
            text_content = fh.read(8000)
        emitter.emit(artifact_update_event(chat_id, message_id, "document", "read_file", "done"))
        emitter.emit(artifact_update_event(chat_id, message_id, "document", "summary", "running"))
        spec = summarize.summarize_text(
            text_content, file_id=fr.id, filename=fr.filename
        )
        record = _save_artifact(spec, db)
        emitter.emit(artifact_update_event(chat_id, message_id, "document", "artifact", "done", record.id))
        emitter.emit(phase_event(chat_id, message_id, "finalizing", "Finalizing"))
        return f"Here's a summary of **{fr.filename}**.", [record.id]
    except Exception as exc:
        emitter.emit(artifact_update_event(chat_id, message_id, "document", "artifact", "error"))
        return f"Could not read file: {exc}", []


def _handle_normal_chat(
    db: Session,
    chat: Chat,
    user_msg: ChatMessage,
    payload: ChatRequest,
    *,
    assistant_message_id: str | None = None,
    web_search: bool = False,
    workers_enabled: bool = True,
    thinking_enabled: bool = False,
    event_sink: Callable[[StreamEvent], None] | None = None,
) -> tuple[str, str, bool, list[dict]]:
    """Handle normal chat via the agent runtime.

    Returns (reply_text, message_id, is_exp0_plan, tool_events) — the exp0 flag
    lets the caller skip work the EXP0 tier explicitly forbids (background fact
    extraction / embeddings), matching
    experimental_opt_in_tiers.EXP0.memory_subsystem_override in the catalog.
    ``tool_events`` is the compact per-turn record of tools the model actually
    ran, persisted on the assistant message and fed back into future history.
    """
    msg_id = assistant_message_id or new_message_id()

    # Determine worker setting: per-chat override or global default
    workers_enabled = payload.workers_enabled if payload.workers_enabled is not None else _get_global_workers_setting(db)

    # Get hardware plan and runtime config
    plan_result = _get_hardware_plan(db, workers_enabled=workers_enabled)
    plan_result = _apply_orchestrator_override(db, plan_result)
    logger.info("HARDWARE PLAN: workers_enabled=%s helper_count=%s orchestrator=%s", workers_enabled, plan_result.get("helper_count"), plan_result.get("orchestrator", {}).get("model"))
    config = _get_runtime_config(db)
    # Translate catalog slugs to the runtime's actual pull refs before resolving.
    _apply_runtime_model_refs(plan_result, config)
    resolved_plan = build_resolved_plan(plan_result)
    is_exp0 = is_exp0_plan(plan_result)
    logger.info("RUNTIME CONFIG: provider=%s base_url=%s models=%s", config.provider, config.base_url, config.models)
    logger.info("RESOLVED PLAN: orchestrator_model=%s summarizer_model=%s utility_model=%s ctx=%s", resolved_plan.orchestrator_model, resolved_plan.summarizer_model, resolved_plan.utility_model, resolved_plan.ctx)

    # Collect previous messages for context. The current user message was
    # already persisted above, so exclude it here — the runtime appends the
    # active user message itself, and including it in history duplicated the
    # active task (two identical trailing user turns), which biased small
    # orchestrators toward replaying the previous assistant answer.
    from ..models import ChatMessage as CM
    prev_msgs = (
        db.query(CM)
        .filter_by(chat_id=chat.id)
        .filter(CM.id != user_msg.id)
        .order_by(CM.created_at.desc())
        .limit(10)
        .all()
    )
    previous_messages = []
    for m in reversed(prev_msgs):
        content = m.text
        # Ground assistant turns in what they factually did: append a compact
        # action log so the model can't lose the memory of files it created,
        # edited, deleted, or moved on earlier turns.
        if m.role == "assistant" and getattr(m, "tool_events", None):
            trailer = _tool_events_history_trailer(m.tool_events)
            if trailer:
                content = f"{content}\n\n{trailer}" if content else trailer
        previous_messages.append({"role": m.role, "content": content})

    # Run agent orchestration synchronously (collect stream)
    from ..model_runtime.client import _run

    # Captured live from the stream: a compact record of every tool the model
    # actually ran this turn (paired call→result). Persisted on the assistant
    # message and fed back into later turns' history so the model doesn't lose
    # the memory of its own file actions (the "I never created any file" bug).
    captured_tool_events: list[dict] = []
    _pending_calls: dict[str, dict] = {}
    # Render-fidelity blocks (see _BlockAccumulator): what the UI replays after
    # a reload, including the edit diffs tool_events deliberately drops.
    blocks = _BlockAccumulator()

    try:
        async def _collect():
            tokens = []
            emitter = get_emitter()
            # Coalesce consecutive token events into fewer, larger token
            # envelopes before they hit stdout → the Rust sidecar relays ~16x
            # fewer Tauri events for long answers. Non-token events are
            # boundaries: they flush pending tokens first, then pass through
            # unchanged. ``tokens`` still accumulates EVERY token (from the
            # original per-token events) so the persisted reply text is whole.
            coalescer = TokenCoalescer(emitter, chat_id=chat.id, message_id=msg_id)
            # A second coalescer fans the same events out to event_sink (the
            # HTTP-streaming route's queue), when present. TokenCoalescer only
            # depends on a duck-typed .emit(StreamEvent), so a tiny adapter
            # around event_sink lets us reuse it without any new batching logic.
            sse_coalescer = None
            if event_sink is not None:
                class _SinkEmitter:
                    def emit(self, ev: "StreamEvent") -> None:
                        event_sink(ev)
                sse_coalescer = TokenCoalescer(_SinkEmitter(), chat_id=chat.id, message_id=msg_id)
            try:
                async for event in orchestrate_turn(
                    payload.message,
                    chat.id,
                    db,
                    config,
                    resolved_plan,
                    assistant_message_id=msg_id,
                    file_ids=payload.file_ids,
                    previous_messages=previous_messages,
                    web_search=web_search,
                    workers_enabled=workers_enabled,
                    thinking_enabled=thinking_enabled,
                    agent_mode=getattr(chat, "agent_mode", "auto") or "auto",
                ):
                    # Stream every orchestrator event live to the Rust sidecar
                    # via stdout. token/tool/done/error drive the existing
                    # frontend streaming UI; thinking_delta drives the
                    # ephemeral reasoning pane. Token events are coalesced;
                    # all others pass straight through.
                    coalescer.feed(event)
                    if sse_coalescer is not None:
                        sse_coalescer.feed(event)
                    if event.type == "phase" and event.payload.get("phase") == "model":
                        # Round boundary: the runtime discards prior-round answer
                        # tokens here (tool round or narration retry). Mirror that
                        # so the persisted reply is only the final round's text.
                        tokens.clear()
                    elif event.type == "token":
                        tokens.append(event.payload.get("text", ""))
                        blocks.add_token(event.payload.get("text", ""))
                    elif event.type == "thinking_delta":
                        # Reasoning used to be streamed and then discarded, so
                        # "what was it thinking about" vanished at done and on
                        # reload. Kept in the block list so it sits in the
                        # cadence where the user watched it happen.
                        blocks.add_thinking(event.payload.get("text", ""))
                    elif event.type == "tool_progress":
                        # Helper-model narration: the headline shown on the card.
                        if event.payload.get("stage") == "narrating":
                            blocks.add_narration(
                                event.payload.get("call_id", ""),
                                event.payload.get("summary", "") or "",
                            )
                    elif event.type == "tool_call":
                        # Any prose the model streamed before calling a tool is a
                        # preamble ("You're right — let me check that directory:"),
                        # not the final answer. The runtime resets its own
                        # all_tokens at each round boundary and treats only the
                        # last round as the answer; mirror that here so the
                        # PERSISTED reply isn't the preamble glued to the answer
                        # ("…correctly:Done! The README…" in the wild). The live
                        # UI still saw every token via the coalescer above.
                        tokens.clear()
                        _pending_calls[event.payload.get("call_id", "")] = {
                            "tool": event.payload.get("tool_name", ""),
                            "arguments": event.payload.get("arguments", {}) or {},
                        }
                        blocks.add_tool_call(
                            event.payload.get("call_id", ""),
                            event.payload.get("tool_name", ""),
                            event.payload.get("arguments", {}) or {},
                        )
                    elif event.type == "tool_result":
                        call = _pending_calls.pop(event.payload.get("call_id", ""), None)
                        captured_tool_events.append(_summarize_tool_event(
                            (call or {}).get("tool", event.payload.get("tool_name", "")),
                            (call or {}).get("arguments", {}),
                            event.payload.get("result", ""),
                        ))
                        blocks.finish_tool(
                            event.payload.get("call_id", ""),
                            event.payload.get("result", ""),
                        )
                    elif event.type == "error":
                        # Per failure_modes.orchestrator_error =
                        # "emit_typed_error_persist_clean_message": the typed
                        # error event has already been streamed to the UI above.
                        # Do NOT raise here — raising would bubble into an HTTP
                        # 503 in the caller, which rolls back the whole request
                        # transaction (including the user's message and chat
                        # row) even though tokens already reached the client.
                        # Return whatever text streamed so far so the turn is
                        # still persisted, with a marker so the caller knows it
                        # ended in error rather than completing normally.
                        return "".join(tokens), event.payload.get("message", "Orchestration error")
            finally:
                # Flush any tail tokens that didn't reach the batch threshold
                # (done/error already flush as boundaries; this is a backstop).
                coalescer.flush()
                if sse_coalescer is not None:
                    sse_coalescer.flush()
            return "".join(tokens), None

        reply_text, error_message = _run(_collect())
        if error_message and not reply_text:
            # No partial content at all — nothing useful to persist as the
            # assistant's reply; surface a clean placeholder instead of an
            # empty message.
            reply_text = f"(No response — {error_message})"
    except Exception as exc:
        # Unexpected failures OUTSIDE the runtime's own typed-error handling
        # (e.g. the runtime itself crashed before it could emit an error
        # event) still need to fail loudly, since no error event reached
        # the UI and no partial turn should be silently persisted as if it
        # succeeded.
        logger.error("Agent orchestration failed: %s", exc)
        # The turn died; any approval it was waiting on is now orphaned. Drop
        # them so the UI doesn't keep showing a live-looking approval card for
        # a turn that no longer exists.
        cancelled = cancel_chat_approvals(chat.id)
        if cancelled:
            logger.info("Cancelled %d pending approval(s) for dead turn on chat %s", cancelled, chat.id)
        raise HTTPException(status_code=503, detail=str(exc))

    return reply_text, msg_id, is_exp0, captured_tool_events, blocks.result()


def _run_fact_extraction(chat_id: str, user_msg_id: str, assistant_msg_id: str):
    """Background thread for fact extraction.

    Opens its own SQLAlchemy session and re-fetches entities by id rather
    than reusing the request-scoped session, which is not thread-safe and
    is closed by the request thread once the response is returned.
    """
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        user_msg = db.get(ChatMessage, user_msg_id)
        assistant_msg = db.get(ChatMessage, assistant_msg_id)
        if user_msg is None or assistant_msg is None:
            logger.warning("Fact extraction skipped: message(s) not found for chat_id=%s", chat_id)
            return
        events = extract_and_reconcile_facts(
            db, user_msg, assistant_msg, source_chat_id=chat_id
        )
        if events:
            logger.info("Memory facts updated: %d events", len(events))
    except Exception as exc:
        logger.warning("Background fact extraction failed: %s", exc)
    finally:
        db.close()
