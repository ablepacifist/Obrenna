"""P6 chat routing: intent detection → appropriate artifact builder or model response."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Artifact, Chat, ChatMessage, File, ModelEndpoint
from ..model_runtime.client import chat_completion
from ..model_runtime.config import RuntimeConfig
from ..schemas.api import ChatMessageDTO, ChatRequest, ChatResponse
from ..services import csv_profiler, dashboard_builder, summarize
from ..services.storage import artifact_pdf_path

router = APIRouter(prefix="/api/chat")

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


def _model_reply(text: str, file_records: list, db: Session) -> tuple[str, list[str]]:
    ep = db.get(ModelEndpoint, 1)
    if not ep or not ep.base_url:
        return (
            "I can help analyze your files, but no local model is configured yet. "
            "Go to Settings → Models to connect a local endpoint (Ollama, LM Studio, etc.).",
            [],
        )
    cfg = RuntimeConfig(
        provider=ep.provider,
        base_url=ep.base_url,
        api_key=ep.api_key or "",
        models=ep.models or {},
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": text}])
        return reply, []
    except Exception as exc:
        return f"Model error: {exc}", []


@router.post("", response_model=ChatResponse)
def send_message(payload: ChatRequest, db: Session = Depends(get_db)):
    # Resolve or create chat.
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

    # Resolve file records.
    file_records: list[File] = []
    for fid in payload.file_ids:
        fr = db.get(File, fid)
        if fr:
            file_records.append(fr)

    # Persist user message.
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
    artifact_ids: list[str] = []
    reply_text = ""

    csv_file = next((f for f in file_records if f.filename.lower().endswith(".csv")), None)

    if intent in ("dashboard", "report", "chart", "table", "summary") and csv_file:
        try:
            df = csv_profiler.load_csv(csv_file.stored_path)
            profile = csv_profiler.profile_dataframe(df)

            if intent == "dashboard":
                spec = dashboard_builder.build_dashboard(
                    df, profile, file_id=csv_file.id, filename=csv_file.filename,
                    instruction=payload.message,
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
            artifact_ids = [record.id]
        except Exception as exc:
            reply_text = f"I ran into a problem processing your file: {exc}"
    elif intent in ("summary",) and file_records:
        # Non-CSV summary: extractive.
        fr = file_records[0]
        try:
            with open(fr.stored_path, "r", errors="replace") as fh:
                text_content = fh.read(8000)
            spec = summarize.summarize_text(
                text_content, file_id=fr.id, filename=fr.filename
            )
            record = _save_artifact(spec, db)
            artifact_ids = [record.id]
            reply_text = f"Here's a summary of **{fr.filename}**."
        except Exception as exc:
            reply_text = f"Could not read file: {exc}"
    else:
        reply_text, artifact_ids = _model_reply(payload.message, file_records, db)

    # Persist assistant message.
    asst_msg = ChatMessage(
        id=uuid.uuid4().hex,
        chat_id=chat.id,
        role="assistant",
        text=reply_text,
        artifacts=artifact_ids,
    )
    db.add(asst_msg)

    # Update chat title if first message.
    if not chat.title or chat.title == "New chat":
        chat.title = payload.message[:60]
    chat.updated_at = datetime.now(timezone.utc)

    db.commit()
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
    )
