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
from sqlalchemy.orm import Session

from ..agent.events import new_message_id
from ..agent.runtime import (
    build_resolved_plan,
    get_allowed_mcp_tool_names,
    load_architecture_config,
    orchestrate_turn,
)
from ..db import get_db
from ..models import Artifact, Chat, ChatMessage, File, ModelEndpoint
from ..model_runtime.client import chat_completion_sync
from ..model_runtime.config import RuntimeConfig
from ..schemas.api import ChatMessageDTO, ChatRequest, ChatResponse
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


def _get_hardware_plan(db: Session) -> dict:
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
        return {
            "path": "fallback",
            "ctx": 8192,
            "helper_count": 0,
            "orchestrator": {"model": ep.models.get("orchestrator") or ep.models.get("main_reasoner", "")},
            "summarizer": {},
            "utility": {},
        }
    return {
        "path": "fallback",
        "ctx": 8192,
        "helper_count": 0,
        "orchestrator": {"model": ""},
        "summarizer": {},
        "utility": {},
    }


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
    logger.info("=== CHAT REQUEST === chat_id=%s message=%r file_ids=%s", payload.chat_id, payload.message, payload.file_ids)
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

    csv_file = next((f for f in file_records if f.filename.lower().endswith(".csv")), None)

    if intent in ("dashboard", "report", "chart", "table", "summary") and csv_file:
        logger.info("ARTIFACT PATH: intent=%s csv_file=%s", intent, csv_file.filename)
        reply_text, artifact_ids = _handle_artifact_intent(
            intent, csv_file, payload.message, db
        )
    elif intent in ("summary",) and file_records:
        logger.info("TEXT SUMMARY PATH: files=%s", [f.filename for f in file_records])
        reply_text, artifact_ids = _handle_text_summary(file_records, db)
    else:
        logger.info("NORMAL CHAT PATH: delegating to agent runtime")
        # Normal chat — use agent runtime
        reply_text, msg_id = _handle_normal_chat(db, chat, user_msg, payload)

    logger.info("CHAT RESPONSE: reply=%r artifact_ids=%s msg_id=%s", reply_text, artifact_ids, 'msg_id' in dir())

    # Persist assistant message
    asst_msg = ChatMessage(
        id=msg_id if 'msg_id' in dir() else uuid.uuid4().hex,
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

    # Record turn and build memory events
    memory_events: list[dict] = []
    try:
        turn_id = record_turn_after_response(db, chat, user_msg, asst_msg)
        if turn_id:
            active_facts = get_active_facts(db)
            memory_events = [{"type": "MEMORY_ACTIVE", "count": len(active_facts)}]
    except Exception as exc:
        logger.warning("Turn recording failed: %s", exc)

    # Dispatch fact extraction in background
    try:
        t = threading.Thread(
            target=_run_fact_extraction,
            args=(db, chat, user_msg, asst_msg),
            daemon=True,
        )
        t.start()
    except Exception as exc:
        logger.warning("Failed to start fact extraction: %s", exc)

    # Commit
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Chat commit failed: %s", exc)

    db.refresh(asst_msg)

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
    intent: str, csv_file: File, message: str, db: Session
) -> tuple[str, list[str]]:
    """Handle deterministic artifact generation."""
    try:
        df = csv_profiler.load_csv(csv_file.stored_path)
        profile = csv_profiler.profile_dataframe(df)

        if intent == "dashboard":
            spec = dashboard_builder.build_dashboard(
                df, profile, file_id=csv_file.id, filename=csv_file.filename,
                instruction=message,
            )
            reply_text = f"Here's your dashboard for **{csv_file.filename}**."
        elif intent == "report":
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
            spec = summarize.summarize_csv(
                profile, file_id=csv_file.id, filename=csv_file.filename
            )
            reply_text = f"Here's a summary of **{csv_file.filename}**."

        record = _save_artifact(spec, db)
        return reply_text, [record.id]
    except Exception as exc:
        return f"I ran into a problem processing your file: {exc}", []


def _handle_text_summary(file_records: list[File], db: Session) -> tuple[str, list[str]]:
    """Handle non-CSV summary (extractive)."""
    fr = file_records[0]
    try:
        with open(fr.stored_path, "r", errors="replace") as fh:
            text_content = fh.read(8000)
        spec = summarize.summarize_text(
            text_content, file_id=fr.id, filename=fr.filename
        )
        record = _save_artifact(spec, db)
        return f"Here's a summary of **{fr.filename}**.", [record.id]
    except Exception as exc:
        return f"Could not read file: {exc}", []


def _handle_normal_chat(
    db: Session,
    chat: Chat,
    user_msg: ChatMessage,
    payload: ChatRequest,
) -> tuple[str, str]:
    """Handle normal chat via the agent runtime."""
    msg_id = new_message_id()

    # Get hardware plan and runtime config
    plan_result = _get_hardware_plan(db)
    logger.info("HARDWARE PLAN: %s", plan_result)
    config = _get_runtime_config(db)
    # Translate catalog slugs to the runtime's actual pull refs before resolving.
    _apply_runtime_model_refs(plan_result, config)
    resolved_plan = build_resolved_plan(plan_result)
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
            async for event in orchestrate_turn(
                payload.message,
                chat.id,
                db,
                config,
                resolved_plan,
                assistant_message_id=msg_id,
                previous_messages=previous_messages,
            ):
                if event.type == "token":
                    tokens.append(event.payload.get("text", ""))
                elif event.type == "error":
                    raise RuntimeError(event.payload.get("message", "Orchestration error"))
            return "".join(tokens)

        reply_text = _run(_collect())
    except Exception as exc:
        logger.error("Agent orchestration failed: %s", exc)
        reply_text = f"Model error: {exc}"

    return reply_text, msg_id


def _run_fact_extraction(
    db: Session,
    chat: Chat,
    user_msg: ChatMessage,
    assistant_msg: ChatMessage,
):
    """Background thread for fact extraction."""
    try:
        events = extract_and_reconcile_facts(
            db, user_msg, assistant_msg, source_chat_id=chat.id
        )
        if events:
            logger.info("Memory facts updated: %d events", len(events))
    except Exception as exc:
        logger.warning("Background fact extraction failed: %s", exc)
