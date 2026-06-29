"""Request/response models for the HTTP API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# --- settings: model endpoint ----------------------------------------------

class ModelRoles(BaseModel):
    main_reasoner: str = ""
    summarizer: str = ""
    utility: str = ""


class ModelEndpointConfig(BaseModel):
    provider: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(examples=["http://localhost:11434/v1"])
    api_key: str = ""
    models: ModelRoles = Field(default_factory=ModelRoles)


class TestConnectionResult(BaseModel):
    ok: bool
    models: list[str] = []
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# --- settings: app ----------------------------------------------------------

class AppSettingsDTO(BaseModel):
    setup_complete: bool = False
    setup_mode: Literal["managed", "byo"] = "managed"
    theme: Literal["light", "dark", "system"] = "system"
    active_models: list[str] = []


# --- system / hardware ------------------------------------------------------

class GpuInfo(BaseModel):
    name: str
    vram_gb: Optional[float] = None


class HardwareInfo(BaseModel):
    os: str
    cpu: str
    ram_gb: Optional[float] = None
    gpu: list[GpuInfo] = []
    vram_gb: Optional[float] = None
    recommended_profile: Literal["local", "external_endpoint"] = "external_endpoint"


# --- model catalog ----------------------------------------------------------

class CatalogModel(BaseModel):
    id: str
    name: str
    role: str
    size: str
    size_gb: float
    fit: Literal["ok", "warn", "bad"]
    note: str


# --- files ------------------------------------------------------------------

class FileDTO(BaseModel):
    id: str
    filename: str
    content_type: Optional[str] = None
    size_bytes: int
    row_count: Optional[int] = None
    columns: Optional[list[str]] = None
    created_at: str


# --- artifacts --------------------------------------------------------------

class DashboardFromCsvRequest(BaseModel):
    file_id: str
    instruction: Optional[str] = None


class ArtifactResponse(BaseModel):
    artifact_id: str
    artifact: dict[str, Any]


class ExportPdfResponse(BaseModel):
    artifact_id: str
    download_path: str
    filename: str


# --- chat -------------------------------------------------------------------

class ChatRequest(BaseModel):
    chat_id: Optional[str] = None
    message: str = ""
    file_ids: list[str] = []


class ChatMessageDTO(BaseModel):
    id: str
    role: str
    text: str
    artifacts: list[str] = []
    files: list[dict[str, Any]] = []
    created_at: str


class ChatResponse(BaseModel):
    chat_id: str
    message: ChatMessageDTO


class ChatDTO(BaseModel):
    id: str
    title: str
    folder_id: Optional[str] = None
    created_at: str
    updated_at: str


class ChatDetailDTO(ChatDTO):
    messages: list[ChatMessageDTO] = []


class FolderDTO(BaseModel):
    id: str
    name: str
    created_at: str


class CreateFolderRequest(BaseModel):
    name: str = "New folder"


class UpdateFolderRequest(BaseModel):
    name: str


class CreateChatRequest(BaseModel):
    title: str = "New chat"
    folder_id: Optional[str] = None


class UpdateChatRequest(BaseModel):
    title: Optional[str] = None
    folder_id: Optional[str] = None
    unfile: bool = False
