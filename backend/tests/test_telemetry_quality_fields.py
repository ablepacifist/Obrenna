"""Tests for the reasoning-quality telemetry fields.

Before these, TurnTelemetry recorded only speed — time-to-first-token, tool
runtimes, token counts. Nothing recorded *which configuration produced a
turn*, so a change in eval scores could not be attributed to a cause. These
fields close that gap, and the assertions below check they are populated from a
REAL turn rather than merely present on the dataclass.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent import pending
from app.agent import runtime as rt
from app.agent.runtime import ResolvedPlan, TurnTelemetry, orchestrate_turn
from app.model_runtime.config import RuntimeConfig


@pytest.fixture(autouse=True)
def _clear_registry():
    pending._pending.clear()
    yield
    pending._pending.clear()


class _StubMemory:
    def to_static_messages(self):
        return []

    def to_dynamic_messages(self):
        return []


def _script(monkeypatch, events):
    rounds = iter(events)

    async def fake_stream(config, messages, **kwargs):
        for ev in next(rounds):
            yield ev

    monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})


def _plan_and_config(model="qwen3.5:9b"):
    config = RuntimeConfig(
        provider="openai_compatible", base_url="http://localhost:11434/v1",
        models={"orchestrator": model},
    )
    plan = ResolvedPlan({"orchestrator": {
        "model": model, "tool_call_mode": "prompt_json", "max_tool_rounds": 4,
    }})
    return config, plan


class TestTelemetryUnit:
    def test_summary_includes_quality_fields(self):
        t = TurnTelemetry(started_at=0.0)
        summary = t.summary()
        for field in (
            "orchestrator_model", "agent_mode", "thinking_enabled",
            "reasoning_effort_by_round", "approval_wait_ms",
            "question_wait_ms", "model_time_ms",
        ):
            assert field in summary, f"missing quality field: {field}"

    def test_records_effort_per_round(self):
        t = TurnTelemetry(started_at=0.0)
        t.record_reasoning_effort(1, "medium")
        t.record_reasoning_effort(2, "none")
        assert t.summary()["reasoning_effort_by_round"] == {1: "medium", 2: "none"}

    def test_waits_accumulate_by_kind(self):
        t = TurnTelemetry(started_at=0.0)
        t.record_wait("approval", 1.5)
        t.record_wait("approval", 0.5)
        t.record_wait("question", 2.0)
        s = t.summary()
        assert s["approval_wait_ms"] == 2000
        assert s["question_wait_ms"] == 2000

    def test_unknown_wait_kind_is_ignored(self):
        t = TurnTelemetry(started_at=0.0)
        t.record_wait("bogus", 5.0)
        s = t.summary()
        assert s["approval_wait_ms"] == 0 and s["question_wait_ms"] == 0

    def test_model_time_excludes_user_waits(self):
        """A manual-mode turn must not look slow because a human was reading.

        Without this subtraction, total_turn_ms conflates model latency with
        however long someone took to click Approve — making manual mode look
        like a performance regression when nothing got slower.
        """
        import time
        t = TurnTelemetry(started_at=time.perf_counter() - 10.0)
        t.record_wait("approval", 6.0)
        s = t.summary()
        assert s["total_turn_ms"] >= 10000
        assert s["model_time_ms"] == pytest.approx(s["total_turn_ms"] - 6000, abs=200)

    def test_model_time_never_negative(self):
        t = TurnTelemetry(started_at=0.0)
        t.record_wait("approval", 10_000_000.0)
        assert t.summary()["model_time_ms"] == 0


class TestTelemetryFromRealTurn:
    """The telemetry STREAM event is opt-in behind OBRENNA_CHAT_TELEMETRY=1
    (the JSONL sink is separate and gated by OBRENNA_TELEMETRY). These turn it
    on so the emitted payload can be inspected directly."""

    @pytest.mark.asyncio
    async def test_fields_populated_by_orchestrate_turn(self, monkeypatch):
        monkeypatch.setenv("OBRENNA_CHAT_TELEMETRY", "1")
        _script(monkeypatch, [[{"type": "token", "content": "hi"}]])
        config, plan = _plan_and_config("qwen3.5:9b")

        events = [e async for e in orchestrate_turn(
            "hello", "chat-telemetry", None, config, plan,
            workers_enabled=False, thinking_enabled=True, agent_mode="manual",
        )]

        telemetry = [e for e in events if e.type == "telemetry"]
        assert telemetry, "turn emitted no telemetry event"
        payload = telemetry[-1].payload
        assert payload["orchestrator_model"] == "qwen3.5:9b"
        assert payload["agent_mode"] == "manual"
        assert payload["thinking_enabled"] is True
        # Round 1 with thinking on is "high" per _round_reasoning_effort.
        assert payload["reasoning_effort_by_round"].get(1) == "high"

    @pytest.mark.asyncio
    async def test_thinking_disabled_records_none_effort(self, monkeypatch):
        """The interesting case: what a zero-reasoning turn looks like."""
        monkeypatch.setenv("OBRENNA_CHAT_TELEMETRY", "1")
        _script(monkeypatch, [[{"type": "token", "content": "hi"}]])
        config, plan = _plan_and_config()

        events = [e async for e in orchestrate_turn(
            "hello", "chat-telemetry-2", None, config, plan,
            workers_enabled=False, thinking_enabled=False,
        )]
        payload = [e for e in events if e.type == "telemetry"][-1].payload
        assert payload["thinking_enabled"] is False
        assert payload["reasoning_effort_by_round"].get(1) == "none"
        assert payload["agent_mode"] == "auto"
