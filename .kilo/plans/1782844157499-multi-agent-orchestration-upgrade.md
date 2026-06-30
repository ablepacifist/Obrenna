# Obrenna Multi-Agent Orchestration Architecture Upgrade

## Overview

Evolve the current single-turn orchestrator → workers → summarizer pipeline into a production-grade multi-agent system with: turn routing, typed workers, structured evidence, multi-round tool loops, MCP permission/reviewer layer, LLM-planned artifacts, durable state/checkpointing, local tracing, model capability registry, and evals.

**Goal:** Replace the blunt `workers_enabled` switch with intelligent routing, make workers return validated JSON, pass structured evidence to the orchestrator, allow multi-round tool use, add safety gates on MCP tools, separate artifact planning from chat, and make the entire system observable and testable.

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Turn router approach | Heuristic + keyword first, LLM fallback | Fast path for obvious cases (artifact keywords, file type analysis), LLM only for ambiguous |
| Worker output validation | Pydantic models + JSON repair retry | Strict schema enforcement with graceful degradation for local models that produce malformed JSON |
| TurnState persistence | Durable from start (SQLite checkpoints + JSONL event logs) | Enables recovery, debugging, and future human-in-loop support |
| Artifact generation | Extend existing: keep keyword paths + add ArtifactPlanner | Preserve working deterministic builders, add LLM-planned path for custom artifacts |
| Trace format | JSONL per-turn files + SQLite index | Lightweight, queryable, no external dependencies |
| MCP Reviewer scope | Tiered approval (safe_read=auto, rest=prompt) + full injection/SSRF checks | Balance developer friction with security |
| EvidencePack | Structured dataclass, not string | Preserve raw worker outputs + citations, pass compact string to model |
| Tool loop | Multi-round, no forced "no tools" after round 1 | Real orchestrators need 2-3 tool rounds for complex queries |

## Affected Code

### New Files to Create

| File | Purpose |
|---|---|
| `backend/app/agent/router.py` | Turn router: heuristic classification + LLM fallback |
| `backend/app/agent/typed_workers.py` | Typed worker schemas, Pydantic models, worker role registry |
| `backend/app/agent/evidence.py` | Structured EvidencePack dataclass (replaces string in workers.py) |
| `backend/app/agent/graph_state.py` | TurnState, checkpointing, SQLite persistence |
| `backend/app/agent/reviewer.py` | ToolCallReviewer: permission tiers, injection detection, SSRF checks |
| `backend/app/agent/artifact_planner.py` | ArtifactPlanner: LLM-driven artifact spec generation |
| `backend/app/agent/model_registry.py` | ModelCapabilityRegistry: per-model metadata |
| `backend/app/services/trace_store.py` | JSONL trace writer + SQLite query index |
| `backend/app/agent/evals.py` | Eval runner + scoring harness |
| `backend/tests/test_router.py` | Router unit tests |
| `backend/tests/test_typed_workers.py` | Typed worker tests |
| `backend/tests/test_evidence.py` | EvidencePack tests |
| `backend/tests/test_graph_state.py` | TurnState persistence tests |
| `backend/tests/test_reviewer.py` | Tool reviewer tests |
| `backend/tests/test_artifact_planner.py` | Artifact planner tests |
| `backend/tests/test_model_registry.py` | Model registry tests |
| `backend/tests/test_trace_store.py` | Trace store tests |
| `backend/tests/test_evals.py` | Eval suite tests |

### Files to Modify

| File | Changes |
|---|---|
| `backend/app/agent/runtime.py` | Wire router, typed workers, structured evidence, improved tool loop, conditional summarizer |
| `backend/app/agent/events.py` | Add `artifact_plan` event type (Phase 1, T4) |
| `backend/app/agent/workers.py` | Integrate typed workers + structured EvidencePack, conditional summarizer logic |
| `backend/app/routers/chat.py` | Wire TurnState checkpointing, trace emission, web_search setting pass-through |
| `backend/app/models.py` | Add `TraceEntry` model, update `Artifact` with planner fields |
| `backend/app/mcp/client.py` | Add reviewer integration point |
| `backend/app/mcp/tools.py` | Add `artifact_create` tool definition |
| `backend/app/services/architecture_config.py` | Add router config, reviewer config, model registry, summarizer threshold sections |
| `backend/app/main.py` | Initialize trace store + model registry at startup |

---

## Task List (Ordered)

### Phase 1: Foundation (No Dependencies)

#### T1: TurnState + Durable Checkpointing

Create `backend/app/agent/graph_state.py`.

**Data Model:**

