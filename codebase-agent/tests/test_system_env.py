"""A program installed after the agent started must still be runnable.

The reported failure, verbatim: the user installed R, added it to PATH,
confirmed `Rscript --version` worked in their own terminal, and asked the agent
to run it. Every attempt returned

    'Rscript' is not recognized as an internal or external command

The model ran `where Rscript`, `where.exe R`, `systeminfo`, and then told the
user "R is not installed on this Windows machine, despite what you said about
adding it to PATH" -- confidently, with a table of evidence, and wrong.

A process inherits its environment once, at launch. The agent had been running
since before R existed on that machine. Its PATH was a snapshot; the user's
shell was reading the live one.
"""
from __future__ import annotations

import os
import sys

import pytest

from codebase_agent.command_exec import run_command
from codebase_agent.project_env import build_command_env
from codebase_agent.system_env import (
    looks_like_missing_program,
    missing_program_hint,
    refreshed_path,
)


class TestRefreshedPath:
    def test_a_directory_added_after_launch_becomes_visible(self):
        """The exact scenario: R's bin dir is in the system PATH but not in the
        environment this process inherited."""
        stale = os.pathsep.join([r"C:\Windows", r"C:\Windows\System32"])
        live = [r"C:\Windows", r"C:\Windows\System32", r"C:\Program Files\R\R-4.4.1\bin\x64"]
        result = refreshed_path(stale, live)
        assert r"C:\Program Files\R\R-4.4.1\bin\x64" in result

    def test_nothing_is_ever_removed(self):
        """The agent's own venv/toolchain entries are not in the registry and
        must survive."""
        stale = os.pathsep.join([r"C:\agent\.venv\Scripts", r"C:\Windows"])
        result = refreshed_path(stale, [r"C:\Windows"])
        assert r"C:\agent\.venv\Scripts" in result

    def test_inherited_entries_keep_precedence(self):
        """Prepending would silently change which python or node a command
        picks -- a different surprise, not a fix."""
        stale = os.pathsep.join([r"C:\agent\.venv\Scripts"])
        result = refreshed_path(stale, [r"C:\Python313"])
        assert result.split(os.pathsep)[0] == r"C:\agent\.venv\Scripts"

    def test_duplicates_are_not_appended(self):
        stale = os.pathsep.join([r"C:\Windows", r"C:\Windows\System32"])
        result = refreshed_path(stale, [r"C:\Windows", r"C:\Windows\System32"])
        assert result == stale

    def test_trailing_slashes_do_not_create_duplicates(self):
        result = refreshed_path(r"C:\Windows", ["C:\\Windows\\"])
        assert result == r"C:\Windows"

    def test_case_differences_do_not_create_duplicates(self):
        result = refreshed_path(r"C:\Windows", [r"c:\windows"])
        assert result == r"C:\Windows"

    def test_environment_variables_in_the_registry_are_expanded(self):
        """Registry PATH entries are REG_EXPAND_SZ: literally '%SystemRoot%\\x'."""
        result = refreshed_path("", [r"%SystemRoot%\System32\Wbem"])
        assert "%SystemRoot%" not in result

    def test_an_empty_inherited_path_is_handled(self):
        assert refreshed_path("", [r"C:\Windows"]) == r"C:\Windows"

    def test_no_extra_entries_leaves_it_untouched(self):
        assert refreshed_path(r"C:\Windows", []) == r"C:\Windows"

    @pytest.mark.skipif(os.name != "nt", reason="registry is Windows-only")
    def test_the_real_registry_read_produces_a_usable_path(self):
        refreshed = refreshed_path(os.environ.get("PATH", ""))
        assert refreshed
        # Whatever else is true, the shell's own directory must be reachable.
        assert any("system32" in p.lower() for p in refreshed.split(os.pathsep))


class TestCommandEnvUsesIt:
    def test_the_command_environment_has_a_refreshed_path(self, tmp_path):
        env = build_command_env(tmp_path)
        key = "Path" if "Path" in env else "PATH"
        assert env[key]

    def test_a_project_env_still_cannot_hijack_path(self, tmp_path):
        (tmp_path / ".env").write_text("PATH=/nonsense\n", encoding="utf-8")
        env = build_command_env(tmp_path)
        assert env.get("PATH", env.get("Path")) != "/nonsense"

    def test_commands_still_run(self, tmp_path):
        """The refresh must not corrupt the PATH it is topping up."""
        result = run_command(tmp_path, f'{sys.executable} -c "print(1+1)"')
        assert result.exit_code == 0
        assert result.stdout.strip() == "2"


class TestMissingProgramIsExplained:
    def test_the_windows_wording_is_recognised(self):
        assert looks_like_missing_program(
            "'Rscript' is not recognized as an internal or external command,\n"
            "operable program or batch file."
        )

    def test_the_posix_wording_is_recognised(self):
        assert looks_like_missing_program("bash: Rscript: command not found")

    def test_an_ordinary_failure_is_not_mistaken_for_one(self):
        assert not looks_like_missing_program("Error in dbConnect: password authentication failed")

    def test_the_hint_names_the_program(self):
        assert "'Rscript'" in missing_program_hint('Rscript -e "1+1"')

    def test_the_hint_denies_the_wrong_conclusion(self):
        """The model's actual error was concluding 'R is not installed'."""
        hint = missing_program_hint("Rscript --version")
        assert "does NOT mean it is not installed" in hint

    def test_the_hint_gives_both_ways_out(self):
        hint = missing_program_hint("Rscript --version")
        assert "full path" in hint
        assert "restart the codebase-agent" in hint

    def test_a_real_missing_program_gets_the_hint_attached(self, tmp_path):
        result = run_command(tmp_path, "definitely_not_a_real_program_xyz --version")
        assert result.exit_code != 0
        assert "obrenna" in result.stderr.lower()
        assert "does NOT mean it is not installed" in result.stderr

    def test_a_successful_command_gets_no_hint(self, tmp_path):
        result = run_command(tmp_path, f'{sys.executable} -c "print(1)"')
        assert "obrenna" not in result.stderr.lower()

    def test_a_genuine_error_gets_no_hint(self, tmp_path):
        result = run_command(tmp_path, f'{sys.executable} -c "raise SystemExit(3)"')
        assert result.exit_code == 3
        assert "obrenna" not in result.stderr.lower()
