"""The same lookup, re-issued every round until the turn runs out.

Observed against a real project. Asked which file defines get_db_connection and
where the schema doc is, the model found the answer on round 2 --
shared/db_helpers.R:316 -- and then issued this identical call eight more times:

    codebase_search {"pattern": "^get_db_connection\\s*<-|get_db_connection\\s*:=",
                     "regex": true}

It spent the entire round budget re-confirming what it already had, never got to
the second half of the question, and ended mid-sentence on "Let me look for...".
Raising the round cap made this worse, not better: more rounds is more rope.

Re-dispatching an identical read-only call cannot return anything new, so it is
answered from the first result with an instruction to do something different.
"""
from __future__ import annotations

import json

import pytest

from app.agent.runtime import _call_signature, handle_tool_calls


class FakeMCP:
    """Counts real dispatches so suppression is observable."""

    def __init__(self, result=None):
        self.calls: list[tuple[str, dict]] = []
        self.result = result if result is not None else {"matches": [{"path": "shared/db_helpers.R"}]}

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.result


def call(tool: str, args: dict, call_id: str = "c1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": tool, "arguments": args}}


class TestSignature:
    def test_identical_calls_share_a_signature(self):
        a = _call_signature("web_search", {"query": "x", "n": 1})
        b = _call_signature("web_search", {"n": 1, "query": "x"})
        assert a == b, "key order must not make a repeat look novel"

    def test_different_arguments_differ(self):
        assert _call_signature("web_search", {"query": "a"}) != _call_signature("web_search", {"query": "b"})

    def test_commands_and_writes_are_never_deduped(self):
        """Re-running tests after a fix is the whole point of the tool loop, and
        a cached 'it passed' would be a lie about the disk."""
        for tool in ("codebase_run_command", "codebase_write_file", "codebase_edit_file",
                     "codebase_delete_file", "codebase_move_file"):
            assert _call_signature(tool, {"command": "npm test"}) == ""

    def test_read_only_lookups_are_deduped(self):
        for tool in ("codebase_search", "codebase_read_file", "codebase_list_directory",
                     "web_search", "file_read"):
            assert _call_signature(tool, {"path": "a"}) != ""

    def test_exotic_argument_values_do_not_raise(self):
        """Args come from model output and can be anything; a signature failure
        must degrade to "not de-duped", never to a crashed turn."""
        assert isinstance(_call_signature("web_search", {"q": object()}), str)


@pytest.mark.asyncio
class TestRepeatSuppression:
    async def test_the_observed_loop_dispatches_once(self):
        mcp = FakeMCP()
        history: dict[str, str] = {}
        args = {"pattern": r"^get_db_connection\s*<-|get_db_connection\s*:=", "regex": True}

        for round_no in range(8):
            await handle_tool_calls(
                [call("codebase_search", args, f"c{round_no}")], mcp, call_history=history,
            )

        assert len(mcp.calls) == 1, f"the search ran {len(mcp.calls)} times; it should run once"

    async def test_the_repeat_still_gets_the_answer_back(self):
        """Suppression must not starve the model of the result it needs."""
        mcp = FakeMCP()
        history: dict[str, str] = {}
        await handle_tool_calls([call("codebase_search", {"pattern": "x"})], mcp, call_history=history)
        again = await handle_tool_calls(
            [call("codebase_search", {"pattern": "x"}, "c2")], mcp, call_history=history,
        )
        payload = json.loads(again[0]["content"])
        assert payload["repeated_call"] is True
        assert "shared/db_helpers.R" in payload["original_result"]

    async def test_it_is_told_to_do_something_different(self):
        mcp = FakeMCP()
        history: dict[str, str] = {}
        await handle_tool_calls([call("codebase_search", {"pattern": "x"})], mcp, call_history=history)
        again = await handle_tool_calls(
            [call("codebase_search", {"pattern": "x"}, "c2")], mcp, call_history=history,
        )
        message = json.loads(again[0]["content"])["message"]
        assert "already ran" in message
        assert "DIFFERENT" in message

    async def test_a_different_pattern_is_dispatched_normally(self):
        mcp = FakeMCP()
        history: dict[str, str] = {}
        await handle_tool_calls([call("codebase_search", {"pattern": "a"})], mcp, call_history=history)
        await handle_tool_calls([call("codebase_search", {"pattern": "b"}, "c2")], mcp, call_history=history)
        assert len(mcp.calls) == 2, "changing the search must still reach the tool"

    async def test_a_command_repeats_as_many_times_as_asked(self):
        mcp = FakeMCP(result={"exit_code": 0, "stdout": "ok"})
        history: dict[str, str] = {}
        for i in range(3):
            await handle_tool_calls(
                [call("codebase_run_command", {"command": "npm test"}, f"c{i}")],
                mcp, call_history=history,
            )
        assert len(mcp.calls) == 3, "re-running a command after an edit must actually re-run it"

    async def test_results_stay_in_call_order_when_a_round_mixes_new_and_repeat(self):
        mcp = FakeMCP()
        history: dict[str, str] = {}
        await handle_tool_calls([call("codebase_search", {"pattern": "a"})], mcp, call_history=history)
        results = await handle_tool_calls(
            [
                call("codebase_search", {"pattern": "a"}, "r1"),
                call("codebase_search", {"pattern": "new"}, "r2"),
            ],
            mcp, call_history=history,
        )
        assert [r["tool_call_id"] for r in results] == ["r1", "r2"]
        assert json.loads(results[0]["content"]).get("repeated_call") is True
        assert json.loads(results[1]["content"]).get("repeated_call") is None

    async def test_without_history_nothing_is_suppressed(self):
        """Callers that don't pass history (older paths, tests) are unaffected."""
        mcp = FakeMCP()
        for i in range(3):
            await handle_tool_calls([call("codebase_search", {"pattern": "x"}, f"c{i}")], mcp)
        assert len(mcp.calls) == 3

    async def test_a_failed_call_is_not_cached_as_the_answer(self):
        """A transient failure must stay retryable, or one blip poisons the turn."""
        class Failing:
            def __init__(self):
                self.n = 0

            async def call_tool(self, name, args):
                self.n += 1
                if self.n == 1:
                    raise RuntimeError("device disconnected")
                return {"matches": [{"path": "found.R"}]}

        mcp = Failing()
        history: dict[str, str] = {}
        await handle_tool_calls([call("codebase_search", {"pattern": "x"})], mcp, call_history=history)
        again = await handle_tool_calls(
            [call("codebase_search", {"pattern": "x"}, "c2")], mcp, call_history=history,
        )
        assert "found.R" in again[0]["content"], "the retry after a failure must really run"