```python
# backend/app/agent/graph_state.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass(slots=True)
class TurnState:
    turn_id: str
    chat_id: str
    user_message: str
    route: str = ""                    # direct_answer, web_research, data_analysis, etc.
    resolved_plan: dict = field(default_factory=dict)
    memory_context: list[dict] = field(default_factory=list)
    worker_tasks: list[dict] = field(default_factory=list)
    worker_results: list[dict] = field(default_factory=list)
    evidence_pack: dict = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    artifact_plan: dict = field(default_factory=dict)
    final_response: str = ""
    traces: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class TurnStateManager:
    """SQLite-backed checkpoint persistence for TurnState."""

    def create(self, chat_id: str, user_message: str) -> TurnState
    """Create a new TurnState with a unique turn_id, persist to SQLite."""

    def checkpoint(self, state: TurnState) -> None
    """Save TurnState to SQLite (upsert by turn_id)."""

    def load(self, turn_id: str) -> TurnState | None
    """Load TurnState by turn_id from SQLite."""

    def load_by_chat(self, chat_id: str) -> list[str]
    """Return list of turn_ids for a chat, ordered by created_at desc."""
```

**Persistence:**
- SQLite table `turn_states` with columns: `turn_id`, `chat_id`, `state_json` (TEXT), `created_at`, `updated_at`.
- JSONL event log in `<data_dir>/traces/` — one `.jsonl` file per turn, each line is an event envelope.

**Integration point:** `runtime.py:orchestrate_turn()` calls `create()` at start, `checkpoint()` at each stage boundary.

#### T2: Model Capability Registry

Create `backend/app/agent/model_registry.py`.

**Data Model:**

```python
# backend/app/agent/model_registry.py

@dataclass(slots=True)
class ModelCapability:
    model: str
    role_fit: list[str]           # ["orchestrator", "writer", "summarizer"]
    tool_calling: str             # "excellent" | "good" | "fair" | "poor"
    json_reliability: str         # "excellent" | "good" | "fair" | "poor"
    ctx_len: int
    tokens_per_second: float
    memory_gb: float
    best_quant: str
    known_failures: list[str]     # ["occasionally malformed tool args"]
```

**API:**

```python
class ModelCapabilityRegistry:
    def __init__(self, catalog_path: Path | None = None)
    """Load from catalog or fall back to built-in defaults."""

    def register(self, model: str, caps: ModelCapability) -> None
    """Register model capabilities (can be loaded from config)."""

    def get(self, model: str) -> ModelCapability | None
    """Look up capabilities for a model slug."""

    def best_for_role(self, role: str, models: list[str]) -> str | None
    """Return the best model for a role from a list, by tool_calling + json_reliability."""

    def requires_json_repair(self, model: str) -> bool
    """Check if this model needs JSON repair retry on structured outputs."""
```

**Config:** `architecture_config.json` → `model_registry` section:

```json
{
  "model_registry": {
    "models": {
      "qwen3.5-9b": {
        "role_fit": ["orchestrator", "writer"],
        "tool_calling": "good",
        "json_reliability": "fair",
        "ctx_len": 32768,
        "tokens_per_second": 32,
        "memory_gb": 8.5,
        "best_quant": "Q4_K_M",
        "known_failures": ["occasionally malformed tool args"]
      },
      "granite4.0-h-micro-3b": {
        "role_fit": ["summarizer"],
        "tool_calling": "poor",
        "json_reliability": "good",
        "ctx_len": 8192,
        "tokens_per_second": 80,
        "memory_gb": 3.2,
        "best_quant": "Q5_K_M",
        "known_failures": []
      }
    }
  }
}
```

**Integration point:** `runtime.py:orchestrate_turn()` queries `requires_json_repair()` to enable repair on orchestrator responses.

#### T3: Trace Store

Create `backend/app/services/trace_store.py`.

**Storage:**
- JSONL event log: `<data_dir>/traces/<turn_id>.jsonl` — one event per line.
- SQLite index: `<data_dir>/traces.db` — table `trace_index` with columns: `turn_id`, `chat_id`, `route`, `models_used` (JSON), `worker_count`, `tool_call_count`, `latency_ms` (JSON), `tokens_used` (JSON), `error_count`, `artifact_generated`, `created_at`.

**API:**

```python
class TraceStore:
    def begin(self, turn_id: str, chat_id: str, route: str) -> str
    """Open a trace session, return session_id."""

    def record(self, session_id: str, event_type: str, data: dict) -> None
    """Record a trace event (e.g., 'worker_dispatched', 'tool_called', 'token_count')."""

    def complete(self, session_id: str, final_data: dict) -> None
    """Close trace, write to SQLite index."""

    def query(self, chat_id: str, limit: int = 50) -> list[dict]
    """Query trace index by chat_id."""
```

**Event types:** `turn_start`, `route_decided`, `workers_dispatched`, `worker_done`, `summarizer_done`, `tool_called`, `tool_result`, `artifact_generated`, `turn_complete`, `turn_error`.

---

### Phase 2: Routing + Typed Workers

#### T4: Turn Router

Create `backend/app/agent/router.py`.

**Routes:** `direct_answer`, `local_file_question`, `web_research`, `data_analysis`, `artifact_generation`, `tool_action`, `ambiguous`.

**Algorithm:**

```
classify_turn(user_message: str, file_ids: list[str] | None, settings: dict) -> RouterResult
```

1. **Heuristic pass** (fast, no LLM):
   - Check `file_ids` for `.csv` → `data_analysis`
   - Check `file_ids` for text files → `local_file_question`
   - Check message for artifact keywords (`dashboard`, `report`, `chart`, `table`, `summary`) → `artifact_generation`
   - Check message for tool keywords (`calculate`, `search`, `what time`, `where am i`) → `tool_action`
   - Check if message is short/simple (no complex entities) → `direct_answer`

