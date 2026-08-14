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
