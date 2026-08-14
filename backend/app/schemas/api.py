"""Request/response models for the HTTP API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# --- settings: model endpoint ----------------------------------------------

class ModelRoles(BaseModel):
    orchestrator: str = ""
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
    managed_plan: dict[str, Any] = {}
    workers_enabled: bool = True  # NEW: Worker models toggle
    # Catalog slug that forces the orchestrator model (e.g. "qwen3.5-27b").
    # None/"" = let the hardware resolver pick.
    orchestrator_override: Optional[str] = None


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


# --- managed setup plan -----------------------------------------------------

class ModelRef(BaseModel):
    model: str
    quant: str
    device: str = "gpu"
    ctx_min: Optional[int] = None
    ctx_max: Optional[int] = None


class ManagedPlanResponse(BaseModel):
    path: Literal["apple", "gpu", "cpu_only", "reject"]
    plan_id: Optional[str] = None
    plan_rank: Optional[int] = None
    ctx: Optional[int] = None
    helper_count: int = 0
    fingerprint_hash: str
    runtime_priority: list[str] = []
    runtime_forbidden: list[str] = []
    required_launch_flags: list[str] = []
    recommended_setup_mode: Literal["managed", "byo"] = "managed"
    action: str = ""
    reason: Optional[str] = None
    detection_warnings: list[str] = []
    orchestrator: Optional[ModelRef] = None
    summarizer: Optional[ModelRef] = None
    utility: Optional[ModelRef] = None
    optional_orchestrator: Optional[dict] = None
    validation_stubbed: bool = True


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

# How much latitude the agent has over files in a chat. "auto" is the default
# everywhere so existing chats keep their previous unattended behaviour.
AgentMode = Literal["auto", "manual", "plan"]


class ChatRequest(BaseModel):
    chat_id: Optional[str] = None
    message: str = ""
    file_ids: list[str] = []
    assistant_message_id: Optional[str] = None
    workers_enabled: Optional[bool] = None  # NEW: Per-chat override
    web_search: bool = False
    thinking_enabled: bool = False
    # Codebase project to attach when this request CREATES the chat. Without
    # this, a codebase picked before the first message had nowhere to go (the
    # PATCH /api/chats/{id} route needs a chat that already exists), so the
    # first turn always ran with no codebase access. Ignored when chat_id is
    # given -- an existing chat's codebase is changed via PATCH.
    active_codebase_project_id: Optional[str] = None
    # Same story for the write policy: settable on the request that creates the
    # chat so the very first turn already respects it.
    agent_mode: Optional[AgentMode] = None


class ApprovalDecisionRequest(BaseModel):
    """User's verdict on a suspended write. Only these two values resume a turn."""
    decision: Literal["approve", "reject"]


class ApprovalDecisionResponse(BaseModel):
    approval_id: str
    decision: str
    chat_id: str


class PendingApprovalDTO(BaseModel):
    """A write suspended awaiting approval.

    ``arguments`` is the tool's full argument dict (including old_string /
    new_string for an edit) so the client can render the exact diff.
    """
    approval_id: str
    chat_id: str
    message_id: str
    tool_name: str
    call_id: str
    arguments: dict[str, Any] = {}
    created_at: float


class AnswerQuestionRequest(BaseModel):
    """User's answer to an ask_user question. Blank answers don't resume a turn."""
    answer: str = Field(min_length=1)


class AnswerQuestionResponse(BaseModel):
    question_id: str
    chat_id: str


class PendingQuestionDTO(BaseModel):
    """A question the agent is suspended on, awaiting an answer."""
    question_id: str
    chat_id: str
    message_id: str
    call_id: str
    question: str
    options: list[str] = []
    created_at: float


class ChatMessageDTO(BaseModel):
    id: str
    role: str
    text: str
    artifacts: list[str] = []
    files: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []
    # Ordered render blocks (text runs + tool cards with full args). Empty for
    # messages written before blocks were persisted; the UI falls back to
    # ``text`` in that case.
    blocks: list[dict[str, Any]] = []
    created_at: str


class ChatResponse(BaseModel):
    chat_id: str
    message: ChatMessageDTO
    memory_events: list[dict] = []


class ChatDTO(BaseModel):
    id: str
    title: str
    folder_id: Optional[str] = None
    active_codebase_project_id: Optional[str] = None
    agent_mode: AgentMode = "auto"
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
    active_codebase_project_id: Optional[str] = None
    clear_codebase_project: bool = False
    agent_mode: Optional[AgentMode] = None


# --- memory -------------------------------------------------------------------

class MemoryFactDTO(BaseModel):
    id: str
    fact_text: str
    source_chat_id: Optional[str] = None
    user_locked: bool = False
    created_at: str
    updated_at: str


class MemoryFactCreateRequest(BaseModel):
    fact_text: str = Field(..., min_length=1, max_length=1000)


class MemoryFactUpdateRequest(BaseModel):
    fact_text: str = Field(..., min_length=1, max_length=1000)


# --- custom tools --------------------------------------------------------------

class CustomToolParam(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    required: bool = False
    location: Literal["query", "body"] = "query"
    type: Literal["string", "number", "boolean"] = "string"


class CustomToolDTO(BaseModel):
    id: str
    name: str
    description: str
    base_url: str
    http_method: str
    headers: dict[str, str]
    params: list[CustomToolParam]
    enabled: bool
    created_at: str
    updated_at: str


class CustomToolCreateRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    description: str = Field(..., min_length=1, max_length=1000)
    base_url: str = Field(..., min_length=1)
    http_method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    params: list[CustomToolParam] = Field(default_factory=list)
    enabled: bool = True


class CustomToolUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    description: Optional[str] = Field(None, min_length=1, max_length=1000)
    base_url: Optional[str] = Field(None, min_length=1)
    http_method: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    params: Optional[list[CustomToolParam]] = None
    enabled: Optional[bool] = None


# --- codebase projects ----------------------------------------------------------

class CodebaseAgentDeviceDTO(BaseModel):
    id: str
    device_id: str
    name: str
    approved: bool
    enabled: bool
    connected: bool
    created_at: str
    last_seen_at: str


class CodebaseProjectDTO(BaseModel):
    id: str
    name: str
    device_id: str
    root_path: str
    write_enabled: bool
    enabled: bool
    created_at: str
    updated_at: str


class CodebaseProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    device_id: str = Field(..., min_length=1)
    root_path: str = Field(..., min_length=1)
    write_enabled: bool = False


class CodebaseProjectUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    write_enabled: Optional[bool] = None
    enabled: Optional[bool] = None
