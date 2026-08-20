"""A wrong path must point at the right one, not dead-end.

Taken from a real session against an R/Shiny project. The model called
codebase_read_file("DATABASE_SCHEMA_REFERENCE.md") -- a bare filename for a file
that lives in docs/ -- and got back exactly:

    {"error": true, "message": "Not a file: DATABASE_SCHEMA_REFERENCE.md"}

There is nothing in that to act on. It reads as "this project does not contain
that file", and the model passed that straight to the user: "I haven't found
the schema documentation you mentioned... any SQL I provide would be
speculative." The file was one directory down the whole time.
"""
from __future__ import annotations

import pytest

from codebase_agent import dispatch
from codebase_agent.fs_tools import find_by_basename


@pytest.fixture
def project(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "DATABASE_SCHEMA_REFERENCE.md").write_text(
        "# Schema\nloc_catchbasin.status_udw\n", encoding="utf-8"
    )
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "db_helpers.R").write_text(
        "get_db_connection <- function() {}\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def read(project, monkeypatch):
    monkeypatch.setattr(dispatch, "_get_project_root", lambda pid: (project, None))

    def _read(path: str):
        return dispatch.op_read_file({"project_id": "p", "path": path})

    return _read


class TestFindByBasename:
    def test_finds_a_file_one_directory_down(self, project):
        assert find_by_basename(project, "DATABASE_SCHEMA_REFERENCE.md") == [
            "docs/DATABASE_SCHEMA_REFERENCE.md"
        ]

    def test_matching_is_case_insensitive(self, project):
        assert find_by_basename(project, "database_schema_reference.md")

    def test_a_full_wrong_path_still_matches_on_its_basename(self, project):
        """The model often guesses a plausible-but-wrong directory."""
        assert find_by_basename(project, "reference/DATABASE_SCHEMA_REFERENCE.md") == [
            "docs/DATABASE_SCHEMA_REFERENCE.md"
        ]

    def test_a_genuinely_absent_file_returns_nothing(self, project):
        assert find_by_basename(project, "NOT_A_REAL_FILE.md") == []

    def test_excluded_directories_are_not_searched(self, project):
        (project / "node_modules").mkdir()
        (project / "node_modules" / "README.md").write_text("x", encoding="utf-8")
        assert find_by_basename(project, "README.md") == []

    def test_several_matches_are_all_offered(self, project):
        (project / "a").mkdir()
        (project / "b").mkdir()
        (project / "a" / "utils.R").write_text("x", encoding="utf-8")
        (project / "b" / "utils.R").write_text("x", encoding="utf-8")
        assert sorted(find_by_basename(project, "utils.R")) == ["a/utils.R", "b/utils.R"]

    def test_an_empty_name_is_not_a_wildcard(self, project):
        assert find_by_basename(project, "") == []


class TestReadFileRedirects:
    def test_the_exact_failure_now_names_the_real_path(self, read):
        result = read("DATABASE_SCHEMA_REFERENCE.md")
        assert result["error"] is True
        assert "docs/DATABASE_SCHEMA_REFERENCE.md" in result["message"]
        assert result["did_you_mean"] == ["docs/DATABASE_SCHEMA_REFERENCE.md"]

    def test_the_error_is_marked_retryable(self, read):
        """Otherwise the tool loop treats a recoverable miss as terminal."""
        assert read("DATABASE_SCHEMA_REFERENCE.md")["retryable"] is True

    def test_a_truly_missing_file_forbids_concluding_absence(self, read):
        result = read("NOT_A_REAL_FILE.md")
        assert result["error"] is True
        assert "did_you_mean" not in result
        # The whole point: it must not stop here and report the file missing.
        assert "Do NOT conclude it is missing" in result["message"]
        assert "codebase_search" in result["message"]

    def test_the_original_reason_is_preserved(self, read):
        assert "Not a file" in read("NOT_A_REAL_FILE.md")["message"]

    def test_a_correct_path_still_just_works(self, read):
        result = read("docs/DATABASE_SCHEMA_REFERENCE.md")
        assert not result.get("error")
        assert "loc_catchbasin" in result["content"]

    def test_escaping_the_project_root_is_still_refused_outright(self, read):
        """A traversal attempt must not be answered with a helpful file list."""
        result = read("../../../etc/passwd")
        assert result["error"] is True
        assert "did_you_mean" not in result


class TestDestructiveOpsDoNotGetSuggestions:
    """Pointing a delete at a substitute path invites destroying the wrong file."""

    def test_delete_of_a_missing_path_offers_no_alternative(self, project, monkeypatch):
        monkeypatch.setattr(dispatch, "_require_write_enabled", lambda pid: (project, None))
        result = dispatch.op_delete_file({"project_id": "p", "path": "DATABASE_SCHEMA_REFERENCE.md"})
        assert result["error"] is True
        assert "did_you_mean" not in result

    def test_move_of_a_missing_path_offers_no_alternative(self, project, monkeypatch):
        monkeypatch.setattr(dispatch, "_require_write_enabled", lambda pid: (project, None))
        result = dispatch.op_move_file(
            {"project_id": "p", "path": "db_helpers.R", "new_path": "x.R"}
        )
        assert result["error"] is True
        assert "did_you_mean" not in result


# ── finding a file by its NAME ────────────────────────────────────────────────
# codebase_search only ever looked inside files. Asked "where is the database
# schema reference document?", the model searched file CONTENTS for
# 'SCHEMA|TABLES|database.*doc' and never found
# documents/DATABASE_SCHEMA_REFERENCE.md, because no tool could match a
# filename. It then told the user the documentation did not exist.


class TestFindFiles:
    def test_a_short_fragment_finds_the_schema_document(self, project):
        from codebase_agent.fs_tools import find_files
        assert find_files(project, "schema") == ["docs/DATABASE_SCHEMA_REFERENCE.md"]

    def test_matching_is_case_insensitive(self, project):
        from codebase_agent.fs_tools import find_files
        assert find_files(project, "SCHEMA") == ["docs/DATABASE_SCHEMA_REFERENCE.md"]

    def test_globs_work_for_extensions(self, project):
        from codebase_agent.fs_tools import find_files
        assert find_files(project, "*.R") == ["shared/db_helpers.R"]

    def test_the_full_name_still_matches(self, project):
        from codebase_agent.fs_tools import find_files
        assert find_files(project, "DATABASE_SCHEMA_REFERENCE.md")

    def test_excluded_directories_are_skipped(self, project):
        from codebase_agent.fs_tools import find_files
        (project / "node_modules").mkdir()
        (project / "node_modules" / "schema.js").write_text("x", encoding="utf-8")
        assert all("node_modules" not in p for p in find_files(project, "schema"))

    def test_an_empty_pattern_does_not_return_the_whole_repo(self, project):
        from codebase_agent.fs_tools import find_files
        assert find_files(project, "") == []

    def test_results_are_deterministic(self, project):
        from codebase_agent.fs_tools import find_files
        assert find_files(project, "*.md") == sorted(find_files(project, "*.md"))


class TestFindFilesDispatch:
    def test_the_payload_names_the_paths(self, project, monkeypatch):
        monkeypatch.setattr(dispatch, "_get_project_root", lambda pid: (project, None))
        out = dispatch.op_find_files({"project_id": "p", "pattern": "schema"})
        assert out["paths"] == ["docs/DATABASE_SCHEMA_REFERENCE.md"]
        assert out["match_count"] == 1

    def test_a_miss_refuses_to_be_read_as_absence(self, project, monkeypatch):
        monkeypatch.setattr(dispatch, "_get_project_root", lambda pid: (project, None))
        out = dispatch.op_find_files({"project_id": "p", "pattern": "nothing_like_this"})
        assert out["match_count"] == 0
        assert "Do not report the file as missing" in out["note"]


class TestCapabilityReporting:
    """The backend needs to know what this build can do, so it never offers the
    model a tool that answers "Unknown operation"."""

    def test_every_dispatchable_op_is_reported(self):
        from codebase_agent.dispatch import _OPS, supported_ops
        assert set(supported_ops()) == set(_OPS)

    def test_the_new_op_is_included(self):
        from codebase_agent.dispatch import supported_ops
        assert "find_files" in supported_ops()

    def test_the_hello_frame_carries_it(self):
        """The list travels at connect; without it the backend assumes an old
        build and withholds the newer tools."""
        import inspect
        from codebase_agent import ws_client
        src = inspect.getsource(ws_client._run_once)
        assert '"ops": supported_ops()' in src
