"""Compacting a tool result must not delete the part that carries the answer.

Every codebase_* result used to fall through to a blanket ``content[:budget]``.
Three consequences, all observed:

  * run_command's JSON is ordered command, cwd, exit_code, stdout, stderr,
    timed_out -- so a command with chatty stdout had its stderr and timed_out
    cut off entirely. The model saw output, no error, and reported success.
  * codebase_read_file was cut at an arbitrary byte, which is how a helper
    module could be read and still leave the model unsure what was in it.
  * codebase_search's JSON was cut mid-array, so the model got an arbitrary
    prefix of the matches with no sign that more existed.
"""
from __future__ import annotations

import json

from app.agent.runtime import (
    ResolvedPlan,
    _compact_tool_results,
    _run_command_failed,
    _trim_run_command,
    _trim_search_results,
    _trim_tool_result,
)


def run_command_payload(stdout: str = "", stderr: str = "", exit_code: int = 0, **extra) -> str:
    return json.dumps({
        "command": "Rscript -e \"source('shared/db_helpers.R')\"",
        "cwd": ".",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": False,
        **extra,
    })


class TestRunCommandKeepsTheVerdict:
    def test_a_flood_of_stdout_does_not_bury_the_error(self):
        content = run_command_payload(
            stdout="progress...\n" * 5000, stderr="could not connect to server", exit_code=1
        )
        trimmed = json.loads(_trim_run_command(content, 2000))

        assert trimmed["exit_code"] == 1, "the verdict must survive"
        assert trimmed["stderr"] == "could not connect to server"
        assert trimmed["timed_out"] is False

    def test_the_result_is_still_valid_json(self):
        """The old cut left a payload sliced mid-string, so nothing downstream
        could parse it -- including the failure detection below."""
        content = run_command_payload(stdout="x" * 50_000, stderr="boom", exit_code=2)
        json.loads(_trim_run_command(content, 1000))  # must not raise

    def test_both_ends_of_stdout_survive(self):
        content = run_command_payload(stdout="FIRST\n" + ("f" * 40_000) + "\nLAST")
        trimmed = json.loads(_trim_run_command(content, 3000))
        assert "FIRST" in trimmed["stdout"]
        assert "LAST" in trimmed["stdout"], "the end of a log is where the error is"
        assert "truncated" in trimmed["stdout"]

    def test_a_timeout_flag_is_never_dropped(self):
        content = json.dumps({
            "command": "python train.py", "cwd": ".", "exit_code": None,
            "stdout": "epoch...\n" * 8000, "stderr": "", "timed_out": True,
        })
        assert json.loads(_trim_run_command(content, 1500))["timed_out"] is True

    def test_small_results_pass_through_untouched(self):
        content = run_command_payload(stdout="4\n")
        assert json.loads(_trim_run_command(content, 4000)) == json.loads(content)

    def test_an_enormous_stderr_keeps_its_tail(self):
        content = run_command_payload(stderr="warning\n" * 9000 + "FATAL: role does not exist")
        trimmed = json.loads(_trim_run_command(content, 2000))
        assert "FATAL: role does not exist" in trimmed["stderr"]

    def test_a_dispatch_error_payload_is_left_alone(self):
        content = json.dumps({"error": True, "message": "This device is no longer approved."})
        assert json.loads(_trim_run_command(content, 4000))["message"].startswith("This device")

    def test_non_json_falls_back_rather_than_raising(self):
        assert _trim_run_command("Tool error: boom", 4000) == "Tool error: boom"


class TestSearchResultsKeepEveryMatch:
    def make(self, n: int, line_len: int = 400) -> str:
        return json.dumps({
            "matches": [
                {"path": f"src/mod{i}.R", "line_number": i, "line": "x" * line_len,
                 "before": ["b" * line_len], "after": ["a" * line_len]}
                for i in range(n)
            ],
            "match_count": n,
            "backend": "ripgrep",
        })

    def test_no_match_is_dropped(self):
        trimmed = json.loads(_trim_search_results(self.make(40), 2000))
        assert len(trimmed["matches"]) == 40, "which files contain it IS the answer"

    def test_paths_and_line_numbers_survive_intact(self):
        trimmed = json.loads(_trim_search_results(self.make(40), 2000))
        assert trimmed["matches"][7]["path"] == "src/mod7.R"
        assert trimmed["matches"][7]["line_number"] == 7

    def test_context_is_sacrificed_before_matches_are(self):
        trimmed = json.loads(_trim_search_results(self.make(60), 1200))
        assert len(trimmed["matches"]) == 60
        assert "before" not in trimmed["matches"][0]

    def test_context_is_kept_when_there_is_room(self):
        trimmed = json.loads(_trim_search_results(self.make(2), 4000))
        assert trimmed["matches"][0]["before"]

    def test_the_diagnostics_survive(self):
        """These are what let an empty or capped result be read correctly."""
        trimmed = json.loads(_trim_search_results(self.make(40), 1500))
        assert trimmed["backend"] == "ripgrep"
        assert trimmed["match_count"] == 40

    def test_output_stays_parseable(self):
        json.loads(_trim_search_results(self.make(200), 800))