2. **LLM fallback** (only if heuristic doesn't classify):
   - Single fast call to `utility_model` at `temperature=0.1`
   - Prompt: "Classify this turn: {options}. Message: {user_message}. Return JSON: {route, confidence, needs_workers}"
   - If LLM confidence < 0.6 → `ambiguous`

3. **RouterResult** includes:
    ```python
    @dataclass
    class RouterResult:
        route: str
        confidence: float          # 0.0-1.0
        needs_workers: bool        # True only for: local_file_question, web_research, data_analysis
        worker_policy: dict        # {max_workers, timeout, allowed_types}
        budget_tokens: int         # context budget for this route
        files_required: bool       # whether this route needs file context
        requires_network: bool     # True only for: web_research
    ```

**User setting override — never let router override explicit user settings:**

If `web_search=false` (from `ChatRequest.web_search` or `AppSettings`):
- Router may classify the task as `web_research` with `requires_network: true`
- Runtime must **not** perform network calls
- Runtime falls back to local context only or explains the limitation to the user
- `RouterResult.network_allowed` is set to `false`, `reason` explains why

If `web_search=true`:
- Router may choose whether network is actually needed per route
- `RouterResult.network_allowed` is `true` only if the route requires it

```python
@dataclass
class RouterResult:
    route: str
    confidence: float
    needs_workers: bool
    worker_policy: dict
    budget_tokens: int
    files_required: bool
    requires_network: bool
    network_allowed: bool = True     # controlled by user setting, not router
    network_reason: str = ""         # e.g. "User disabled web search"
```

**Worker policy mapping:**

| Route | Workers | Policy |
|---|---|---|
| `direct_answer` | No | — |
| `local_file_question` | Yes (2-4) | ContextExtractWorker, SourceRankWorker |
| `web_research` | Yes (1-2) | WebSearchWorker (via MCP), CitationWorker |
| `data_analysis` | Yes (1-2) | TableProfileWorker, DataCleanWorker |
| `artifact_generation` | No | — (handled by ArtifactPlanner) |
| `tool_action` | No | — (handled by tool loop) |
| `ambiguous` | Yes (1) | ContextExtractWorker (conservative) |

**Integration point:** `runtime.py:orchestrate_turn()` calls `classify_turn()` before memory assembly and worker dispatch. Pass `web_search` setting from `ChatRequest` as parameter.

**Side note — add `artifact_plan` event type here (T4):**

While creating the router, also add the `artifact_plan` event type to `backend/app/agent/events.py`. This is Phase 1 so the Tauri/Rust stream parser can accept and preserve the event early:

```python
# backend/app/agent/events.py additions

EVENT_TYPE_ARTIFACT_PLAN = "artifact_plan"
VALID_EVENT_TYPES = (
    EVENT_TYPE_TOKEN, EVENT_TYPE_DONE, EVENT_TYPE_ERROR,
    EVENT_TYPE_TOOL_CALL, EVENT_TYPE_TOOL_RESULT, EVENT_TYPE_TOOL_PROGRESS,
    EVENT_TYPE_ARTIFACT_PLAN,  # NEW — Phase 1, T4
)

@dataclass(slots=True)
class ArtifactPlanEvent:
    chat_id: str
    message_id: str = ""
    artifact_type: str = ""
    artifact_id: str = ""
    title: str = ""

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": EVENT_TYPE_ARTIFACT_PLAN,
            "payload": {
                "artifact_type": self.artifact_type,
                "artifact_id": self.artifact_id,
                "title": self.title,
            },
        }

def artifact_plan_event(chat_id, artifact_type, artifact_id, title="", message_id="") -> StreamEvent:
    return StreamEvent(
        chat_id=chat_id, message_id=message_id,
        type=EVENT_TYPE_ARTIFACT_PLAN,
        payload={"artifact_type": artifact_type, "artifact_id": artifact_id, "title": title},
    )
```

Tauri parser behavior: recognize `artifact_plan` event, log it or store it, do not render. UI rendering is deferred to Phase 4.

#### T5: Typed Worker Schemas

Create `backend/app/agent/typed_workers.py`.

**Worker Types & Output Schemas:**

```python
# backend/app/agent/typed_workers.py

from pydantic import BaseModel, Field
from typing import Literal

class Claim(BaseModel):
    claim: str
    source_ref: str | None = None
    confidence: Literal["low", "medium", "high"] = "medium"

class SourceRef(BaseModel):
    source: str
    url: str | None = None
    relevance: float = 0.0

class Entity(BaseModel):
    name: str
    type: Literal["person", "organization", "location", "date", "number", "file", "other"]
    context: str | None = None

class TableSummary(BaseModel):
    columns: list[str]
    row_count: int
    key_findings: list[str] = []
    data_quality: Literal["good", "fair", "poor"] = "good"

class Contradiction(BaseModel):
    claim_a: str
    claim_b: str
    resolution: str | None = None

class WorkerOutput(BaseModel):
    worker_type: str
    claims: list[Claim] = []
    sources: list[SourceRef] = []
    entities: list[Entity] = []
    tables: list[TableSummary] = []
    contradictions: list[Contradiction] = []
    missing_info: list[str] = []
    confidence: Literal["low", "medium", "high"] = "medium"
    recommended_next_steps: list[str] = []
```

**Worker Registry:**

```python
WORKER_REGISTRY: dict[str, dict] = {
    "context_extract": {
        "model_role": "utility",
        "system_prompt": "Extract key entities...",
        "temperature": 0.1,
    },
    "source_rank": {
        "model_role": "utility",
        "system_prompt": "Rank sources by reliability...",
        "temperature": 0.1,
    },
    "citation": {
        "model_role": "utility",
        "system_prompt": "Verify citations...",
        "temperature": 0.1,
    },
    "table_profile": {
        "model_role": "utility",
        "system_prompt": "Profile CSV table...",
        "temperature": 0.1,
    },
    "data_clean": {
        "model_role": "utility",
        "system_prompt": "Identify data quality issues...",
        "temperature": 0.1,
    },
    "schema_repair": {
        "model_role": "utility",
        "system_prompt": "Repair malformed JSON/schema...",
        "temperature": 0.1,
    },
}
```

**Dispatch with validation:**

```python
async def dispatch_typed_worker(
    task: dict,
    config: RuntimeConfig,
    worker_type: str,
    output_schema: type[WorkerOutput] = WorkerOutput,
) -> TypedWorkerResult:
    """Execute worker, parse output through Pydantic, retry with repair on failure."""
    # 1. Execute worker (same as current, via chat_completion_stream)
    raw_output = await _execute_worker(...)

    # 2. Parse through Pydantic
    try:
        parsed = output_schema.model_validate_json(raw_output)
        return TypedWorkerResult(status="success", output=parsed, raw=raw_output)
    except ValidationError:
        # 3. Try JSON repair (extract JSON from messy output)
        repaired = _repair_json(raw_output)
        try:
            parsed = output_schema.model_validate(repaired)
            return TypedWorkerResult(status="success", output=parsed, raw=raw_output, repaired=True)
        except ValidationError:
            return TypedWorkerResult(status="invalid_output", error="Schema validation failed")
```

**JSON repair strategy:**
1. Find first `[` or `{` and last `]` or `}`
2. Strip markdown code fences (```)
3. Strip leading/trailing whitespace and text before first bracket
4. Try `json.loads()`
5. If still failing, return raw string (will be marked as invalid)

**Integration point:** Replace `_prepare_worker_tasks()` in `runtime.py` with typed task generation. Replace `dispatch_workers()` in `workers.py` with `dispatch_typed_worker()`.

#### T6: Structured EvidencePack + Conditional Summarizer

Create `backend/app/agent/evidence.py`.

```python
# backend/app/agent/evidence.py

from pydantic import BaseModel, Field
from .typed_workers import WorkerOutput

class EvidencePack(BaseModel):
    task_id: str
    user_intent: str
    claims: list[Claim] = []
    source_refs: list[SourceRef] = []
    extracted_entities: list[Entity] = []
    tables: list[TableSummary] = []
    contradictions: list[Contradiction] = []
    missing_info: list[str] = []
    artifact_inputs: dict = field(default_factory=dict)
    compact_summary: str = ""
    worker_outputs: list[WorkerOutput] = []  # raw typed outputs, kept in state but not passed to model
    failure_count: int = 0
    token_estimate: int = 0                 # estimated token count of worker outputs

    def to_compact_string(self) -> str:
        """Format for model consumption — same as current compact string."""
        ...  # reuse workers.py EvidencePack.to_compact_string() logic

    def to_artifact_inputs(self) -> dict:
        """Extract structured data the ArtifactPlanner can use."""
        return {
            "claims": [c.model_dump() for c in self.claims],
            "entities": [e.model_dump() for e in self.extracted_entities],
            "tables": [t.model_dump() for t in self.tables],
            "missing_info": self.missing_info,
        }

    def estimate_tokens(self) -> int:
        """Rough token estimate: ~4 chars per token, sum all fields."""
        raw = self.to_compact_string()
        return len(raw) // 4
```

**Summarizer is kept but made conditional.**

The summarizer only runs when evidence is large enough that passing it raw would exceed the orchestrator's context budget or when artifact synthesis benefits from compression:

```python
# In runtime.py orchestrate_turn(), after workers complete:

SUMMARIZER_THRESHOLD_TOKENS = 4096  # configurable via architecture_config

if evidence_pack.token_estimate > SUMMARIZER_THRESHOLD_TOKENS:
    # Summarizer creates a compressed view for the orchestrator
    summary_text, success = await summarize_into_evidence_pack(
        config, resolved_plan.summarizer_model, evidence_pack,
    )
    if success:
        evidence_pack.compact_summary = summary_text
    else:
        # Summarizer failed — fall back to compact string (no hard abort)
        evidence_pack.compact_summary = evidence_pack.to_compact_string()
        logger.warning("Summarizer failed, using raw compact string")
else:
    # Evidence is small enough — no summarizer needed
    evidence_pack.compact_summary = evidence_pack.to_compact_string()
```

**Key rules:**
- Structured `EvidencePack` is the source of truth — always kept in `TurnState`.
- The summarizer creates a model-facing `compact_summary` only when needed.
- If summarizer fails, fall back to raw compact string (not a hard abort — evidence pack is still structured and complete).
- The `worker_outputs` list is kept in `TurnState` for artifact planning and tracing, but not passed to the orchestrator.

**Integration point:** `runtime.py` replaces string `evidence_summary` with `EvidencePack` instance. Pass `evidence_pack.compact_summary` to orchestrator, keep `worker_outputs` attached for artifact planning.

---

### Phase 3: Tool Loop + Reviewer

#### T7: Improved Multi-Round Tool Loop

Modify `backend/app/agent/runtime.py` — replace the tool loop in `orchestrate_turn()`.

**Current flow (problematic):**
```python
# After first tool call round, model_tools is set to None
# This prevents the orchestrator from making additional tool calls
if detected_tool_calls:
    model_tools = None
    continue
```

**New flow:**

```python
# Stateful tool tracking
seen_tool_names: set[str] = set()
tool_result_cache: dict[str, str] = {}
duplicate_guard = 0

while tool_round < max_tool_rounds:
    tool_round += 1
    detected_tool_calls = []

    async for event in chat_completion_stream(
        config, orchestrator_messages,
        model=resolved_plan.orchestrator_model,
        role="orchestrator",
        temperature=0.2,
        tools=model_tools,  # ALWAYS pass tools (don't set to None after round 1)
    ):
        if event.get("type") == "tool_calls_done":
            calls = event.get("calls", [])

            # Guard: check for duplicate tool calls
            new_calls = [c for c in calls if c.get("id") not in tool_result_cache]
            if not new_calls:
                duplicate_guard += 1
                if duplicate_guard >= 2:
                    logger.warning("Max duplicate tool calls reached — forcing final response")
                    break
            else:
                duplicate_guard = 0

            # Execute only new calls
            tool_results = await handle_tool_calls(new_calls, mcp_client)
            for call, result in zip(new_calls, tool_results):
                tool_result_cache[call["id"]] = result
                orchestrator_messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                })

            break  # Re-call model with tool results

    # If no tool calls and no tokens, break
    if not detected_tool_calls and not all_tokens:
        break
