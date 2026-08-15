"""A command must see the project's own credentials.

The failure this pins: asked to check a live database, the agent ran
``Rscript -e "source('shared/db_helpers.R'); get_db_connection()"`` -- the
project's real connection helper, reading Sys.getenv("DB_HOST") -- and it came
back empty, because the spawned command inherited only the agent process's
environment and nothing ever loaded the project's .env. The model read that as
"I have no access to your database" and told the user so, while the credentials
sat in a file it had permission to read the whole time.
"""
from __future__ import annotations

import os
import sys

from codebase_agent.command_exec import run_command
from codebase_agent.project_env import (
    PROTECTED_NAMES,
    build_command_env,
    load_project_env,
    parse_env_file,
)


class TestParsing:
    def test_plain_assignments(self):
        parsed = parse_env_file("DB_HOST=metrics.internal\nDB_PORT=5432\n")
        assert parsed == {"DB_HOST": "metrics.internal", "DB_PORT": "5432"}

    def test_comments_and_blank_lines_are_ignored(self):
        parsed = parse_env_file("# the metrics db\n\nDB_HOST=x\n\n# trailing\n")
        assert parsed == {"DB_HOST": "x"}

    def test_export_prefix_is_accepted(self):
        assert parse_env_file("export DB_USER=reader\n") == {"DB_USER": "reader"}

    def test_quotes_are_stripped(self):
        parsed = parse_env_file("A='single'\nB=\"double\"\n")
        assert parsed == {"A": "single", "B": "double"}

    def test_escapes_only_apply_inside_double_quotes(self):
        assert parse_env_file(r'A="one\ntwo"') == {"A": "one\ntwo"}
        assert parse_env_file(r"B='one\ntwo'") == {"B": r"one\ntwo"}

    def test_a_hash_inside_a_password_survives(self):
        """Passwords contain '#'. Only a whitespace-preceded '#' is a comment."""
        parsed = parse_env_file("DB_PASS=pa#ssword\nDB_USER=reader # the readonly one\n")
        assert parsed["DB_PASS"] == "pa#ssword"
        assert parsed["DB_USER"] == "reader"

    def test_dollar_signs_are_literal(self):
        """Expanding these would silently corrupt a password."""
        assert parse_env_file("DB_PASS=$ecret$HOME")["DB_PASS"] == "$ecret$HOME"

    def test_values_containing_equals_are_kept_whole(self):
        assert parse_env_file("DB_URL=postgres://u:p@h/db?a=b")["DB_URL"] == (
            "postgres://u:p@h/db?a=b"
        )

    def test_junk_lines_do_not_break_the_file(self):
        parsed = parse_env_file("not a pair\n123BAD=x\nGOOD=y\n")
        assert parsed == {"GOOD": "y"}

    def test_empty_value_is_allowed(self):
        assert parse_env_file("DB_PASS=\n") == {"DB_PASS": ""}


class TestLoading:
    def test_reads_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("DB_HOST=metrics.internal\n", encoding="utf-8")
        assert load_project_env(tmp_path)["DB_HOST"] == "metrics.internal"

    def test_reads_renviron_for_r_projects(self, tmp_path):
        (tmp_path / ".Renviron").write_text("DB_USER=shiny\n", encoding="utf-8")
        assert load_project_env(tmp_path)["DB_USER"] == "shiny"

    def test_renviron_wins_over_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("DB_HOST=a\n", encoding="utf-8")
        (tmp_path / ".Renviron").write_text("DB_HOST=b\n", encoding="utf-8")
        assert load_project_env(tmp_path)["DB_HOST"] == "b"

    def test_a_project_with_no_env_files_is_not_an_error(self, tmp_path):
        assert load_project_env(tmp_path) == {}

    def test_absurdly_large_files_are_skipped(self, tmp_path):
        (tmp_path / ".env").write_text("A=" + "x" * 300_000, encoding="utf-8")
        assert load_project_env(tmp_path) == {}


