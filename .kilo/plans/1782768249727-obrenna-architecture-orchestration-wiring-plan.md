# Obrenna Architecture & Orchestration Wiring Plan

## Goal

Wire the provided architecture contract into the current Obrenna codebase without making the MCP server thick or orchestration-aware. The current app already has a Tauri Rust shell, a PyInstaller-packaged FastAPI Python backend, a hardware resolver/catalog, memory services, chat persistence, and a synchronous HTTP chat path. This plan preserves the working REST/control-plane pieces while adding the required agent runtime, MCP boundary, Rust permission broker, and typed streaming channel.

## Locked Decisions

- Scope: strict migration.
- Keep FastAPI for setup, settings, files, artifacts, chats, memory, and health endpoints.
- Move chat generation into a Python agent runtime service owned by the backend sidecar.
- Rust core continues to spawn/supervise the Python sidecar and spawns the MCP server as a separate process.
- Resolve the Rust-spawned MCP plus Python stdio-client conflict with a Rust stdio proxy: Rust owns the MCP server process and its pipes, while Python sends MCP JSON-RPC frames to Rust over a small sidecar IPC/proxy channel; Rust relays them to the server stdio and relays responses back.
- Python owns local model runtime processes and orchestration logic. The MCP server exposes tools only.
- Phase 1 streaming emits only `token`, `done`, and `error`, but every event is typed as `{type, payload}` from day one.

## Current-Code Facts To Preserve

- `src-tauri/src/main.rs` and `src-tauri/src/backend.rs` already launch a packaged `obrenna-server` backend and expose Tauri commands for backend URL, data dir, logs, and updates.
- `backend/desktop_server.py` runs FastAPI on `OBRENNA_PORT`.
- `backend/app/routers/chat.py` currently detects artifact intents, persists messages, calls a synchronous local OpenAI-compatible model client, then returns a completed `ChatResponse`.
- `backend/app/services/hardware_resolver.py` already returns `orchestrator`, `summarizer`, `utility`, `ctx`, and `helper_count` from `hardware_catalog.json`.
- `backend/app/services/memory.py` already assembles memory context and folds summaries/facts, but the normal chat path does not yet route through a multi-role orchestration runtime.
- No `architecture_config.json` or JSON `memory_config.json` exists in the repo yet; memory settings currently live in Python constants.
- Frontend chat currently sends HTTP POST `/api/chat`, then reloads chat history and animates the completed assistant message locally. There is no real streaming listener yet.

## Target Runtime Shape

1. Rust starts the Python sidecar as today, but also reads its stdout line-by-line for typed event envelopes.
2. Rust starts a distinct MCP server process and owns its stdin/stdout handles.
3. Python loads `architecture_config.json`, `hardware_catalog.json`, and memory settings at startup.
4. Python builds a resolved plan from `choose_and_validate(...)`; it never hardcodes model IDs or helper counts in orchestration code.
5. Python agent runtime handles a chat turn: memory context, optional worker dispatch, summarizer evidence pack, orchestrator generation, MCP tool calls, persistence hooks, and typed streaming events.
6. Python MCP client sends MCP JSON-RPC requests to Rust's MCP proxy channel.
7. Rust's MCP proxy relays MCP requests to the server process over stdio and relays responses back to Python.
8. Sensitive MCP tools call the Rust permission broker, not Python, before executing.
9. Rust emits sidecar events to the webview as Tauri events, for example `obrenna://agent-event` or `agent-event` with `{chat_id, message_id?, type, payload}`.
10. Frontend subscribes to the typed Tauri event stream and incrementally appends tokens for the active assistant message.

## Implementation Steps

### 1. Add Architecture Contract Files

- Add `backend/app/services/architecture_config.json` from the supplied architecture brief.
- Decide whether to convert the current `backend/app/services/memory_config.py` constants into a JSON companion file now or add a loader that exposes the current Python constants in the same shape. Prefer a JSON `memory_config.json` if it has already been specified elsewhere; otherwise keep Python constants and leave JSON conversion as a follow-up.
- Update `backend/obrenna-server.spec` so PyInstaller bundles `architecture_config.json` and any new memory JSON file.
- Add a small loader module, for example `backend/app/services/architecture_config.py`, that validates the decision record keys required by the runtime.

### 2. Introduce Python Agent Runtime Modules

