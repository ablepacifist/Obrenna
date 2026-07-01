"""Tests for worker dispatch and summarizer fallback behavior."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.workers import (
    EvidencePack,
    WorkerResult,
    WorkerStatus,
    summarize_into_evidence_pack,
    dispatch_workers,
)
from app.model_runtime.config import RuntimeConfig


class TestEvidencePack:
    def test_empty_pack_compact_string(self):
        pack = EvidencePack()
        compact = pack.to_compact_string()
        assert compact == "No worker results available."

    def test_success_entry_compact_string(self):
        pack = EvidencePack(entries=[
            {"worker_id": "w1", "status": "success", "output": {"key": "value"}}
        ])
        compact = pack.to_compact_string()
        assert "w1" in compact
        assert "key" in compact

    def test_failure_entry_compact_string(self):
        pack = EvidencePack(entries=[
            {"worker_id": "w1", "status": "timeout", "error": "timed out"}
        ])
        compact = pack.to_compact_string()
        assert "w1" in compact
        assert "FAILED" in compact
        assert "timeout" in compact


class TestSummarizerFallback:
    @pytest.mark.asyncio
    async def test_summarizer_success(self):
        """When summarizer succeeds, return the summary."""
        config = RuntimeConfig(provider="test", base_url="http://test", api_key="", models={})
        pack = EvidencePack(entries=[
            {"worker_id": "w1", "status": "success", "output": {"result": "ok"}}
        ])

        with patch("app.agent.workers.chat_completion_stream") as mock_stream:
            mock_stream.return_value = self._make_stream([
                {"type": "token", "content": "This is the summary."}
            ])
            summary, success = await summarize_into_evidence_pack(
                config, "test-model", pack
            )
            assert success is True
            assert "summary" in summary.lower()

    @pytest.mark.asyncio
    async def test_summarizer_fallback_to_compact(self):
        """When summarizer fails, caller should fall back to compact string."""
        config = RuntimeConfig(provider="test", base_url="http://test", api_key="", models={})
        pack = EvidencePack(entries=[
            {"worker_id": "w1", "status": "success", "output": {"result": "ok"}}
        ])

        with patch("app.agent.workers.chat_completion_stream") as mock_stream:
            mock_stream.side_effect = RuntimeError("Model unavailable")
            summary, success = await summarize_into_evidence_pack(
                config, "test-model", pack
            )
            assert success is False
            assert summary == ""

            # The caller (runtime.py) should then use pack.to_compact_string()
            compact = pack.to_compact_string()
            assert "w1" in compact

    @pytest.mark.asyncio
    async def test_summarizer_and_fallback_both_fail(self):
        """When both summarizer and compact fallback produce empty, error is emitted."""
        config = RuntimeConfig(provider="test", base_url="http://test", api_key="", models={})
        empty_pack = EvidencePack()  # No entries

        with patch("app.agent.workers.chat_completion_stream") as mock_stream:
            mock_stream.side_effect = RuntimeError("Model unavailable")
            summary, success = await summarize_into_evidence_pack(
                config, "test-model", empty_pack
            )
            assert success is False
            assert summary == ""

            # Compact fallback of empty pack returns "No worker results available."
            compact = empty_pack.to_compact_string()
            # The caller should detect this and emit error event
            assert compact == "No worker results available."

    @staticmethod
    def _make_stream(tokens):
        async def gen():
            for token in tokens:
                yield token
        return gen()


class TestWorkerDispatch:
    @pytest.mark.asyncio
    async def test_worker_timeout_produces_failure_marker(self):
        """Worker timeout should produce a WorkerResult with status=TIMEOUT."""
        tasks = [{"worker_id": "w1", "user_prompt": "Do something"}]
        config = RuntimeConfig(provider="test", base_url="http://test", api_key="", models={})

        with patch("app.agent.workers._execute_worker") as mock_exec:
            mock_exec.side_effect = asyncio.TimeoutError("timeout")
            results = await dispatch_workers(
                tasks, config, "test-model", "system prompt",
                helper_count=1, timeout_seconds=1, workers_enabled=True
            )
            assert len(results) == 1
            assert results[0].status == WorkerStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_worker_success(self):
        """Successful worker should produce WorkerResult with status=SUCCESS."""
        tasks = [{"worker_id": "w1", "user_prompt": "Do something"}]
        config = RuntimeConfig(provider="test", base_url="http://test", api_key="", models={})

        with patch("app.agent.workers._execute_worker") as mock_exec:
            mock_exec.return_value = '{"key": "value"}'
            results = await dispatch_workers(
                tasks, config, "test-model", "system prompt",
                helper_count=1, timeout_seconds=12, workers_enabled=True
            )
            assert len(results) == 1
            assert results[0].status == WorkerStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_workers_disabled_returns_empty(self):
        """When workers_enabled=False, dispatch_workers should return empty list."""
        tasks = [{"worker_id": "w1", "user_prompt": "Do something"}]
        config = RuntimeConfig(provider="test", base_url="http://test", api_key="", models={})

        results = await dispatch_workers(
            tasks, config, "test-model", "system prompt",
            helper_count=1, timeout_seconds=12, workers_enabled=False
        )
        assert results == []