class TestRouting:
    def test_each_codebase_tool_gets_its_own_shape_aware_trim(self):
        content = run_command_payload(stdout="y" * 30_000, stderr="ERR", exit_code=1)
        routed = _trim_tool_result("codebase_run_command", content, 2000)
        assert json.loads(routed)["stderr"] == "ERR"

    def test_read_file_keeps_head_and_tail(self):
        body = "import os\n" + ("#\n" * 20_000) + "def last_function():\n"
        trimmed = _trim_tool_result("codebase_read_file", body, 2000)
        assert trimmed.startswith("import os")
        assert trimmed.endswith("def last_function():\n"), "the end of a file matters too"

    def test_an_unknown_tool_still_gets_bounded(self):
        assert len(_trim_tool_result("something_new", "z" * 10_000, 500)) < 600

    def test_compaction_applies_it_through_the_real_entry_point(self):
        results = [{"tool_name": "codebase_run_command",
                    "content": run_command_payload(stdout="q" * 20_000, stderr="FAILED")}]
        calls = [{"function": {"name": "codebase_run_command"}}]
        raw, compacted = _compact_tool_results(results, calls, 2000)

        assert compacted < raw
        assert json.loads(results[0]["content"])["stderr"] == "FAILED"


class TestTheBudgetFollowsTheHardware:
    """A budget fixed at the worst case is what starved capable machines.

    The 9B orchestrator serves tiers from ctx_min 8192 up to ctx_max 65536, so
    its single catalog number has to assume the smallest. Every machine then
    got ~1500 tokens per tool result regardless of the window it actually had.
    """

    def plan(self, ctx: int, catalog_budget: int = 6000) -> ResolvedPlan:
        return ResolvedPlan({
            "orchestrator": {"model": "m", "tool_result_budget": catalog_budget},
            "ctx": ctx,
        })

    def test_a_bigger_window_gets_a_bigger_budget(self):
        small = self.plan(8192).tool_result_budget
        large = self.plan(16384).tool_result_budget
        assert large > small
        assert large > 6000, "the catalog worst case must not cap capable hardware"

    def test_the_catalog_value_is_a_floor_not_a_ceiling(self):
        assert self.plan(2048, catalog_budget=9000).tool_result_budget == 9000

    def test_a_result_never_swallows_the_whole_window(self):
        for ctx in (8192, 16384, 32768, 65536):
            budget_tokens = self.plan(ctx).tool_result_budget / 4
            assert budget_tokens <= ctx * 0.25, f"ctx={ctx} would leave no room to answer"

    def test_a_missing_ctx_falls_back_to_the_catalog(self):
        assert ResolvedPlan({"orchestrator": {"tool_result_budget": 5000}}).tool_result_budget >= 5000

    def test_a_nonsense_catalog_value_does_not_produce_a_zero_budget(self):
        assert ResolvedPlan(
            {"orchestrator": {"tool_result_budget": 0}, "ctx": 8192}
        ).tool_result_budget > 0


class TestFailureDetectionSeesTruncatedFailures:
    def test_a_nonzero_exit_is_a_failure(self):
        assert _run_command_failed(run_command_payload(exit_code=1)) is True

    def test_success_is_not(self):
        assert _run_command_failed(run_command_payload(exit_code=0)) is False

    def test_a_bare_tool_error_string_counts_as_failure(self):
        """Produced by an unhandled exception in the tool loop. It used to read
        as success, so the model was free to retry the same broken call."""
        assert _run_command_failed("Tool error: invalid literal for int()") is True

    def test_a_payload_cut_mid_json_counts_as_failure(self):
        assert _run_command_failed(run_command_payload(stdout="x" * 100)[:60]) is True

    def test_empty_content_is_not_treated_as_a_failure(self):
        assert _run_command_failed("") is False
