"""codebase_search: the tool the model uses to find out what exists.

This file exists because there were no tests here at all, and a total failure
shipped undetected. On Windows the ripgrep backend parsed its output with
``line.split(":", 2)`` against an absolute search root, so every line began
"C:\\..." and the drive letter's colon was eaten as the field separator: the
"line number" became the rest of the path and ``int()`` on it raised out of the
entire call. Every match of every query, on every machine with rg installed --
and never locally, because rg is not on the dev box's PATH so the Python
fallback ran instead.

The user-visible symptom was the model searching for a function, being handed
nothing, and concluding a function that plainly exists only "potentially" does.
"""
from __future__ import annotations

import json
import shutil
import sys

import pytest

from codebase_agent.dispatch import _LIST_ENTRY_CAP  # noqa: F401  (documents the cap under test)
from codebase_agent.search import (
    SearchMatch,
    _attach_context,
    _parse_ripgrep_json,
    _search_with_python,
    search_codebase,
)

HAS_RG = shutil.which("rg") is not None
needs_rg = pytest.mark.skipif(not HAS_RG, reason="ripgrep not installed")


def rg_stream(*events: dict) -> str:
    """rg --json emits one JSON object per line."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


def match_event(path: str, line_number: int, text: str) -> dict:
    return {
        "type": "match",
        "data": {
            "path": {"text": path},
            "lines": {"text": text + "\n"},
            "line_number": line_number,
            "absolute_offset": 0,
            "submatches": [],
        },
    }


@pytest.fixture
def project(tmp_path):
    """A project shaped like the one that triggered the failure."""
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "db_helpers.R").write_text(
        "library(DBI)\n"
        "library(RPostgres)\n"
        "\n"
        "get_db_connection <- function() {\n"
        "  dbConnect(RPostgres::Postgres(), host = Sys.getenv('DB_HOST'))\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "app.R").write_text(
        "source('shared/db_helpers.R')\nconn <- get_db_connection()\n", encoding="utf-8"
    )
    return tmp_path


class TestRipgrepOutputParsing:
    """The regression. Parses captured rg output, so it runs without rg."""

    def test_absolute_path_yields_the_real_relative_path_and_line(self, project):
        absolute = str(project / "shared" / "db_helpers.R")
        outcome = _parse_ripgrep_json(
            rg_stream(
                {"type": "begin", "data": {"path": {"text": absolute}}},
                match_event(absolute, 4, "get_db_connection <- function() {"),
                {"type": "end", "data": {"path": {"text": absolute}}},
                {"type": "summary", "data": {"stats": {"searches": 1423}}},
            ),
            project,
            max_results=100,
        )

        assert len(outcome.matches) == 1, "an absolute search root must not lose its matches"
        found = outcome.matches[0]
        assert found.path == "shared/db_helpers.R"
        assert found.line_number == 4
        assert "get_db_connection" in found.line

    @pytest.mark.skipif(sys.platform != "win32", reason="drive letters only exist on Windows")
    def test_the_drive_letter_is_what_broke_the_old_parser(self, project):
        """Documents why this backend reads --json instead of `path:line:text`."""
        line = f"{project / 'app.R'}:2:conn <- get_db_connection()"
        parts = line.split(":", 2)
        assert parts[0] == str(project)[0], "the drive letter is consumed as field one"
        with pytest.raises(ValueError):
            int(parts[1])  # the old code did exactly this, uncaught

    def test_counts_the_files_that_matched(self, project):
        first, second = str(project / "app.R"), str(project / "shared" / "db_helpers.R")
        outcome = _parse_ripgrep_json(
            rg_stream(
                {"type": "begin", "data": {"path": {"text": first}}},
                match_event(first, 2, "conn <- get_db_connection()"),
                {"type": "begin", "data": {"path": {"text": second}}},
                match_event(second, 4, "get_db_connection <- function() {"),
                {"type": "summary", "data": {"stats": {"searches": 2}}},
            ),
            project,
            max_results=100,
        )
        assert outcome.files_with_matches == 2
        assert outcome.backend == "ripgrep"

    def test_files_scanned_is_unknown_not_zero(self, project):
        """rg's summary counts files that MATCHED, so it says 0 on a miss.

        Reporting that as files_scanned would tell the caller "I looked at
        nothing" when the truth is "I looked and it isn't there" -- or worse,
        the reverse. Unknown must stay unknown until it is actually measured.
        """
        outcome = _parse_ripgrep_json(
            rg_stream({"type": "summary", "data": {"stats": {"searches": 0}}}),
            project,
            max_results=100,
        )
        assert outcome.files_scanned is None

    def test_results_are_capped_and_say_so(self, project):
        absolute = str(project / "app.R")
        events = [match_event(absolute, i, f"line {i}") for i in range(1, 12)]
        outcome = _parse_ripgrep_json(rg_stream(*events), project, max_results=5)
        assert len(outcome.matches) == 5
        assert outcome.truncated is True

    def test_paths_outside_the_project_are_dropped(self, project):
        outcome = _parse_ripgrep_json(
            rg_stream(match_event(str(project.parent / "elsewhere.R"), 1, "x")),
            project,
            max_results=100,
        )
        assert outcome.matches == []

    def test_malformed_lines_do_not_sink_the_whole_result(self, project):
        absolute = str(project / "app.R")
        stream = "not json\n" + rg_stream(match_event(absolute, 2, "conn <- get_db_connection()"))
        outcome = _parse_ripgrep_json(stream, project, max_results=100)
        assert len(outcome.matches) == 1

    def test_non_utf8_text_arrives_base64_encoded(self, project):
        import base64

        absolute = str(project / "app.R")
        event = match_event(absolute, 2, "placeholder")
        event["data"]["lines"] = {"bytes": base64.b64encode("café".encode()).decode()}
        outcome = _parse_ripgrep_json(rg_stream(event), project, max_results=100)
        assert outcome.matches[0].line == "café"


class TestFindsWhatExists:
    """End-to-end through whichever backend is installed."""

    def test_finds_a_function_definition_in_an_r_file(self, project):
        outcome = search_codebase(project, "get_db_connection")
        paths = {m.path for m in outcome.matches}
        assert "shared/db_helpers.R" in paths, f"backend={outcome.backend} found {paths}"

    def test_context_lines_distinguish_a_definition_from_a_call_site(self, project):
        outcome = search_codebase(project, "get_db_connection", context=2)
        definition = next(m for m in outcome.matches if m.path == "shared/db_helpers.R")
        assert definition.before, "a match with no surroundings can't be classified"
        assert any("dbConnect" in line for line in definition.after)

    def test_context_can_be_switched_off(self, project):
        outcome = search_codebase(project, "get_db_connection", context=0)
        assert all(not m.before and not m.after for m in outcome.matches)

    def test_literal_mode_does_not_treat_the_pattern_as_regex(self, project):
        (project / "calc.py").write_text("total = a.b(c)\n", encoding="utf-8")
        assert search_codebase(project, "a.b(c)", regex=False).matches
        # As a regex the same string means something else entirely.
        assert not search_codebase(project, r"a\.b\(c\)x", regex=True).matches

    def test_invalid_regex_explains_itself(self, project):
        # re.error is not a ValueError, so this used to escape the caller's
        # handler and surface as an unexplained "unexpected error".
        with pytest.raises(ValueError, match="Invalid regular expression"):
            search_codebase(project, "get_db_connection(")

    def test_hidden_dotfiles_are_searchable(self, project):
        """.env is hidden AND gitignored -- the two things rg skips by default.

        The prompt tells the model to go find how the project connects; if
        search can't see .env that instruction is unfollowable.
        """
        (project / ".env").write_text("DB_HOST=metrics.internal\n", encoding="utf-8")
        outcome = search_codebase(project, "DB_HOST")
        assert ".env" in {m.path for m in outcome.matches}, f"backend={outcome.backend}"

    def test_a_leading_dash_is_a_pattern_not_a_flag(self, project):
        (project / "notes.txt").write_text("--max-count is per file\n", encoding="utf-8")
        outcome = search_codebase(project, "--max-count", regex=False)
        assert "notes.txt" in {m.path for m in outcome.matches}

    def test_excluded_directories_stay_excluded(self, project):
        (project / "node_modules").mkdir()
        (project / "node_modules" / "junk.R").write_text("get_db_connection\n", encoding="utf-8")
        outcome = search_codebase(project, "get_db_connection")
        assert all("node_modules" not in m.path for m in outcome.matches)


@needs_rg
class TestRipgrepIsActuallyReachable:
    """rg must survive the environment the agent really runs in.

    The agent is launched detached, so it has no usable stdin handle. On Windows
    a child that inherits one fails with "The handle is invalid", the OSError is
    swallowed as a fallback, and rg silently never runs -- which would have kept
    the parsing fix above from ever taking effect in production.
    """

    def test_rg_runs_without_an_inheritable_stdin(self, project):
        outcome = search_codebase(project, "get_db_connection")
        assert outcome.backend == "ripgrep", (
            "rg is installed but was not used -- the subprocess spawn is failing"
        )


@needs_rg
class TestBackendsAgree:
    """Same query, same answer, whichever backend the connected machine has.

    Divergence here is how a search silently changes behaviour when a user
    installs ripgrep.
    """

    @pytest.mark.parametrize("pattern", ["get_db_connection", "DB_HOST", "dbConnect"])
    def test_ripgrep_and_python_return_the_same_matches(self, project, pattern):
        (project / ".env").write_text("DB_HOST=metrics.internal\n", encoding="utf-8")

        with_rg = search_codebase(project, pattern)
        assert with_rg.backend == "ripgrep"
        fallback = _search_with_python(project, project, pattern, True, False, 100)
        _attach_context(fallback.matches, project, 2)

        def key(outcome):
            return sorted((m.path, m.line_number, m.line.strip()) for m in outcome.matches)

        assert key(with_rg) == key(fallback)


class TestEmptyResultsAreDiagnosable:
    """An empty list must not be readable as proof of absence."""

    def test_a_genuine_miss_reports_what_was_examined(self, project):
        """Both backends must be able to say how much they looked at when they
        found nothing -- that is the only moment the number matters."""
        outcome = search_codebase(project, "no_such_symbol_anywhere")
        assert outcome.matches == []
        assert outcome.files_scanned is not None, f"backend={outcome.backend} cannot say"
        assert outcome.files_scanned > 0, "must show that files were actually examined"

    def test_the_dispatch_payload_carries_the_caveat(self, project, monkeypatch):
        from codebase_agent import dispatch

        monkeypatch.setattr(dispatch, "_get_project_root", lambda pid: (project, None))
        payload = dispatch.op_search({"project_id": "p", "pattern": "no_such_symbol_anywhere"})
        assert payload["match_count"] == 0
        assert payload["files_scanned"] > 0
        assert "NOT proof" in payload["note"]
        assert payload["backend"] in {"ripgrep", "python"}

    def test_a_hit_carries_no_scare_note(self, project, monkeypatch):
        from codebase_agent import dispatch

        monkeypatch.setattr(dispatch, "_get_project_root", lambda pid: (project, None))
        payload = dispatch.op_search({"project_id": "p", "pattern": "get_db_connection"})
        assert payload["match_count"] >= 1
        assert "note" not in payload


class TestContextAttachment:
    def test_reads_each_file_once_and_bounds_the_edges(self, project):
        matches = [
            SearchMatch(path="shared/db_helpers.R", line_number=1, line="library(DBI)"),
            SearchMatch(path="shared/db_helpers.R", line_number=6, line="}"),
        ]
        _attach_context(matches, project, 2)
        assert matches[0].before == [], "line 1 has nothing above it"
        assert matches[0].after == ["library(RPostgres)", ""]
        assert matches[1].after == [], "the last line has nothing below it"

    def test_a_vanished_file_does_not_raise(self, project):
        matches = [SearchMatch(path="gone.R", line_number=3, line="x")]
        _attach_context(matches, project, 2)
        assert matches[0].before == []
