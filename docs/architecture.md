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