```

**Additional guards:**
- **Max tokens:** Check accumulated tokens against `resolved_plan.ctx` — yield error if approaching limit.
- **Wall-clock timeout:** Wrap entire orchestration in `asyncio.wait_for(..., timeout=total_timeout)` where `total_timeout = max_tool_rounds * stream_timeout`.
- **Tool error repair:** If a tool call returns an error, append `"Tool returned error: {error}. Try again with corrected arguments."` to the messages for that tool.

#### T8: MCP Tool Reviewer

Create `backend/app/agent/reviewer.py`.

**Permission Tiers:**

```python
# Permission tiers
PERMISSION_TIERS = {
    # tier: (auto_execute, require_user_approval, log_to_audit)
    "safe_read":      (True,  False, True),   # get_time, calculator
    "local_read":     (True,  False, True),   # file_read (allowlisted paths)
    "local_write":    (False, True,  True),   # file_write
    "network":        (False, True,  True),   # web_search (configurable toggle)
    "delete":         (False, True,  True),   # future: file_delete
    "shell":          (False, True,  True),   # future: shell_exec (sandbox only)
}
```

**Tool-to-tier mapping (configurable in `architecture_config.json`):**

```json
{
  "reviewer": {
    "tier_map": {
      "get_time": "safe_read",
      "calculator": "safe_read",
      "file_read": "local_read",
      "file_write": "local_write",
      "web_search": "network",
      "get_location": "network"
    }
  }
}
```

**Reviewer API:**

```python
@dataclass
class ReviewResult:
    approved: bool
    tier: str
    requires_approval: bool
    rejection_reason: str = ""
    sanitized_args: dict = field(default_factory=dict)

