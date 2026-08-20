"""Reliability regressions distilled from a real failing transcript.

Each test reproduces a specific way the agent misled the user, and asserts the
fix. Before these fixes the suite was silent on all of them — the user's core
complaint ("the tests are not actually capturing the errors").

Failures covered:
  * The model narrates an intention ("…let me check that directory:") and stops
    without calling any tool, leaving a dangling fragment as the whole reply.
  * A model-call timeout stringifies to "" → an invisible error toast and a
    persisted fragment with no explanation.
  * The persisted reply glues a pre-tool-call preamble to the final answer
    ("…correctly:Done! The README…").
  * Text-only history erases the model's memory of its own file actions, so it
    truthfully denies ever creating files it created (the action-log trailer).
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent.runtime import (
    ResolvedPlan,
    orchestrate_turn,
    _looks_like_unfinished_narration,
    _malformed_tool_call_guidance,
)
from app.model_runtime.config import RuntimeConfig


class _StubMemory:
    def to_static_messages(self):
        return []

    def to_dynamic_messages(self):
        return []


def _plan(max_tool_rounds=3):
    return ResolvedPlan({"orchestrator": {
        "model": "qwen3.5:4b", "tool_call_mode": "prompt_json",
        "max_tool_rounds": max_tool_rounds,
    }})


def _config():
    return RuntimeConfig(provider="openai_compatible",
                         base_url="http://localhost:11434/v1", models={})


def _patch_common(monkeypatch):
    from app.agent import runtime as rt
    monkeypatch.setattr(rt, "assemble_context", lambda *a, **k: _StubMemory())
    monkeypatch.setattr(rt, "get_orchestration_config", lambda: {"worker_timeout_seconds": 1})
    return rt


# ── _looks_like_unfinished_narration — the detector, in isolation ────────────

class TestNarrationDetector:
    @pytest.mark.parametrize("text", [
        "You're right - let me check what's actually in that directory:",
        "I'll read the file now:",
        "Let me look at the config.",
        "First, I will list the files.",
        "Checking the directory now",
    ])
    def test_flags_action_promises(self, text):
        assert _looks_like_unfinished_narration(text) is True

    @pytest.mark.parametrize("text", [
        "Yes, that file exists at the project root.",
        "The gateway is a login layer in front of Obrenna.",
        "Done. I removed the Troubleshooting section and updated the date.",
        "",  # empty is handled by other fallbacks, not this detector
    ])
    def test_does_not_flag_real_answers(self, text):
        assert _looks_like_unfinished_narration(text) is False

    def test_long_output_never_flagged_even_with_intent_word(self):
        # A long substantive answer that happens to contain "let me" is a real
        # answer, not a dangling preamble.
        text = ("Here is the full explanation. " * 20) + "let me know if you want more."
        assert _looks_like_unfinished_narration(text) is False


# ── narration nudge in orchestrate_turn ──────────────────────────────────────

class TestNarrationNudge:
    @pytest.mark.asyncio
    async def test_dangling_fragment_triggers_one_retry_that_answers(self, monkeypatch):
        rt = _patch_common(monkeypatch)
        calls = {"n": 0}

        async def fake_stream(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                # A promise with no tool call — the exact wild failure.
                yield {"type": "token", "content": "You're right - let me check that directory:"}
            else:
                # The retry round must carry the nudge guidance.
                messages = args[1]
                assert any("did not actually call any tool" in (m.get("content") or "")
                           for m in messages), "nudge guidance must be fed on retry"
                yield {"type": "token", "content": "There are three README files: A, B, and C."}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        events = [e async for e in orchestrate_turn(
            "what's in that directory?", "chat-nudge", None, _config(), _plan(),
            workers_enabled=False,
        )]

        assert calls["n"] == 2, "exactly one nudge retry"
        # A round boundary was emitted so the collector drops the fragment.
        assert any(e.type == "phase" and e.payload.get("phase") == "model"
                   for e in events)
        # The final answer (round 2) is present; no error surfaced.
        answer_events = [e for e in events if e.type == "token"
                         and "three README files" in e.payload.get("text", "")]
        assert answer_events
        assert not any(e.type == "error" for e in events)

    @pytest.mark.asyncio
    async def test_nudge_fires_at_most_once(self, monkeypatch):
        """If the model keeps narrating, we nudge ONCE then accept — never loop."""
        rt = _patch_common(monkeypatch)
        calls = {"n": 0}

        async def fake_stream(*args, **kwargs):
            calls["n"] += 1
            # Always a dangling fragment, every round.
            yield {"type": "token", "content": "Let me check that directory:"}

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        events = [e async for e in orchestrate_turn(
            "what's there?", "chat-nudge-2", None, _config(), _plan(),
            workers_enabled=False,
        )]

        # Round 1 + exactly one nudge retry, then accept — bounded.
        assert calls["n"] == 2
        assert any(e.type == "done" for e in events)


# ── timeout / opaque exceptions become VISIBLE ───────────────────────────────

class TestRepeatedFailingCommandNudge:
    """A model that re-runs the SAME failing command instead of fixing the code
    (seen re-running a crashing script until the round cap) must be told, after
    the second identical failure, to edit the file instead of re-running."""

    @pytest.mark.asyncio
    async def test_second_identical_failure_injects_fix_guidance(self, monkeypatch):
        import json as _json
        rt = _patch_common(monkeypatch)
        calls = {"n": 0}
        saw_guidance = {"at_round": None}

        async def fake_stream(*args, **kwargs):
            calls["n"] += 1
            messages = args[1]
            if any("STOP re-running the same command" in (m.get("content") or "") for m in messages):
                saw_guidance["at_round"] = calls["n"]
            if calls["n"] <= 2:
                # Run the same broken command twice.
                yield {"type": "tool_calls_done", "calls": [{
                    "id": f"c{calls['n']}", "type": "function",
                    "function": {"name": "codebase_run_command",
                                 "arguments": {"command": "python tictactoe.py"}},
                }]}
            else:
                yield {"type": "token", "content": "I'll fix the file now."}

        async def fake_handle_tool_calls(tool_calls, mcp_client):
            return [{
                "tool_call_id": tc["id"], "tool_name": "codebase_run_command",
                "content": _json.dumps({"exit_code": 1, "stdout": "", "stderr": "Traceback: boom", "timed_out": False}),
            } for tc in tool_calls]

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)
        monkeypatch.setattr(rt, "handle_tool_calls", fake_handle_tool_calls)

        events = [e async for e in orchestrate_turn(
            "build and run tictactoe", "chat-loop", None, _config(), _plan(max_tool_rounds=6),
            workers_enabled=False,
        )]

        # Once the same command fails repeatedly, the fix-the-file guidance must
        # be injected (before the round cap) so the model stops re-running it.
        assert saw_guidance["at_round"] is not None, "fix-the-file guidance was never injected"
        assert saw_guidance["at_round"] >= 3

    def test_run_command_failed_detects_failure_shapes(self):
        from app.agent.runtime import _run_command_failed
        assert _run_command_failed('{"exit_code": 1, "stderr": "boom"}') is True
        assert _run_command_failed('{"exit_code": 0, "stdout": "ok"}') is False
        assert _run_command_failed('{"timed_out": true, "exit_code": null}') is True
        assert _run_command_failed('{"error": true, "message": "x"}') is True
        # Unparseable now counts as failure. It used to read as success, which
        # meant the two shapes that produce it -- a bare "Tool error: ..." string
        # from an unhandled exception, and a result cut mid-JSON by compaction --
        # were exempt from the nudge above, exactly when output was largest.
        assert _run_command_failed("not json") is True
        assert _run_command_failed('{"exit_code": 1, "stdout": "xxx') is True
        # Absence of a result is still not evidence of a failed one.
        assert _run_command_failed("") is False


class TestVisibleFailures:
    @pytest.mark.asyncio
    async def test_timeout_yields_visible_message_not_empty(self, monkeypatch):
        rt = _patch_common(monkeypatch)

        async def fake_stream(*args, **kwargs):
            raise asyncio.TimeoutError()
            yield  # pragma: no cover — make this an async generator

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        events = [e async for e in orchestrate_turn(
            "do a big thing", "chat-timeout", None, _config(), _plan(),
            workers_enabled=False,
        )]

        errors = [e for e in events if e.type == "error"]
        assert errors, "a timeout must surface an error event"
        assert "timed out" in errors[0].payload.get("message", "").lower()
        assert errors[0].payload.get("message", "").strip() != ""
        # And the user gets visible reply text, never an empty/dangling turn.
        tokens = "".join(e.payload.get("text", "") for e in events if e.type == "token")
        assert tokens.strip(), "a failed turn must still produce visible text"
        assert "timed out" in tokens.lower()

    @pytest.mark.asyncio
    async def test_empty_string_exception_names_the_type(self, monkeypatch):
        rt = _patch_common(monkeypatch)

        async def fake_stream(*args, **kwargs):
            raise RuntimeError("")  # str(exc) == "" — the invisible-toast case
            yield

        monkeypatch.setattr(rt, "chat_completion_stream", fake_stream)

        events = [e async for e in orchestrate_turn(
            "hello", "chat-empty-exc", None, _config(), _plan(),
            workers_enabled=False,
        )]

        errors = [e for e in events if e.type == "error"]
        assert errors
        msg = errors[0].payload.get("message", "")
        assert msg.strip() != ""
        assert "RuntimeError" in msg  # type name fills in for the empty str()


# ── chat.py tool-event grounding helpers (pure) ──────────────────────────────

class TestToolEventGrounding:
    def test_summarize_marks_success_and_failure(self):
        from app.routers.chat import _summarize_tool_event
        ok = _summarize_tool_event(
            "codebase_write_file", {"path": "README.md"},
            '{"path": "README.md", "created": true, "content_hash": "abc"}',
        )
        assert ok == {"tool": "codebase_write_file", "path": "README.md",
                      "new_path": None, "ok": True, "detail": ""}

        bad = _summarize_tool_event(
            "codebase_edit_file", {"path": "SETUP.md"},
            '{"error": true, "message": "old_string not found in SETUP.md"}',
        )
        assert bad["ok"] is False
        assert "not found" in bad["detail"]

    def test_history_trailer_lists_only_mutations_with_status(self):
        from app.routers.chat import _tool_events_history_trailer
        events = [
            {"tool": "codebase_read_file", "path": "x.md", "ok": True},  # read → excluded
            {"tool": "codebase_write_file", "path": "README.md", "ok": True, "new_path": None},
            {"tool": "codebase_delete_file", "path": "obrenna/README.md", "ok": True, "new_path": None},
            {"tool": "codebase_move_file", "path": "a.md", "new_path": "docs/a.md", "ok": True},
            {"tool": "codebase_edit_file", "path": "z.md", "ok": False, "detail": "not found", "new_path": None},
        ]
        trailer = _tool_events_history_trailer(events)
        assert "created README.md (ok)" in trailer
        assert "deleted obrenna/README.md (ok)" in trailer
        assert "moved a.md → docs/a.md (ok)" in trailer
        assert "edited z.md (FAILED: not found)" in trailer
        assert "x.md" not in trailer  # the read is not listed

    def test_history_trailer_empty_when_no_mutations(self):
        from app.routers.chat import _tool_events_history_trailer
        assert _tool_events_history_trailer(
            [{"tool": "codebase_read_file", "path": "x", "ok": True}]
        ) == ""
        assert _tool_events_history_trailer([]) == ""


class TestMalformedGuidance:
    """A cut-off large write must be steered toward 'minimal file then edits',
    not the generic 'shrink your edit' advice that made it retry the same
    oversized write and fail again (the Tic-Tac-Toe build failure)."""

    def test_write_file_gets_minimal_then_edit_advice(self):
        raw = '{"action":"tool_call","tool":"codebase_write_file","arguments":{"path":"tictactoe.py","content":"def check_winner(board):\\n    \\"\\"\\"'
        msg = _malformed_tool_call_guidance(raw)
        assert "tictactoe.py" in msg
        assert "skeleton" in msg.lower() or "minimal" in msg.lower()
        assert "codebase_edit_file" in msg
        assert "whole file" in msg.lower()

    def test_edit_file_gets_smaller_edit_advice(self):
        raw = '{"action":"tool_call","tool":"codebase_edit_file","arguments":{"path":"main.py","old_string":"..."'
        msg = _malformed_tool_call_guidance(raw)
        assert "main.py" in msg
        assert "smaller" in msg.lower()

    def test_unknown_tool_gets_generic_advice(self):
        msg = _malformed_tool_call_guidance('{"garbled')
        assert "could not be parsed" in msg.lower()
