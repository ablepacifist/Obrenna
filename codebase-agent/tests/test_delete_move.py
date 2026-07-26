"""delete_file / move_file primitives, and the empty-old_string guard.

These reproduce the exact failure from the reviewed transcript: the model,
asked to MOVE and DELETE README files, had no move/delete primitive and
resorted to codebase_edit_file with old_string="" + replace_all=true — a no-op
that still "succeeded", so it believed it had deleted a file that was still on
disk. The move/delete primitives + the empty-old_string rejection close that.
"""
from __future__ import annotations

import pytest

from codebase_agent.edit import edit_file
from codebase_agent.fs_tools import FsError, delete_file, move_file, write_new_file


def _write(path, text, *, crlf=False):
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(data.encode("utf-8"))


def test_delete_file_removes_and_backs_up(tmp_path):
    f = tmp_path / "README.md"
    _write(f, "duplicate readme\n")
    assert f.exists()

    change_id = delete_file(tmp_path, "README.md")

    assert not f.exists()
    assert isinstance(change_id, str) and change_id
    # A backup was recorded so the delete is revertable.
    from codebase_agent.backups import list_changes, revert_change
    changes = list_changes(tmp_path)
    assert any(c.id == change_id for c in changes)
    revert_change(tmp_path, change_id)
    assert f.exists()
    assert f.read_bytes() == b"duplicate readme\n"


def test_delete_file_refuses_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    with pytest.raises(FsError):
        delete_file(tmp_path, "sub")


def test_delete_missing_file_raises(tmp_path):
    with pytest.raises(FsError):
        delete_file(tmp_path, "nope.md")


def test_move_file_relocates_without_overwrite(tmp_path):
    src = tmp_path / "README.md"
    _write(src, "the keeper\n")

    (tmp_path / "docs").mkdir()
    change_id, content_hash = move_file(tmp_path, "README.md", "docs/README.md")

    assert not src.exists()
    dest = tmp_path / "docs" / "README.md"
    assert dest.read_bytes() == b"the keeper\n"
    assert change_id and content_hash


def test_move_file_creates_missing_parent_dirs(tmp_path):
    src = tmp_path / "a.txt"
    _write(src, "x\n")
    move_file(tmp_path, "a.txt", "deep/nested/a.txt")
    assert (tmp_path / "deep" / "nested" / "a.txt").exists()


def test_move_file_refuses_to_overwrite_destination(tmp_path):
    _write(tmp_path / "a.txt", "aaa\n")
    _write(tmp_path / "b.txt", "bbb\n")
    with pytest.raises(FsError):
        move_file(tmp_path, "a.txt", "b.txt")
    # Neither file was touched.
    assert (tmp_path / "a.txt").read_bytes() == b"aaa\n"
    assert (tmp_path / "b.txt").read_bytes() == b"bbb\n"


def test_move_missing_source_raises(tmp_path):
    with pytest.raises(FsError):
        move_file(tmp_path, "ghost.txt", "dest.txt")


def test_edit_file_rejects_empty_old_string(tmp_path):
    # The core anti-footgun: empty old_string + replace_all used to be a
    # silent no-op that reported success (a fake "deletion").
    f = tmp_path / "SETUP.md"
    _write(f, "keep me\n")
    with pytest.raises(FsError, match="old_string must not be empty"):
        edit_file(tmp_path, "SETUP.md", old_string="", new_string="", replace_all=True)
    # File is untouched.
    assert f.read_bytes() == b"keep me\n"


def test_edit_file_rejects_noop_identical_strings(tmp_path):
    f = tmp_path / "SETUP.md"
    _write(f, "line\n")
    with pytest.raises(FsError, match="identical"):
        edit_file(tmp_path, "SETUP.md", old_string="line", new_string="line")


def test_edit_file_can_remove_a_section_with_empty_new_string(tmp_path):
    # The RIGHT way to "remove" content: real old_string, empty new_string.
    f = tmp_path / "SETUP.md"
    _write(f, "intro\n\n## Troubleshooting\nblah\n\noutro\n")
    edit_file(tmp_path, "SETUP.md",
              old_string="## Troubleshooting\nblah\n\n", new_string="")
    out = f.read_bytes().decode()
    assert "Troubleshooting" not in out
    assert "intro" in out and "outro" in out


def test_write_new_file_at_root_with_bare_name(tmp_path):
    # Bare filename → project root (the location the model kept getting wrong).
    write_new_file(tmp_path, "README.md", "root readme\n")
    assert (tmp_path / "README.md").read_bytes() == b"root readme\n"