class ToolCallReviewer:
    def review(self, tool_name: str, args: dict, context: dict) -> ReviewResult:
        """
        Check tool call against:
        1. Is tool in allowed list?
        2. What permission tier does it belong to?
        3. Does argument path escape sandbox?
        4. Does tool description contain suspicious instructions?
        5. Does this require user approval?
        """

    def check_path_safety(self, path_arg: str) -> bool:
        """Check if a file path argument is within sandbox."""

    def detect_prompt_injection(self, tool_name: str, args: dict) -> bool:
        """Detect prompt injection patterns in tool arguments."""
        # Check for: nested JSON injection, escape sequences, instruction overrides
        patterns = [
            r'(?i)(system|prompt|instruction)\s*[=:]\s*"',
            r'(?i)(ignore|bypass|override|disregard)\s+previous',
            r'```(?:python|json|javascript)',  # code fence injection
        ]
        combined = json.dumps(args) + " " + tool_name
        return any(re.search(p, combined) for p in patterns)

    def detect_ssrf(self, args: dict) -> bool:
        """Detect SSRF patterns in tool arguments."""
        url_patterns = [
            r'https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0)',
            r'https?://(?:169\.254\.169\.254)',  # AWS metadata
        ]
        combined = json.dumps(args)
        return any(re.search(p, combined) for p in url_patterns)