class TestEnvironmentAssembly:
    def test_project_values_are_added_to_the_inherited_environment(self, tmp_path):
        (tmp_path / ".env").write_text("DB_HOST=metrics.internal\n", encoding="utf-8")
        env = build_command_env(tmp_path)
        assert env["DB_HOST"] == "metrics.internal"
        # Still a real environment, not a replacement for one.
        assert any(key in env for key in ("PATH", "Path"))

    def test_project_values_win_over_a_stale_inherited_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_HOST", "stale-from-the-agent-process")
        (tmp_path / ".env").write_text("DB_HOST=metrics.internal\n", encoding="utf-8")
        assert build_command_env(tmp_path)["DB_HOST"] == "metrics.internal"

    def test_a_project_cannot_break_the_shell_it_runs_in(self, tmp_path):
        """A .env that redefines PATH would break every command rather than
        configure one, so the OS-critical names are not overridable."""
        (tmp_path / ".env").write_text("PATH=/nonsense\nSystemRoot=/nope\nDB_HOST=ok\n",
                                       encoding="utf-8")
        env = build_command_env(tmp_path)
        assert env.get("PATH", env.get("Path")) != "/nonsense"
        assert env["DB_HOST"] == "ok", "ordinary values must still come through"

    def test_every_protected_name_is_upper_case(self):
        """The lookup upper-cases the key, so a lower-case entry here would
        silently never match."""
        assert all(name == name.upper() for name in PROTECTED_NAMES)


class TestEndToEndThroughRunCommand:
    """The behaviour the model actually depends on."""

    def test_a_command_sees_the_projects_credentials(self, tmp_path):
        (tmp_path / ".env").write_text("DB_HOST=metrics.internal\n", encoding="utf-8")
        result = run_command(
            tmp_path,
            f'{sys.executable} -c "import os; print(os.environ.get(\'DB_HOST\', \'MISSING\'))"',
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == "metrics.internal", (
            "the project's own connection helper would fail without this"
        )

    def test_the_helper_pattern_from_the_real_project_works(self, tmp_path):
        """Mirrors shared/db_helpers.R: a helper reading credentials from the
        environment, sourced by a one-liner. This is the exact shape that
        returned nothing and convinced the model it had no database access."""
        (tmp_path / ".env").write_text(
            "DB_HOST=metrics.internal\nDB_USER=reader\n", encoding="utf-8"
        )
        (tmp_path / "db_helpers.py").write_text(
            "import os\n"
            "def get_db_connection():\n"
            "    return f\"{os.environ['DB_USER']}@{os.environ['DB_HOST']}\"\n",
            encoding="utf-8",
        )
        result = run_command(
            tmp_path,
            f'{sys.executable} -c "import db_helpers; print(db_helpers.get_db_connection())"',
        )
        assert result.stdout.strip() == "reader@metrics.internal"

    def test_credentials_never_appear_in_the_result_object(self, tmp_path):
        """Values reach the child process only. Nothing in what goes back to
        the model should contain them unless the command itself printed them."""
        (tmp_path / ".env").write_text("DB_PASS=hunter2\n", encoding="utf-8")
        result = run_command(tmp_path, f'{sys.executable} -c "print(1)"')
        blob = f"{result.command}{result.cwd}{result.stdout}{result.stderr}"
        assert "hunter2" not in blob

    def test_the_agents_own_environment_still_comes_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OBRENNA_TEST_MARKER", "present")
        result = run_command(
            tmp_path,
            f'{sys.executable} -c "import os; print(os.environ.get(\'OBRENNA_TEST_MARKER\'))"',
        )
        assert result.stdout.strip() == "present"

    def test_a_project_without_env_files_still_runs_commands(self, tmp_path):
        result = run_command(tmp_path, f'{sys.executable} -c "print(2+2)"')
        assert result.exit_code == 0 and result.stdout.strip() == "4"

    def test_the_parent_process_environment_is_not_mutated(self, tmp_path):
        (tmp_path / ".env").write_text("OBRENNA_LEAK_CHECK=leaked\n", encoding="utf-8")
        run_command(tmp_path, f'{sys.executable} -c "print(1)"')
        assert "OBRENNA_LEAK_CHECK" not in os.environ
