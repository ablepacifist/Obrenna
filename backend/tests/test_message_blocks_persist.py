"""Tests for persisted render blocks (the reason edit diffs survive a reload).

``tool_events`` is a compact audit trail for the model's own context and
deliberately drops old_string/new_string. Before blocks existed that was the
ONLY per-tool record persisted, so on reload the UI had nothing left to draw a
diff from and every edit collapsed to flat prose. These pin the fix.
"""
from __future__ import annotations

import json

from app.routers.chat import (
    _BLOCK_ARG_MAX_CHARS,
    _BlockAccumulator,
    _render_args_for_block,
    _summarize_tool_event,
)


def test_edit_diff_detail_is_kept_in_blocks():
    args = {
        "path": "SETUP.md",
        "old_string": "TODO",
        "new_string": "Run npm run dev",
        "irrelevant": "drop me",
    }
    kept = _render_args_for_block("codebase_edit_file", args)
    assert kept["old_string"] == "TODO"
    assert kept["new_string"] == "Run npm run dev"
    assert kept["path"] == "SETUP.md"
    # Only render-relevant args survive.
    assert "irrelevant" not in kept


def test_tool_events_still_drops_diff_detail():
    """The two records have different jobs; blocks must not be conflated with
    tool_events, which stays compact because it is replayed into the prompt."""
    ev = _summarize_tool_event(
        "codebase_edit_file",
        {"path": "SETUP.md", "old_string": "TODO", "new_string": "done"},
        json.dumps({"change_id": "x"}),
    )
    assert "old_string" not in ev
    assert "new_string" not in ev
    assert ev["path"] == "SETUP.md"
    assert ev["ok"] is True


def test_huge_content_is_capped():
    big = "x" * (_BLOCK_ARG_MAX_CHARS + 5000)
    kept = _render_args_for_block("codebase_write_file", {"path": "a.txt", "content": big})
    assert len(kept["content"]) < len(big)
    assert kept["content"].endswith("… (truncated)")


def test_accumulator_interleaves_text_and_tools_in_order():
    acc = _BlockAccumulator()
    acc.add_token("Let me check ")
    acc.add_token("that file.")
    acc.add_tool_call("c1", "codebase_read_file", {"path": "a.py"})
    acc.finish_tool("c1", json.dumps({"content": "..."}))
    acc.add_token("Now editing.")
    acc.add_tool_call("c2", "codebase_edit_file", {
        "path": "a.py", "old_string": "old", "new_string": "new",
    })
    acc.finish_tool("c2", json.dumps({"change_id": "abc"}))
    acc.add_token("Done.")

    blocks = acc.result()
    assert [b["kind"] for b in blocks] == ["text", "tool", "text", "tool", "text"]
    # Consecutive tokens coalesce into one run.
    assert blocks[0]["text"] == "Let me check that file."
    assert blocks[3]["toolName"] == "codebase_edit_file"
    assert blocks[3]["status"] == "done"
    # The diff detail the UI needs is present.
    assert blocks[3]["args"]["old_string"] == "old"
    assert blocks[3]["args"]["new_string"] == "new"


def test_failed_tool_marked_error_with_message():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_edit_file", {"path": "a.py"})
    acc.finish_tool("c1", json.dumps({"error": True, "message": "no such file"}))
    block = acc.result()[0]
    assert block["status"] == "error"
    assert block["summary"] == "no such file"


def test_narration_attaches_to_the_matching_card():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_read_file", {"path": "a.py"})
    acc.add_narration("c1", "Reading a.py to find the bug")
    acc.add_narration("nonexistent", "should be ignored")
    block = acc.result()[0]
    assert block["description"] == "Reading a.py to find the bug"


def test_trailing_blank_text_is_dropped():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_read_file", {"path": "a.py"})
    acc.finish_tool("c1", "{}")
    acc.add_token("   \n ")
    assert [b["kind"] for b in acc.result()] == ["tool"]


def test_non_json_result_is_treated_as_success():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "web_search", {})
    acc.finish_tool("c1", "plain text result")
    assert acc.result()[0]["status"] == "done"


def test_ask_user_question_is_kept_for_replay():
    kept = _render_args_for_block("ask_user", {
        "question": "Which file?", "options": ["a", "b"],
    })
    assert kept["question"] == "Which file?"
    assert kept["options"] == ["a", "b"]


