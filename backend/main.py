"""Obrenna backend — FastAPI entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.db import init_db
from app.routers import health, settings, files, artifacts, chat, system, models, chats, setup, shutdown, memory, tools


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


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