```

**Integration point:** `runtime.py:handle_tool_calls()` calls `reviewer.review()` before each tool call. Rejected calls yield `"Tool call rejected: {reason}"` as the tool result.

**Integration point:** `mcp/client.py` — add `reviewer` parameter to `MCPClient`, call before `call_tool()`.

---

### Phase 4: Artifact System

#### T9: ArtifactPlanner

Create `backend/app/agent/artifact_planner.py`.

**Concept:** The orchestrator can emit an `ArtifactPlan` in its final response instead of plain text. The `ArtifactPlanner` validates and normalizes this plan before the renderer processes it.

**ArtifactPlan schema (Pydantic):**

```python
# backend/app/agent/artifact_planner.py

class ArtifactPlan(BaseModel):
    artifact_type: Literal["dashboard", "report", "chart", "table", "document"]
    title: str
    summary: str | None = None
    source_file_id: str | None = None

    # Dashboard-specific
    cards: list[Card] = []
    charts: list[Chart] = []
    tables: list[Table] = []
    insights: list[str] = []

    # Report-specific
    sections: list[ReportSection] = []

    # Chart-specific
    chart: Chart | None = None

    # Table-specific
    table: Table | None = None

    # Document-specific
    markdown: str | None = None
```

**Planner flow:**

```python
async def plan_artifact(
    orchestrator_response: str,
    evidence_pack: EvidencePack,
    artifact_type_hint: str | None = None,
) -> tuple[ArtifactPlan | None, str]:
    """
    Try to extract/plan an artifact from the orchestrator's final response.

    Returns:
        (ArtifactPlan, fallback_text) — if planning succeeds, fallback_text is empty.
        If planning fails, returns (None, orchestrator_response) — fall back to plain text.
    """
    # 1. Try structured extraction from response
    plan = _extract_artifact_plan(orchestrator_response, artifact_type_hint)

    # 2. Validate against schema
    if plan:
        try:
            validated = ArtifactPlan.model_validate(plan)
            return validated, ""
        except ValidationError:
            logger.warning("Artifact plan validation failed, trying repair")

    # 3. JSON repair retry (for local models that produce malformed JSON)
    if registry.requires_json_repair(orchestrator_model):
        repaired = _repair_json(orchestrator_response)
        try:
            validated = ArtifactPlan.model_validate(repaired)
            return validated, ""
        except ValidationError:
            pass

    # 4. Fallback: no artifact, return plain text
    return None, orchestrator_response
