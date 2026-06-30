"""SQLAlchemy ORM models. Stores file/artifact metadata, settings, chats."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)
    content_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    columns: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    artifact_type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_file_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    spec: Mapped[Any] = mapped_column(JSON)
    pdf_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AppSettings(Base):
    """Singleton row (id=1): app-level setup + appearance state."""

    __tablename__ = "settings_app"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_mode: Mapped[str] = mapped_column(String, default="managed")  # managed | byo
    theme: Mapped[str] = mapped_column(String, default="light")  # light | dark
    active_models: Mapped[Any] = mapped_column(JSON, default=list)
    managed_plan: Mapped[Any] = mapped_column(JSON, default=dict)


class ModelEndpoint(Base):
    """Singleton row (id=1): the configured OpenAI-compatible local endpoint."""

    __tablename__ = "model_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String, default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String)
    api_key: Mapped[str] = mapped_column(String, default="")
    models: Mapped[Any] = mapped_column(JSON, default=dict)


class ProvisionJob(Base):
    """Background model provisioning job started by managed setup confirm."""

    __tablename__ = "provision_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    fingerprint_hash: Mapped[str] = mapped_column(String, index=True)
    runtime_kind: Mapped[str] = mapped_column(String, default="openai_compatible_unknown")
    status: Mapped[str] = mapped_column(String, default="queued")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["ProvisionJobItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ProvisionJobItem(Base):
    """Per-model status row for a provisioning job."""

    __tablename__ = "provision_job_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("provision_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String)
    model_slug: Mapped[str] = mapped_column(String)
    quant: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    bytes_total: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    job: Mapped["ProvisionJob"] = relationship(back_populates="items")


class ProvisionEventLog(Base):
    """Persisted provisioning events for replay/diagnostics."""

    __tablename__ = "provision_event_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("provision_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="New chat")
    folder_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    rolling_summary: Mapped[str] = mapped_column(Text, default="")
    summarized_upto_turn_index: Mapped[int] = mapped_column(Integer, default=-1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )
    turns: Mapped[list["ChatTurn"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)  # user | assistant
    text: Mapped[str] = mapped_column(Text, default="")
    artifacts: Mapped[Any] = mapped_column(JSON, default=list)  # list[artifact_id]
    files: Mapped[Any] = mapped_column(JSON, default=list)  # list[{name,size}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    chat: Mapped["Chat"] = relationship(back_populates="messages")


class ChatTurn(Base):
    """Paired turn archive for memory retrieval and vector indexing."""

    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    user_text: Mapped[str] = mapped_column(Text, default="")
    assistant_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    chat: Mapped["Chat"] = relationship(back_populates="turns")


class MemoryFact(Base):
    """Local user-editable memory facts with tombstone support."""

    __tablename__ = "memory_facts"

    ACCOUNT_ID: str = "local-default"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String, default=ACCOUNT_ID, nullable=False)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_chat_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