- Add `backend/app/agent/events.py` with typed event models: `token`, `done`, `error` for phase 1, with forward-compatible `type: str` and `payload: dict`.
- Add `backend/app/agent/runtime.py` for the orchestration entry point. Keep it independent from FastAPI route code.
- Add `ResolvedPlan` adapter code that maps the existing `choose_and_validate(...)` response into runtime fields: orchestrator model, summarizer model, utility model, helper count, and context.
- Add `ModelRuntime` abstraction under `backend/app/model_runtime/` that supports streaming generation. Initially it may wrap the existing local OpenAI-compatible endpoint if managed process spawning is not ready, but the interface must be role-based and plan-driven so llama.cpp/Ollama process ownership can be added behind it without changing orchestration.
- Ensure orchestrator calls use thinking-on handling and parse/remove `<think>` content from answer tokens. Utility and summarizer calls run thinking-off.

### 3. Implement Worker/Summarizer Orchestration

- Add `WorkerResult` and `dispatch_workers(...)` using `asyncio.Semaphore(plan.helper_count)`.
- Apply a 12 second timeout per utility worker and return explicit failure markers for `timeout`, `error`, or `invalid_output`; do not raise for a single worker failure.
- Add `summarize_into_evidence_pack(...)` that folds successful worker outputs and failure markers through the summarizer role.
- Treat summarizer failure as a hard abort and emit a typed `error` event.
- Ensure the orchestrator receives compact evidence packs, never raw concatenated worker outputs.

### 4. Add MCP Client Boundary In Python

- Add `backend/app/mcp/client.py` with a transport abstraction that supports the Rust stdio proxy now and can support direct stdio or HTTP/SSE registrations later.
- Expose `list_tools()` and `call_tool(name, args)` to the agent runtime only.
- Do not expose worker spawning as a tool.
- Restrict worker tool access in backend prompts/tool lists, not by negotiating a `no_spawn` MCP capability.

### 5. Add Rust MCP Server Process And Stdio Proxy

- Add a separate MCP server binary or packaged resource. Prefer a small Rust binary if practical because `get_time`, file path checks, and permission callbacks are shell-adjacent; a Python MCP server is acceptable only if it remains a distinct process spawned by Rust.
- Extend `src-tauri/src/backend.rs` or split a new `src-tauri/src/mcp.rs` module to spawn and supervise the MCP server on app startup.
- Implement a Rust MCP proxy that owns the server's stdin/stdout and relays JSON-RPC frames between Python and the server.
- Use a simple, length-safe local IPC protocol between Python and Rust for proxy requests. Acceptable options are JSONL over the existing Python sidecar stdin/stdout with correlation IDs, or a loopback TCP listener bound to `127.0.0.1` and passed to Python via env var. Prefer loopback TCP if stdout is reserved for UI events.
- Keep UI streaming events and MCP proxy traffic separated so token events cannot be confused with MCP responses.
- Terminate the MCP server when the Tauri app exits, alongside the Python backend.

### 6. Implement Initial MCP Tools

- `get_time`: direct local system time and timezone.
- `calculator`: sandboxed expression grammar evaluator only. Never use `eval`, shell, Python AST execution, JavaScript `Function`, or equivalent code execution.
- `file_read`: only accepts file IDs or paths resolved from the existing `File` rows/user-surfaced allowlist. Never honor arbitrary model-supplied absolute paths.
- `web_search`: snippets plus source URLs only. Do not add full-page fetch.
- `get_location`: routes through Rust permission broker and returns `granted`, `denied`, or `prompt_shown` semantics. If platform location is unavailable in phase 1, return a clean denied/unavailable result rather than faking coordinates.

### 7. Add Rust Permission Broker

- Add broker state in Rust for sensitive capabilities, starting with location.
- Expose a broker method reachable from the MCP server process. If the MCP server is a separate Rust binary, use loopback IPC or a scoped local endpoint; do not store the permission decision in the MCP server.
- Prompt through the visible Tauri shell when no decision exists.
- Persist or cache grants according to product policy. If persistence is not yet decided, cache for the session and make that explicit in code and UI copy.

### 8. Wire Typed Streaming From Python To Rust To Webview

- Define a single JSON event envelope emitted by Python, for example `{"channel":"agent_event","chat_id":"...","type":"token","payload":{"text":"..."}}`.
- In Rust, read Python sidecar stdout line-by-line and parse only recognized JSON envelopes as events. Route ordinary logs to log files/stderr.
- Emit Tauri events to the webview with the same typed envelope.
- Add frontend event subscription with `@tauri-apps/api/event.listen` for desktop mode.
- Update chat state to create a pending assistant message, append `token.payload.text`, finalize on `done`, and surface `error` without corrupting persisted history.
- Keep an HTTP fallback for browser dev mode: either retain current completed response behavior or add SSE later. Do not block the strict desktop event path on browser streaming.