```

**Integration point:**
- `runtime.py:orchestrate_turn()` — after orchestrator final response, check if it contains artifact intent. If yes, call `plan_artifact()`.
- `runtime.py` — emit `artifact_plan` event when plan is created.
- `routers/chat.py` — after receiving plan, save artifact via existing `_save_artifact_to_db()` or new `ArtifactEngine`.

**Integration with existing system:** The existing deterministic artifact routes (`_handle_artifact_intent()`) remain untouched. They continue to match keywords → CSV → deterministic builder. The new `ArtifactPlanner` is an **additional** path: LLM plans artifact → validates → renderer.

---

### Phase 5: Integration + Observability

#### T10: Wire Everything in `runtime.py`

Modify `backend/app/agent/runtime.py:orchestrate_turn()`.

**New flow:**

```python
async def orchestrate_turn(
    user_message, chat_id, db, config, resolved_plan,
    *,
    file_ids=None,
    previous_messages=None,
    web_search=False,      # NEW: from ChatRequest
    workers_enabled=True,
):
    # 0. Create TurnState checkpoint
    state = graph_manager.create(chat_id, user_message)
    trace_session = trace_store.begin(state.turn_id, chat_id, "unknown")

    # 1. Classify turn (ROUTER)
    router_result = classify_turn(user_message, file_ids, web_search=web_search, workers_enabled=workers_enabled)
    state.route = router_result.route
    graph_manager.checkpoint(state)
    trace_store.record(trace_session, "route_decided", {"route": state.route, "confidence": router_result.confidence})

    # 2. Assemble memory context
    memory_ctx = assemble_context(db, chat, user_message)
    state.memory_context = memory_ctx.to_messages()
    graph_manager.checkpoint(state)

    # 3. Worker dispatch (only if router says yes AND workers enabled)
    if router_result.needs_workers and workers_enabled:
        worker_tasks = _prepare_typed_worker_tasks(user_message, state)
        state.worker_tasks = worker_tasks
        worker_results = await dispatch_typed_workers(worker_tasks, ...)
        state.worker_results = [wr.model_dump() for wr in worker_results]
        trace_store.record(trace_session, "workers_dispatched", {"count": len(worker_results)})

        # 4. Build structured EvidencePack
        evidence_pack = build_evidence_pack(worker_results, user_message)
        state.evidence_pack = evidence_pack.model_dump()

        # 5. Conditional summarizer — only if evidence is too large
        threshold = get_summarizer_threshold()  # from architecture_config
        if evidence_pack.token_estimate > threshold:
            summary_text, success = await summarize_into_evidence_pack(
                config, resolved_plan.summarizer_model, evidence_pack,
            )
            if success:
                evidence_pack.compact_summary = summary_text
                trace_store.record(trace_session, "summarizer_used", {"threshold_exceeded": True})
            else:
                # Summarizer failed — fall back to raw compact string (no hard abort)
                evidence_pack.compact_summary = evidence_pack.to_compact_string()
                logger.warning("Summarizer failed, using raw compact string")
                trace_store.record(trace_session, "summarizer_failed", {})
        else:
            evidence_pack.compact_summary = evidence_pack.to_compact_string()
            trace_store.record(trace_session, "summarizer_skipped", {"reason": "below threshold"})

        graph_manager.checkpoint(state)
    else:
        evidence_pack = EvidencePack(task_id=state.turn_id, user_intent=user_message)
        evidence_pack.compact_summary = ""

    # 5. Build orchestrator messages
    orchestrator_messages = _build_orchestrator_messages(
        user_message, state.memory_context,
        evidence_pack.compact_summary, previous_messages,
    )

    # 6. Prepare MCP client WITH reviewer
    #     Filter out network tools if router says network needed but user disabled it
    allowed_tools = _get_allowed_tools_for_request(allowed_mcp_tools_config(), web_search=web_search)
    if not router_result.network_allowed and router_result.requires_network:
        # Block web_search and other network tools — explain limitation to user instead
        allowed_tools = [t for t in allowed_tools if t.get("name") != "web_search"]
        state.errors.append({"code": "network_blocked", "reason": router_result.network_reason})
        graph_manager.checkpoint(state)
    mcp_client = create_mcp_client(proxy_url, reviewer=ToolCallReviewer(...))
    model_tools = _format_tools_for_model(allowed_tools) if allowed_tools else None

    # 7. Multi-round tool loop (IMPROVED)
    tool_round = 0
    duplicate_guard = 0
    tool_result_cache = {}

    while tool_round < max_tool_rounds:
        tool_round += 1
        detected_tool_calls = []

        async for event in chat_completion_stream(...):
            if event.get("type") == "tool_calls_done":
                calls = event.get("calls", [])

                # New: only execute uncached calls
                new_calls = [c for c in calls if c.get("id") not in tool_result_cache]
                if not new_calls:
                    duplicate_guard += 1
                    if duplicate_guard >= 2:
                        break  # force final response

                tool_results = await handle_tool_calls(new_calls, mcp_client)
                for call, result in zip(new_calls, tool_results):
                    tool_result_cache[call["id"]] = result
                    orchestrator_messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    })
                state.tool_results = list(tool_result_cache.values())
                graph_manager.checkpoint(state)

                break

        if not detected_tool_calls and not all_tokens:
            break

    # 8. Final response: check for artifact intent
    final_text = "".join(all_tokens)
    artifact_plan, fallback_text = await plan_artifact(
        final_text, evidence_pack,
        artifact_type_hint=router_result.route,
    )

    if artifact_plan:
        state.artifact_plan = artifact_plan.model_dump()
        # Save artifact via engine
        artifact_id = await artifact_engine.save(artifact_plan, db)
        yield artifact_plan_event(chat_id, artifact_plan, artifact_id)

    # 9. Checkpoint final state
    state.final_response = fallback_text or final_text
    graph_manager.checkpoint(state)

    # 10. Complete trace
    trace_store.complete(trace_session_id, {
        "route": state.route,
        "worker_count": len(state.worker_results),
        "tool_call_count": len(tool_result_cache),
    })

    yield done_event(chat_id, message_id=msg_id)
```

#### T11: Wire `chat.py` Router Integration

Modify `backend/app/routers/chat.py:_handle_normal_chat()`.

- Add `file_ids` parameter to `orchestrate_turn()` call.
- Pass `web_search` setting to `classify_turn()`.
- Capture trace ID from orchestration, include in response.

#### T12: Update `architecture_config.json`

Add sections for router, reviewer, summarizer threshold, and model registry:

```json
{
  "agent_runtime": {
    "roles": {...},
    "streaming": {...},
    "orchestration": {...},
    "router": {
      "heuristic_keywords": {
        "artifact_generation": ["dashboard", "report", "chart", "table", "summary"],
        "data_analysis": ["csv", "visualize", "visualise", "tabulate", "plot"],
        "web_research": ["search", "find", "look up", "website", "article"]
      },
      "llm_fallback_model": "utility",
      "llm_fallback_temperature": 0.1
    },
    "summarizer": {
      "threshold_tokens": 4096,
      "failure_policy": "fallback_to_compact_string"
    },
    "reviewer": {
      "tier_map": {
        "get_time": "safe_read",
        "calculator": "safe_read",
        "file_read": "local_read",
        "web_search": "network",
        "get_location": "network"
      }
    },
    "model_registry": {
      "models": { ... }
    }
  }
}
```

The `summarizer.threshold_tokens` configures when the summarizer runs. Default: 4096. The `failure_policy` ensures the summarizer is not a hard abort — `fallback_to_compact_string` means the orchestrator still gets content if the summarizer model fails.

---

### Phase 6: Evals

#### T13: Eval Suite

Create `backend/app/agent/evals.py` and `backend/tests/test_evals.py`.

**Golden Task Format:**

```python
@dataclass
class EvalTask:
    task_id: str
    route: str                    # expected route
    user_message: str
    file_ids: list[str] | None
    expected_artifact_type: str | None
    expected_tool_calls: list[str] | None  # ["calculator", "file_read"]
    min_worker_count: int
    max_worker_count: int
    scoring_criteria: dict        # {"citations_match": True, "artifact_validates": True}
