"""P6 chat routing: intent detection → appropriate artifact builder or model response.

Integrates the agent runtime for normal chat while preserving deterministic
artifact generation paths (dashboard, report, chart, table, summary).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..agent.events import (
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
from ..models import AppSettings, Artifact, Chat, ChatMessage, File, ModelEndpoint
from ..model_runtime.client import chat_completion_sync
from ..model_runtime.config import RuntimeConfig
from ..schemas.api import ChatMessageDTO, ChatRequest, ChatResponse
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
    """
    # DEBUG, not INFO: message content is private local content and must not
    # land in default-level logs on a local-first/private-by-default product.
    logger.debug("=== CHAT REQUEST === chat_id=%s message=%r file_ids=%s", payload.chat_id, payload.message, payload.file_ids)
    ep = db.get(ModelEndpoint, 1)
    logger.info("MODEL ENDPOINT: provider=%s base_url=%s api_key_set=%s models=%s", ep.provider if ep else None, ep.base_url if ep else None, bool(ep.api_key) if ep else None, ep.models if ep else None)

    # Resolve or create chat
    if payload.chat_id:
        chat = db.get(Chat, payload.chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found.")
    else:
        chat = Chat(
            id=uuid.uuid4().hex,
            title=payload.message[:60] or "New chat",
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

    intent = _detect_intent(payload.message)
    logger.info("INTENT DETECTED: %s", intent)
    artifact_ids: list[str] = []
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
        reply_text, msg_id, is_exp0 = _handle_normal_chat(db, chat, user_msg, payload,
                                                  assistant_message_id=msg_id,
                                                  web_search=payload.web_search,
                                                  workers_enabled=effective_workers_enabled,
                                                  thinking_enabled=payload.thinking_enabled)

    # DEBUG, not INFO: reply text is private local content.
    logger.debug("CHAT RESPONSE: reply=%r artifact_ids=%s msg_id=%s", reply_text, artifact_ids, msg_id)

    # Persist assistant message
    asst_msg = ChatMessage(
        id=msg_id or uuid.uuid4().hex,
        chat_id=chat.id,
        role="assistant",
        text=reply_text,
        artifacts=artifact_ids,
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
            created_at=asst_msg.created_at.isoformat(),
        ),
        memory_events=memory_events,
    )


router.add_api_route("/artifact", send_message, methods=["POST"], response_model=ChatResponse)


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
) -> tuple[str, str, bool]:
    """Handle normal chat via the agent runtime.

    Returns (reply_text, message_id, is_exp0_plan) — the exp0 flag lets the
    caller skip work the EXP0 tier explicitly forbids (background fact
    extraction / embeddings), matching
    experimental_opt_in_tiers.EXP0.memory_subsystem_override in the catalog.
    """
    msg_id = assistant_message_id or new_message_id()

    # Determine worker setting: per-chat override or global default
    workers_enabled = payload.workers_enabled if payload.workers_enabled is not None else _get_global_workers_setting(db)

    # Get hardware plan and runtime config
    plan_result = _get_hardware_plan(db, workers_enabled=workers_enabled)
    logger.info("HARDWARE PLAN: workers_enabled=%s helper_count=%s", workers_enabled, plan_result.get("helper_count"))
    config = _get_runtime_config(db)
    # Translate catalog slugs to the runtime's actual pull refs before resolving.
    _apply_runtime_model_refs(plan_result, config)
    resolved_plan = build_resolved_plan(plan_result)
    is_exp0 = is_exp0_plan(plan_result)
    logger.info("RUNTIME CONFIG: provider=%s base_url=%s models=%s", config.provider, config.base_url, config.models)
    logger.info("RESOLVED PLAN: orchestrator_model=%s summarizer_model=%s utility_model=%s ctx=%s", resolved_plan.orchestrator_model, resolved_plan.summarizer_model, resolved_plan.utility_model, resolved_plan.ctx)

    # Collect previous messages for context
    from ..models import ChatMessage as CM
    prev_msgs = (
        db.query(CM)
        .filter_by(chat_id=chat.id)
        .order_by(CM.created_at.desc())
        .limit(10)
        .all()
    )
    previous_messages = [
        {"role": m.role, "content": m.text}
        for m in reversed(prev_msgs)
    ]

    # Run agent orchestration synchronously (collect stream)
    from ..model_runtime.client import _run

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
                ):
                    # Stream every orchestrator event live to the Rust sidecar
                    # via stdout. token/tool/done/error drive the existing
                    # frontend streaming UI; thinking_delta drives the
                    # ephemeral reasoning pane. Token events are coalesced;
                    # all others pass straight through.
                    coalescer.feed(event)
                    if event.type == "token":
                        tokens.append(event.payload.get("text", ""))
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
        raise HTTPException(status_code=503, detail=str(exc))

    return reply_text, msg_id, is_exp0


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
