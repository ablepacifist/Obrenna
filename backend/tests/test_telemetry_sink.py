"""Tests for the local per-turn telemetry JSONL sink (Fix #8)."""
import json
import os
from pathlib import Path

import pytest

from app.services import telemetry as telemetry_mod


@pytest.mark.asyncio
async def test_write_turn_telemetry_appends_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setenv("OBRENNA_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("OBRENNA_TELEMETRY", "on")
    # Force the cached dir to re-resolve against the new env.
    telemetry_mod._dir_cache = None

    payload = {
        "total_turn_ms": 1234,
        "token_count": 5,
        "ollama_stats": {1: {"prompt_eval_count": 12, "eval_count": 3}},
    }
    telemetry_mod.write_turn_telemetry("chat_1", payload)

    out = (tmp_path / "turns.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(out) == 1
    record = json.loads(out[0])
    assert record["chat_id"] == "chat_1"
    assert record["telemetry"]["total_turn_ms"] == 1234
    assert record["telemetry"]["ollama_stats"]["1"]["prompt_eval_count"] == 12


@pytest.mark.asyncio
async def test_write_turn_telemetry_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OBRENNA_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("OBRENNA_TELEMETRY", "off")
    telemetry_mod._dir_cache = None

    telemetry_mod.write_turn_telemetry("chat_2", {"total_turn_ms": 1})

    assert not (tmp_path / "turns.jsonl").exists()


def test_telemetry_summary_records_ollama_stats_and_derived_prefix_cache_hit():
    from app.agent.runtime import TurnTelemetry

    t = TurnTelemetry(started_at=0.0)
    t.record_ollama_stats(1, {"prompt_eval_count": 100, "eval_count": 10})
    t.record_ollama_stats(2, {"prompt_eval_count": 20, "eval_count": 5})
    t.record_tool_runtime(0.150)
    t.tool_round_count = 2
    t.done_at = 1.0

    summary = t.summary()
    assert summary["ollama_stats"][1]["prompt_eval_count"] == 100
    assert summary["tool_round_count"] == 2
    assert summary["tool_runtime_ms"] == [150]
    # Round 2 prefilled fewer tokens than round 1 → prefix cache hit inferred.
    assert summary["prefix_cache_hit"] is True


def test_telemetry_summary_prefix_cache_hit_false_when_round2_not_smaller():
    from app.agent.runtime import TurnTelemetry

    t = TurnTelemetry(started_at=0.0)
    t.record_ollama_stats(1, {"prompt_eval_count": 20})
    t.record_ollama_stats(2, {"prompt_eval_count": 20})
    t.done_at = 1.0

    assert t.summary()["prefix_cache_hit"] is False