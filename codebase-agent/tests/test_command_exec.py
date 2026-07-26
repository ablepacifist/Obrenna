"""run_command: the shell-execution primitive that makes this a coding agent.

Proves it runs real commands confined to the project root, captures exit
code + stdout + stderr, honors the timeout, and refuses to escape the root.
"""
from __future__ import annotations

import sys

import pytest

from codebase_agent.command_exec import run_command
from codebase_agent.fs_tools import FsError
from codebase_agent.pathsafety import PathSafetyError


def test_runs_a_command_and_captures_stdout(tmp_path):
    r = run_command(tmp_path, f'{sys.executable} -c "print(2+2)"')
    assert r.exit_code == 0
    assert r.stdout.strip() == "4"
    assert r.timed_out is False


def test_nonzero_exit_code_is_reported(tmp_path):
    r = run_command(tmp_path, f'{sys.executable} -c "import sys; sys.exit(3)"')
    assert r.exit_code == 3


def test_stderr_is_captured(tmp_path):
    r = run_command(tmp_path, f'{sys.executable} -c "import sys; sys.stderr.write(\'boom\')"')
    assert "boom" in r.stderr


def test_runs_in_the_project_directory(tmp_path):
    # A file created by a command lands in the project root, and the command
    # sees the project as its cwd.
    run_command(tmp_path, f'{sys.executable} -c "open(\'made.txt\',\'w\').write(\'hi\')"')
    assert (tmp_path / "made.txt").read_text() == "hi"


def test_runs_in_subdir_cwd(tmp_path):
    (tmp_path / "sub").mkdir()
    run_command(tmp_path, f'{sys.executable} -c "open(\'in_sub.txt\',\'w\').write(\'x\')"', cwd="sub")
    assert (tmp_path / "sub" / "in_sub.txt").exists()


def test_cwd_escape_is_rejected(tmp_path):
    with pytest.raises(PathSafetyError):
        run_command(tmp_path, "echo hi", cwd="..")


def test_empty_command_rejected(tmp_path):
    with pytest.raises(FsError):
        run_command(tmp_path, "   ")


def test_timeout_is_enforced(tmp_path):
    # A command that sleeps far longer than the timeout is killed and flagged.
    r = run_command(tmp_path, f'{sys.executable} -c "import time; time.sleep(30)"', timeout=2)
    assert r.timed_out is True
    assert r.exit_code is None
    assert "timed out" in r.stderr.lower()


def test_write_then_run_end_to_end(tmp_path):
    # The core coding-agent loop: a file is written, then executed.
    (tmp_path / "app.py").write_text("print('hello from app')\n", encoding="utf-8")
    r = run_command(tmp_path, f"{sys.executable} app.py")
    assert r.exit_code == 0
    assert "hello from app" in r.stdout
