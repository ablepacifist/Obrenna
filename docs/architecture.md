# Architecture

Obrenna is a **local-first AI artifact workspace**. It runs entirely on the user's
machine: files, prompts, and generated artifacts never leave the device unless the
user explicitly shares them.

## Layers

```
┌─────────────────────────────────────────────────────────────┐
│ frontend/  React + Vite + TS + Tailwind v4                   │
│   setup flow · sidebar · chat · artifact renderers · settings│
└───────────────▲─────────────────────────────────────────────┘
                │  HTTP (JSON), VITE_API_BASE_URL
┌───────────────┴─────────────────────────────────────────────┐
│ backend/  FastAPI                                            │
│   routers ─► services ─► graphs (LangGraph) ─► model_runtime │
│                          │                                   │
│                          ▼                                   │
│              SQLite (SQLAlchemy 2.0) + local file storage    │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
shared/artifact-schema.json  ── codegen ──►  TS types + Pydantic models
```

## The load-bearing rule

The model never renders dashboards or PDFs. It only ever produces a **structured
artifact spec** (see `shared/artifact-schema.json`). The app validates that spec
against the schema and renders it **deterministically**. This keeps output
reliable, exportable, and identical across runs.

In the first vertical slice the dashboard spec is produced **deterministically from
the CSV** (no model needed). The `generate_artifact_spec` node in
`backend/app/graphs/csv_dashboard.py` is the single seam where a configured local
model can later take over spec generation.

## Separation of concerns

- **artifacts** — schema + renderers (the contract between agent and UI)
- **model_runtime** — OpenAI-compatible adapter for local endpoints
- **graphs** — LangGraph orchestration
- **UI** — pure rendering of validated specs

These are deliberately independent so any one can be swapped without touching the others.

## Privacy posture

- No cloud calls by default. The only outbound traffic is to a **local** model
  endpoint the user configures (e.g. Ollama at `http://localhost:11434/v1`).
- "Automatic model downloading" and "web search" are intentionally **not** wired up
  in this milestone (see plan). The setup flow's download step is simulated.

## Runtime Boundaries

**Rust (Tauri)** owns: process lifecycle, process supervision, app permissions,
typed frontend event bridge. The `BackendProcesses` supervisor owns both the MCP
proxy and Python sidecar child handles. On app close, Rust attempts graceful
Python shutdown via HTTP, then forced `kill()` + `wait()` on both children.

**Python (FastAPI/LangGraph)** owns: orchestration, worker dispatch, summarizer
routing, model runtime integration, MCP client behavior, and local memory service.
Python writes typed JSON event envelopes to stdout for Rust to read.

**MCP server** exposes tools only. It must not become the agent runtime.

## Streaming Events

Agent stdout is **not** automatically a chat event. Rust validates each stdout
line as JSON and checks the `type` field against a whitelist:
`token`, `done`, `error`, `thinking_delta`, `tool_call`, `tool_result`,
`tool_progress`. Non-matching lines are emitted as `backend-log` events.

## Memory Semantics

Memory is local/private. User-created facts default to `user_locked=true`.
Automatic memory extraction (`extract_and_reconcile_facts`) uses `source="auto"`
which sets `user_locked=false`. Auto-memory **cannot** overwrite `user_locked`
facts — the `_reconcile_fact` function returns `NOOP` for locked facts on
UPDATE/DELETE operations. Delete tombstones locked facts instead of physically
erasing them.

Memory configuration is loaded from `backend/app/services/memory_config.json`
via a Pydantic model. Constants are not scattered.

## Vector Search

Current vector search backend is brute-force cosine behind a `VectorStore` ABC.
Embeddings are computed on-the-fly from persisted `chat_turns` and `memory_facts`
rows — no separate index is maintained. `sqlite-vec` is not currently active
unless explicitly implemented and enabled in config.

## Worker and Summarizer Failure

Worker timeout or error produces a failure marker in the evidence pack — the
turn continues. Summarizer failure falls back to `EvidencePack.to_compact_string()`.
Hard error (`code: summarizer_failure`) is emitted only when both the summarizer
and the compact fallback fail.