# ── what the user watched, replayed ───────────────────────────────────────────
# The reported symptom was a reloaded transcript of bare tool labels: a card
# saying "codebase_search" with nothing under it, and a card saying it ran a
# command but never showing what the command printed. Two separate causes: the
# read-only tools' arguments were dropped by the keep-list before persistence,
# and no tool result beyond an error `message` was stored at all.


def test_search_pattern_survives_to_the_transcript():
    """Without `pattern` the persisted args are {} and the card is a bare name."""
    kept = _render_args_for_block("codebase_search", {"pattern": "get_db_connection", "regex": False})
    assert kept["pattern"] == "get_db_connection"
    assert kept["regex"] is False


def test_read_and_list_arguments_survive():
    assert _render_args_for_block("codebase_read_file", {"path": "a.R", "offset": 40})["offset"] == 40
    assert _render_args_for_block("codebase_list_directory", {"path": "shared", "recursive": True})["recursive"] is True


def test_command_output_is_persisted_not_just_the_command():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_run_command", {"command": "Rscript -e 'dbListTables(con)'"})
    acc.finish_tool("c1", json.dumps({
        "command": "Rscript -e 'dbListTables(con)'", "cwd": ".", "exit_code": 0,
        "stdout": "loc_catchbasin\nbreeding_sites", "stderr": "", "timed_out": False,
    }))
    result = acc.result()[0]["result"]
    assert result["exitCode"] == 0
    assert "loc_catchbasin" in result["stdout"]


def test_a_failing_command_keeps_its_stderr():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_run_command", {"command": "Rscript bad.R"})
    acc.finish_tool("c1", json.dumps({
        "exit_code": 1, "stdout": "", "stderr": "could not connect to server", "timed_out": False,
    }))
    result = acc.result()[0]["result"]
    assert result["exitCode"] == 1
    assert result["stderr"] == "could not connect to server"


def test_long_output_keeps_its_tail():
    """The error is at the bottom of a log, so the tail is the part to keep."""
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_run_command", {"command": "npm run build"})
    acc.finish_tool("c1", json.dumps({
        "exit_code": 1, "stdout": "step\n" * 5000 + "FINAL FAILURE", "stderr": "", "timed_out": False,
    }))
    assert "FINAL FAILURE" in acc.result()[0]["result"]["stdout"]


def test_search_result_records_where_it_looked():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_search", {"pattern": "get_db_connection"})
    acc.finish_tool("c1", json.dumps({"matches": [
        {"path": "shared/db_helpers.R", "line_number": 4, "line": "get_db_connection <- function() {"},
        {"path": "shared/db_helpers.R", "line_number": 9, "line": "  get_db_connection()"},
        {"path": "app.R", "line_number": 2, "line": "conn <- get_db_connection()"},
    ], "match_count": 3, "truncated": False}))
    result = acc.result()[0]["result"]
    assert result["matchCount"] == 3
    assert result["paths"] == ["shared/db_helpers.R", "app.R"]


def test_an_empty_search_is_recorded_as_a_real_zero():
    acc = _BlockAccumulator()
    acc.add_tool_call("c1", "codebase_search", {"pattern": "nope"})
    acc.finish_tool("c1", json.dumps({"matches": [], "match_count": 0}))
    assert acc.result()[0]["result"]["matchCount"] == 0


def test_reasoning_is_persisted_in_the_cadence_it_happened_in():
    """Thinking used to be streamed and discarded, so "what were you thinking"
    had no answer once the turn ended."""
    acc = _BlockAccumulator()
    acc.add_thinking("The user wants sites dry for two years. ")
    acc.add_thinking("I should check the real schema first.")
    acc.add_tool_call("c1", "codebase_search", {"pattern": "status_udw"})
    acc.finish_tool("c1", json.dumps({"matches": []}))
    acc.add_token("Checking the schema.")

    kinds = [b["kind"] for b in acc.result()]
    assert kinds == ["thinking", "tool", "text"]
    assert acc.result()[0]["text"].startswith("The user wants sites dry")


def test_reasoning_is_bounded():
    from app.routers.chat import _BLOCK_THINKING_MAX_CHARS
    acc = _BlockAccumulator()
    for _ in range(200):
        acc.add_thinking("x" * 1000)
    assert len(acc.result()[0]["text"]) < _BLOCK_THINKING_MAX_CHARS + 1000


def test_blank_reasoning_does_not_create_an_empty_pane():
    acc = _BlockAccumulator()
    acc.add_thinking("   \n  ")
    acc.add_token("answer")
    assert [b["kind"] for b in acc.result()] == ["text"]
