# Memory & Context Subsystem Plan

## Goal
Implement persistent local memory for GrebGlob so each installed app has a private on-device memory system that:

- Keeps recent chat turns in context.
- Maintains a per-chat rolling summary.
- Archives full chat turns with embeddings for deterministic retrieval.
- Stores durable local user facts with user-edit/delete authority.
- Retrieves relevant context before model generation without stuffing full history into prompts.
- Exposes a Memory settings UI for reviewing, editing, and deleting facts.

## Locked Decisions

- Scope: one implicit private local workspace/user per app install. Do not add auth, tenancy, or explicit account management in this milestone.
- Embeddings: bundle a CPU Python embedding runtime in the backend rather than relying on the configured OpenAI-compatible endpoint.
- Embedding implementation preference: use a small ONNX-backed package such as `fastembed` with a 384-dimension small model if packaging works; avoid a Torch stack unless necessary.
- Vector index: implement `sqlite-vec` now, not a brute-force-only v1.
- UI: include the Memory settings panel and transient memory-added feedback in this milestone.
- Existing chat storage remains the user-visible source for messages. Add a paired turn archive for memory rather than replacing `chat_messages`.

## Current Codebase Facts

- Backend is FastAPI + SQLAlchemy with SQLite initialized through `Base.metadata.create_all(engine)` in `backend/app/db.py`.
- There is no Alembic or migration framework.
- Chats are stored as `Chat` and separate `ChatMessage` rows in `backend/app/models.py`.
- `/api/chat` persists one user message row and one assistant message row in `backend/app/routers/chat.py`.
- The runtime client in `backend/app/model_runtime/client.py` is async, but `/api/chat` currently calls `chat_completion` from a sync route without awaiting it. Fix this boundary before adding memory calls.
- Hardware setup stores the resolved context in `AppSettings.managed_plan`; memory budget selection should read this when available and fall back safely.
- Desktop packaging uses PyInstaller through `backend/grebglob-server.spec` and CI build workflow `.github/workflows/build.yml`; `sqlite-vec` and embedding runtime assets must be packaged.

## Data Model Plan

1. Extend `Chat` with rolling-summary state:
   - `rolling_summary: Text`, default `""`.
   - `summarized_upto_turn_index: Integer`, default `-1`.
   - Keep existing `title`, folder, timestamps, and `messages` behavior unchanged.

2. Add a paired turn archive model, for example `ChatTurn`:
   - `id: str` primary key.
   - `chat_id: str` foreign key to `chats.id` with cascade delete.
   - `turn_index: int`, unique per chat.
   - `user_message_id: str` foreign key to `chat_messages.id`.
   - `assistant_message_id: str` foreign key to `chat_messages.id`.
   - `user_text: Text` and `assistant_text: Text` as a stable snapshot for retrieval.
   - `created_at`.

3. Add local memory facts, for example `AccountFact` or `MemoryFact`:
   - `id: str` primary key.
   - `account_id: str`, default `local-default` or equivalent constant for future migration seam.
   - `fact_text: Text`.
   - `source_chat_id: Optional[str]`.
   - `created_at`, `updated_at`.
   - `user_locked: bool`, default false.
   - `deleted_at: Optional[DateTime]` for tombstones.
   - Keep tombstone embeddings so auto-extraction can avoid re-adding user-deleted facts.

4. Add sqlite-vec virtual tables for embeddings:
   - `chat_turn_vectors` keyed by `turn_id` with embedding dimension matching the bundled model.
   - `memory_fact_vectors` keyed by `fact_id` with the same dimension.
   - Store enough metadata or joins to retrieve text and enforce chat/local workspace scope.

5. Implement idempotent schema upgrades because there is no Alembic:
   - Keep `Base.metadata.create_all(engine)` for new installs.
   - Add a `run_migrations()` step in `init_db()` after table creation that checks columns/tables with SQLite PRAGMA and applies safe `ALTER TABLE` statements.
   - Create/load sqlite-vec virtual tables with explicit error reporting.
   - Backfill paired `ChatTurn` rows from existing `chat_messages` by walking each chat in chronological order and pairing `user` followed by `assistant` messages.
   - Skip incomplete or malformed pairs; do not mutate existing messages.

## Backend Services