### 9. Refactor Chat Route Safely

- Split `backend/app/routers/chat.py` into thin routing plus service functions. Keep deterministic artifact generation paths working.
- For normal chat, create/persist the user message, start `agent_runtime.orchestrate_turn(...)`, stream events, then persist the assistant message when done.
- Ensure memory recording and fact extraction happen after the final assistant response is known, not per token.
- Avoid sharing a SQLAlchemy session across background threads. Create a fresh session for any background fact extraction.
- Preserve existing `ChatResponse` shape for non-streaming fallback and tests.

### 10. Packaging And Build Updates

- Add Python dependencies for the chosen MCP SDK and streaming support to `backend/requirements.txt`.
- Update `backend/obrenna-server.spec` hidden imports and datas for new agent/MCP/config modules.
- If the MCP server is Rust, ensure CI builds it and includes it under `src-tauri/resources` or an equivalent Tauri resource path.
- If the MCP server is Python, create a second PyInstaller entry point and update `.github/workflows/build.yml` to upload/download both sidecar binaries.
- Update `src-tauri/tauri.conf.json` resources to include all sidecar and MCP server binaries.
- Ensure Windows `.exe` naming is handled for both Python backend and MCP server.

## Failure Modes To Implement

- Python sidecar startup failure: Rust reports startup error and does not show a fake-ready chat UI.
- MCP server startup failure: Python agent emits typed `error` for tool use and Rust logs process failure.
- MCP proxy timeout: return a tool error to Python with correlation ID and do not hang the orchestrator.
- Utility worker timeout/error: include explicit failure marker in evidence pack and continue.
- Summarizer failure: hard abort the turn and emit typed `error`.
- Orchestrator generation error: emit typed `error`, persist a clean assistant error message if appropriate, and leave the chat recoverable.
- Permission denied: return structured tool result; do not throw unless broker IPC itself fails.
- Frontend listener disconnect/reload: reload persisted chat history from REST endpoints; streaming is best-effort live UI, persistence remains backend-owned.

## Validation Plan

- Backend unit tests for architecture config loading and resolved-plan mapping.
- Backend async tests for worker timeout behavior, failure marker schema, summarizer hard abort, and evidence-pack prompt assembly.
- MCP server tests for `calculator` rejecting code execution payloads, `file_read` rejecting non-allowlisted paths, `get_time` schema, and `get_location` denied/unavailable path.
- Rust tests or integration harness for MCP proxy correlation IDs, request/response forwarding, child process termination, and malformed JSON handling.
- Frontend tests or manual verification that token/done/error events update one pending assistant message and do not duplicate persisted messages after reload.
- Existing backend tests: `pytest` from `backend`.
- Frontend build: `npm --prefix frontend run build`.
- Rust build/check: `cargo check` from `src-tauri`.
- Packaging smoke: PyInstaller build for `obrenna-server` and any MCP sidecar, then Tauri dev/build launch enough to confirm both child processes start and terminate.

## Rollout Order

1. Add config loader and event envelope models with tests.
2. Add Python agent runtime skeleton and streaming model-runtime interface without changing the UI yet.
3. Add Rust sidecar stdout event reader and frontend event listener using a fake/test event path.
4. Refactor normal chat to use the agent runtime and emit phase-1 typed events.
5. Add MCP server process, Rust stdio proxy, and Python MCP client transport.
6. Add initial five tools and permission broker behavior.
7. Connect orchestrator tool calls through the MCP client.
8. Add worker dispatch and summarizer evidence-pack flow.
9. Harden packaging/CI and remove any temporary fake event paths.

## Non-Goals For This Pass

- Full arbitrary web fetch.
- File write, shell execution, data-analysis sandbox, or artifact render tool.
- Showing raw thinking traces in the UI.
- Remote Anthropic API integration.
- Replacing all REST endpoints with sidecar IPC.
- Downloading GGUF model files in the installer.

## Open Follow-Ups

- Decide the exact persistent policy for location permission grants: session-only, per-install, or per-capability with reset UI.
- Decide whether `memory_config.py` must become `memory_config.json` immediately or whether a loader shim is enough for this migration.
- Choose the concrete MCP SDK/crate after checking current Python/Rust ecosystem fit; preserve the process boundary regardless of SDK.