```

**Scoring:**

```python
class EvalScorer:
    def score_route(self, actual_route: str, expected_route: str) -> bool
    def score_tool_calls(self, actual: list[str], expected: list[str] | None) -> bool
    def score_worker_count(self, actual: int, min: int, max: int) -> bool
    def score_artifact_schema(self, artifact: dict) -> bool
    def score_latency(self, latency_ms: float, route: str) -> bool
```

**Golden Tasks (20-50):**

| # | Route | Description |
|---|---|---|
| 1-5 | `direct_answer` | Simple questions, greetings, clarifications |
| 6-10 | `local_file_question` | Questions about uploaded CSV/text files |
| 11-15 | `web_research` | "Search for latest info about X" |
| 16-20 | `data_analysis` | "Show me a dashboard from this CSV" |
| 21-25 | `artifact_generation` | "Generate a report from..." |
| 26-30 | `tool_action` | "Calculate 2+2", "What time is it" |

**Eval runner:**

```python
async def run_evals(tasks: list[EvalTask], db: Session) -> EvalResults:
    """Run all golden tasks against the current orchestration pipeline."""
    results = []
    for task in tasks:
        # Execute orchestration
        events = list(orchestrate_turn(...))
        # Score
        score = EvalScorer().score(events, task)
        results.append(EvalResult(task=task, score=score, events=events))
    return EvalResults(results=results, pass_rate=...)
```

---

## Risk & Constraints

| Risk | Mitigation |
|---|---|
| Local models struggle with structured JSON | JSON repair retry + fallback to raw text for artifact planning |
| Multi-round tool loops increase latency | Wall-clock timeout guard; max 5 rounds; max 12s per round |
| Reviewer adds overhead | Tiered: safe_read tools skip all checks; only network/write tools get full review |
| Durable checkpointing adds DB writes | Batch checkpoints — only write at stage boundaries, not per token |
| Evals drift as system evolves | Store evals in versioned JSON; run on CI |
| Breaking existing artifact routes | Keyword routes are preserved; ArtifactPlanner is additive |
| Router classifies network task but user disabled web_search | Runtime enforces `network_allowed` flag; blocks network tools; falls back to local context or explains limitation |

## Validation Plan

**Unit tests (new):**
- `test_router.py` — heuristic classification, LLM fallback, worker policy mapping
- `test_typed_workers.py` — Pydantic parsing, JSON repair retry, invalid output handling
- `test_evidence.py` — EvidencePack construction, compact string formatting, artifact_inputs
- `test_graph_state.py` — checkpoint create/load, SQLite persistence
- `test_reviewer.py` — tier lookup, path safety, injection detection, SSRF detection
- `test_artifact_planner.py` — plan extraction, schema validation, repair retry
- `test_model_registry.py` — registration, best_for_role, json_repair flag
- `test_trace_store.py` — JSONL writing, SQLite indexing, querying
- `test_evals.py` — scoring functions, eval runner

**Integration tests (new):**
- Test full turn flow with router → workers → evidence → tool loop → artifact plan
- Test MCP client with reviewer integrated
- Test checkpoint recovery after simulated failure
- Test `web_search=false` blocks network tools even when router classifies as `web_research`
- Test conditional summarizer — runs when above threshold, skips when below, falls back on failure

**Existing tests:**
- `test_runtime_tool_calls.py` — continue to pass (tool handling API unchanged)
- `test_agent_events.py` — continue to pass (event types unchanged)
- `test_architecture_config.py` — update for new config sections
- `pytest` from `backend` — all existing tests continue to pass

## Finalized Design Decisions

All three open questions are resolved:

1. **Router never overrides user settings.** If `web_search=false`, the router may classify as `web_research` but runtime must block network tools and continue with local-only behavior. `RouterResult.network_allowed` is controlled by user setting, not the router.

2. **Summarizer kept, made conditional.** EvidencePack is the source of truth. Summarizer only creates a compressed `compact_summary` when `evidence_pack.token_estimate > SUMMARIZER_THRESHOLD_TOKENS` (default 4096). If summarizer fails, fall back to raw compact string — no hard abort.

3. **Add `artifact_plan` event to Tauri/Rust stream parser in Phase 1.** Backend emits the event early (T4 — Turn Router). Tauri parser recognizes and preserves it. UI logs/ignores it until artifact rendering work begins in Phase 4. This prevents protocol refactoring later.

## Open Questions

None remaining.