1. Add `backend/app/services/memory_config.py` or equivalent constants:
   - Similarity threshold: `0.60`.
   - Chat archive top-k default: `3`.
   - Fact top-k default: `5`.
   - Context-budget tiers from the provided brief.
   - Embedding model id/name and dimension.

2. Add `backend/app/services/embeddings.py`:
   - Lazily initialize then cache the bundled CPU embedding model process/object.
   - Provide `embed_text(text: str) -> list[float]` and batch support if the chosen package supports it.
   - Normalize or validate vector length before insert/search.
   - Fail with a clear backend error if the model assets are missing or the embedding package cannot load.

3. Add `backend/app/services/vector_store.py`:
   - Load sqlite-vec extension for the active SQLite connection where required.
   - Insert/update/delete turn and fact vectors.
   - Search chat turns by `chat_id`, query vector, threshold, and top-k.
   - Search memory facts by implicit local `account_id`, query vector, threshold, and top-k.
   - Return deterministic sorted results by similarity descending, then stable id/index tie-breakers.

4. Add `backend/app/services/memory.py`:
   - `pick_memory_budget(ctx_max)` using the brief’s context tiers.
   - `assemble_context(db, chat_id, user_message)` that embeds the user message, searches archive and facts, loads recency, loads rolling summary, and returns a structured context payload.
   - `build_model_messages(user_message, context_payload)` to convert memory context into a system/user message sequence for the orchestrator.
   - `record_turn_after_response(db, chat, user_msg, assistant_msg)` to create `ChatTurn` and vector rows.
   - `fold_aged_turn_into_summary(...)` to fold only the oldest newly aged-out turn into `Chat.rolling_summary`.
   - `extract_and_reconcile_facts(...)` to run after response, extract 0-5 candidate facts, compare against existing facts, and apply ADD/UPDATE/DELETE/NOOP.

5. Add structured prompts for background LLM calls:
   - Summary fold prompt: incorporate exactly one turn into the existing summary without re-summarizing the summary.
   - Fact extraction prompt: output JSON list of coarse, self-contained narrative facts; allow empty output.
   - Reconcile prompt: output one operation among ADD, UPDATE, DELETE, NOOP plus optional target fact id.
   - Use summarizer or utility model through the existing local endpoint. These are background calls and must not block response streaming once streaming exists.

## Chat Route Integration

1. Convert `/api/chat` route and helpers to correctly await async model-runtime calls, or add a synchronous runtime wrapper and use it consistently.

2. Before orchestrator generation for normal chat:
   - Resolve/create chat.
   - Persist the user message as today.
   - Call memory `assemble_context(...)`.
   - Call model with assembled messages, not only the raw user message.

3. For artifact-producing intents:
   - Persist user and assistant messages as today.
   - Still call `record_turn_after_response(...)` so the turn is archived.
   - Do not inject memory into deterministic CSV/dashboard builders unless later product requirements call for it.

4. After assistant response:
   - Persist assistant message.
   - Create `ChatTurn` with paired user/assistant IDs.
   - Embed and insert the turn vector.
   - Fold aged-out turns into rolling summary according to the budget.
   - Dispatch fact extraction/reconcile in a background task when possible.
   - Commit safely so a failed background extraction does not lose chat messages.

5. Context assembly precedence:
   - Recency buffer always.
   - Rolling summary always.
   - Account/local facts next.
   - Retrieved archive turns last.
   - Trim archive turns before facts when context is tight.

## Memory API

Add a router such as `backend/app/routers/memory.py` and include it in `backend/main.py`.

Endpoints:

- `GET /api/memory/facts`: list active, non-deleted local memory facts ordered by `updated_at desc`.
- `PATCH /api/memory/facts/{fact_id}`: update fact text, recompute embedding, set `user_locked=true`.
- `DELETE /api/memory/facts/{fact_id}`: set `deleted_at`, set `user_locked=true`, keep vector/tombstone for duplicate suppression.
- Optional `POST /api/memory/facts`: allow user-created memory facts; set `user_locked=true`.

Schemas:

- Add DTOs and request models to `backend/app/schemas/api.py` or split if the file becomes too large.
- Return `user_locked` and timestamps so the UI can explain user-controlled memories.

## Frontend Plan

1. Extend `frontend/src/lib/api.ts` with memory DTOs and calls.

2. Add a Memory tab in `frontend/src/components/settings/SettingsView.tsx`.

