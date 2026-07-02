"""Tests confirming user message / model reply content is not logged at INFO.

Obrenna is local-first/private-by-default. Several call sites previously
logged full user message text and full model replies at INFO level
(runtime.py, chat.py, model_runtime/client.py) — since INFO is commonly the
default configured log level, this meant private conversation content
routinely landed in log files. These call sites are now DEBUG-level; this
test locks that in so a future change can't silently regress it back to
INFO.
"""
from __future__ import annotations

import logging

import pytest


class TestOrchestrateTurnDoesNotLogMessageContentAtInfo:
    @pytest.mark.asyncio
    async def test_user_message_not_in_info_logs(self, monkeypatch, caplog):
        from app.agent import runtime as rt
        from app.model_runtime.config import RuntimeConfig

        secret_marker = "MY-VERY-PRIVATE-MESSAGE-CONTENT-12345"

        async def fake_stream(config, messages, **kwargs):
            yield {"type": "token", "content": "ok"}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        class _StubMemory:
            def to_messages(self):
                return []

        monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())

        config = RuntimeConfig(
            provider="openai_compatible", base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:4b"},
        )
        plan = rt.ResolvedPlan({"orchestrator": {"model": "qwen3.5:4b", "tool_call_mode": "openai_native"}})

        with caplog.at_level(logging.INFO, logger="app.agent.runtime"):
            _events = [
                e async for e in rt.orchestrate_turn(
                    secret_marker, "chat1", db=None, config=config, resolved_plan=plan,
                    workers_enabled=False,
                )
            ]

        info_and_above = [r for r in caplog.records if r.levelno >= logging.INFO]
        leaked = [r for r in info_and_above if secret_marker in r.getMessage()]
        assert not leaked, "user message content must not appear in INFO-level logs"


class TestChatRouterDoesNotLogMessageContentAtInfo:
    def test_send_message_does_not_log_message_text_at_info(self, monkeypatch, caplog):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.agent.events import StreamEvent
        from app.db import Base
        from app.models import AppSettings, ModelEndpoint
        from app.routers import chat as chat_router
        from app.schemas.api import ChatRequest

        secret_marker = "MY-VERY-PRIVATE-CHAT-MESSAGE-67890"

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        db.add(AppSettings(id=1, workers_enabled=False))
        db.add(ModelEndpoint(
            id=1, provider="openai_compatible", base_url="http://localhost:11434/v1",
            models={"orchestrator": "qwen3.5:4b"},
        ))
        db.commit()

        async def fake_orchestrate_turn(*args, **kwargs):
            yield StreamEvent(chat_id="doesnt-matter", type="token", payload={"text": "a reply"})

        monkeypatch.setattr(chat_router, "orchestrate_turn", fake_orchestrate_turn)
        monkeypatch.setattr(
            chat_router, "_get_hardware_plan",
            lambda db, workers_enabled=True: {
                "path": "fallback", "ctx": 8192, "helper_count": 0,
                "orchestrator": {"model": "qwen3.5:4b"}, "summarizer": {}, "utility": {},
            },
        )

        payload = ChatRequest(message=secret_marker)

        with caplog.at_level(logging.INFO, logger="app.routers.chat"):
            chat_router.send_message(payload, db=db)

        info_and_above = [r for r in caplog.records if r.levelno >= logging.INFO]
        leaked = [r for r in info_and_above if secret_marker in r.getMessage()]
        assert not leaked, "user chat message must not appear in INFO-level logs"
