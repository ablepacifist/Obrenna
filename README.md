# GrebGlob — local-first AI artifact workspace

A downloadable private AI workspace that turns your files into polished artifacts — dashboards, PDF reports, charts, tables, and documents — using only local models. No cloud calls, no data leaving your machine.

**Not** a generic ChatGPT clone. The LLM only emits structured artifact specs; the app renders them deterministically.

---

## Architecture

```
frontend/   React + Vite + TypeScript + Tailwind v4
backend/    FastAPI + SQLAlchemy (SQLite) + LangGraph
shared/     artifact-schema.json  ← single source of truth
```

**The load-bearing rule:** The LLM produces a JSON artifact spec. The frontend renders it. The LLM never directly outputs HTML, charts, or PDF layout.

**Privacy:** Everything runs on your machine. The backend speaks to a local model endpoint (Ollama, LM Studio, llama.cpp, vLLM, or any OpenAI-compatible server). No telemetry, no cloud storage.

## First vertical slice (works today, no LLM required)

```
Upload sales.csv → deterministic DashboardArtifact → renders in browser → exports to PDF
```

The dashboard builder (`backend/app/services/dashboard_builder.py`) is the seam where a local model will later author the spec instead of the heuristic builder.

---

## Install

### Backend

Requirements: **Python ≥ 3.11**, pip.

```bash
cd backend
pip install -r requirements.txt
python -m playwright install chromium   # one-time ~150 MB download for PDF export
```

### Frontend

Requirements: **Node ≥ 20**, npm.

```bash
cd frontend
npm install
```

### Root codegen (optional — types are pre-committed)

```bash
npm install          # at repo root
npm run codegen      # regenerates frontend/src/lib/types/artifact.ts from shared/artifact-schema.json
```

---

## Dev

**Run both apps** (two terminals):

```bash
# Terminal 1 — backend
cd backend
python -m uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm run dev
```

Frontend runs at `http://localhost:5173`. Vite proxies `/api` and `/health` to `http://localhost:8000`.

**Run backend tests:**

```bash
cd backend
pytest
```

---

## Local model setup

The backend defaults to `http://localhost:11434/v1` (Ollama). To configure a different endpoint:

1. Start the app and go through the setup flow → "Connect my own local server".
2. Or `POST /api/settings/model-endpoint` with your provider URL.

Recommended local models (from `backend/app/services/model_catalog.py`):

| Model | Role | Size |
|---|---|---|
| Qwen 2.5 14B | Main reasoner | 9.2 GB |
| Phi-3.5 Mini | Summarizer | 2.3 GB |
| Llama 3.2 3B | Utility | 2.0 GB |

With **Ollama**: `ollama pull qwen2.5:14b && ollama pull phi3.5 && ollama pull llama3.2:3b`

---

## API surface

```
GET  /health
GET  /api/settings/model-endpoint
POST /api/settings/model-endpoint
POST /api/settings/model-endpoint/test
GET  /api/settings/app
POST /api/settings/app
POST /api/files/upload
POST /api/artifacts/dashboard-from-csv
GET  /api/artifacts/{id}
POST /api/artifacts/{id}/export/pdf
GET  /api/artifacts/{id}/export/pdf/download
POST /api/chat
GET  /api/system/hardware
GET  /api/models/catalog
GET  /api/folders
POST /api/folders
GET  /api/chats
POST /api/chats
GET  /api/chats/{id}
PATCH /api/chats/{id}
DELETE /api/chats/{id}
```

Interactive docs: `http://localhost:8000/docs`

---

## Artifact types

All defined in `shared/artifact-schema.json`. Five discriminated types:

- **dashboard** — KPI cards, charts (bar/line/area), tables, insights
- **report** — structured sections with headings, paragraphs, optional tables
- **chart** — single recharts chart (bar/line/area/pie)
- **table** — plain columns + rows
- **document** — markdown body

---

## Roadmap

- [ ] Wire local model to `_generate_artifact_spec` in `backend/app/graphs/csv_dashboard.py`
- [ ] Chat routing: intent → correct artifact builder (dashboard/report/chart/table/summary)
- [ ] Streaming assistant responses
- [ ] Multi-file upload and cross-file analysis
- [ ] PDF export: faithful browser rendering via Playwright (replace SVG approximation)
- [ ] Managed model download via Ollama API
- [ ] Windows/macOS installer (Tauri or packaged Electron shell)