3. Add `frontend/src/components/settings/MemorySettings.tsx`:
   - List saved memories.
   - Allow inline edit/save.
   - Allow delete.
   - Explain that memories are stored locally on this machine.
   - Respect existing settings panel visual style.

4. Add transient memory feedback:
   - Backend can include memory event metadata in `ChatResponse`, or frontend can poll a lightweight memory event endpoint.
   - Prefer adding optional `memory_events` to `ChatResponse` for simple v1 feedback.
   - Show a small toast such as `Added to memory` when ADD/UPDATE occurs.

5. Keep Privacy settings accurate:
   - Update wording to mention local memory facts and that the user can edit/delete them in Settings > Memory.

## Packaging And Dependencies

1. Add required packages to `backend/requirements.txt`:
   - `sqlite-vec` package if available for target platforms.
   - Selected bundled embedding package, preferably `fastembed` or equivalent ONNX-backed option.
   - Any required numeric dependency if not brought transitively.

2. Update `backend/grebglob-server.spec`:
   - Include embedding package hidden imports/data.
   - Include sqlite-vec binaries/native extension.
   - Include any model asset directory if assets are bundled at build time.

3. Update `.github/workflows/build.yml`:
   - Install and verify new dependencies during backend build.
   - Add a smoke step that imports embedding service and loads sqlite-vec before PyInstaller build or immediately after building the executable.

4. Decide asset download behavior during implementation:
   - Preferred for desktop reliability: ship/cache the small embedding model in app data or bundled resources during managed setup.
   - Do not silently contact cloud services during normal chat. If setup must download assets, make it part of managed setup and keep Privacy copy accurate.

## Failure Modes

- Embedding runtime fails to load: chat should still work without memory retrieval; surface a clear local-memory-disabled warning in logs/UI.
- sqlite-vec fails to load: startup should not crash silently. Either fail memory initialization with explicit status or fall back only if product owner approves during implementation.
- Background extraction fails: preserve chat messages and turn archive; log error; do not show memory toast.
- User-locked fact matches an auto candidate: never update/delete it.
- User-deleted fact matches an auto candidate: do not re-add it; tombstone remains authoritative.
- Existing chat backfill finds incomplete pairs: skip them and continue.
- Context budget missing from managed plan: use 16k default tier from the brief.

## Validation Plan

Backend tests:

- `pick_memory_budget` returns expected caps for 8k, 16k, 32k, and above-32k contexts.
- Cosine/sqlite-vec search respects threshold, top-k, chat scope, and stable ordering.
- Backfill pairs chronological user/assistant messages and skips malformed sequences.
- Rolling summary folds only the newly aged-out turn and never rewrites old chat messages.
- User edit sets `user_locked=true` and recomputes vector.
- User delete tombstones, hides from list endpoint, and prevents auto re-add.
- Reconcile refuses UPDATE/DELETE against locked facts.
- `/api/chat` correctly awaits model calls and does not store coroutine objects as text.
- Memory endpoints list/edit/delete/create facts correctly.

Frontend checks:

- Memory tab lists facts, handles empty state, edits, deletes, and refreshes state.
- Toast appears for memory events without breaking normal chat flow.
- Existing chat UI remains unchanged when no memory events are present.

Packaging checks:

- `python -m pytest` from `backend` passes.
- Backend executable starts on Windows/macOS/Linux CI with sqlite-vec and embedding imports working.
- Fresh app install creates memory tables and vector tables.
- Existing app data migrates without deleting chats, files, artifacts, folders, or settings.

## Implementation Order

1. Fix async model-runtime boundary in chat route and add tests for normal chat response text.
2. Add schema models and idempotent migration/backfill helpers.
3. Add bundled embedding service and sqlite-vec vector store.
4. Add memory service for budgets, retrieval, context assembly, turn recording, summary folding, and fact reconciliation.
5. Integrate memory into `/api/chat` hot path and after-response path.
6. Add memory API routes and schemas.
7. Add frontend Memory settings tab and API bindings.
8. Add memory event response/toast flow.
9. Update dependency and packaging configuration.
10. Run backend, frontend, and packaged smoke validation.

## Out Of Scope

- Multi-user accounts, login, sync, cloud memory, or tenancy isolation.
- Retention/purge policies beyond user-deleted fact tombstones.
- LLM reranker for retrieval candidates.
- Streaming assistant responses unless already required by another active plan.
- Document/vector RAG for uploaded files.
