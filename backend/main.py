"""Obrenna backend — FastAPI entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.db import init_db
from app.routers import (
    health,
    settings,
    files,
    artifacts,
    chat,
    system,
    models,
    chats,
    setup,
    shutdown,
    memory,
    tools,
    knowledge_packs,
    custom_tools,
    codebase_projects,
    codebase_agent_ws,
    codebase_agent_devices,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    # Close the shared model-runtime httpx client pool (Fix #3). The Python
    # sidecar runs this same FastAPI app via uvicorn, so this teardown covers
    # every production entry path.
    from app.model_runtime.client_pool import close_model_client
    await close_model_client()
    # Close the persistent MCP client connections (Fix #6).
    from app.mcp.client import get_mcp_manager
    await get_mcp_manager().shutdown()
    # Close pooled knowledge-pack sqlite3 connections (Fix #7).
    from app.services.memory import reset_knowledge_retriever
    reset_knowledge_retriever()


app = FastAPI(title="Obrenna", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(settings.router)
app.include_router(files.router)
app.include_router(artifacts.router)
app.include_router(chat.router)
app.include_router(system.router)
app.include_router(models.router)
app.include_router(chats.router)
app.include_router(setup.router)
app.include_router(shutdown.router)
app.include_router(memory.router)
app.include_router(tools.router)
app.include_router(knowledge_packs.router)
app.include_router(custom_tools.router)
app.include_router(codebase_projects.router)
app.include_router(codebase_agent_ws.router)
app.include_router(codebase_agent_devices.router)
