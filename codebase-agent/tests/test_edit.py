"""edit_file line-ending tolerance + core behaviour.

The critical case is CRLF: read_file normalizes line endings to LF in the
content it returns, so a model's old_string is LF-only. On Windows the file on
disk is almost always CRLF — matching a raw CRLF file against an LF old_string
would always miss on a multi-line span, making edits impossible. edit_file must
match in normalized space and preserve the file's original newline style.
"""
from __future__ import annotations

import pytest

from codebase_agent.edit import EditNotFoundError, EditNotUniqueError, edit_file
from codebase_agent.fs_tools import FsError


def _write(path, text, *, crlf):
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(data.encode("utf-8"))


def test_multiline_edit_on_crlf_file_matches_lf_old_string(tmp_path):
    # File on disk is CRLF (Windows default); the model's old_string is LF
    # (that's what read_file showed it). The edit must still apply.
    f = tmp_path / "SETUP.md"
    _write(f, "# Title\n\n## Start\n\nTODO: start it.\n\n## Stop\n", crlf=True)
    assert b"\r\n" in f.read_bytes()

    edit_file(tmp_path, "SETUP.md",
              old_string="## Start\n\nTODO: start it.",
              new_string="## Start\n\nRun npm run dev")

    out = f.read_bytes()
    # Content updated...
    assert b"Run npm run dev" in out
    assert b"TODO: start it." not in out
    # ...and the file stays CRLF (we didn't reflow line endings).
    assert b"\r\n" in out
    assert b"\n" not in out.replace(b"\r\n", b"")  # no lone LF introduced


def test_multiline_edit_on_lf_file_still_works(tmp_path):
    f = tmp_path / "SETUP.md"
    _write(f, "# Title\n\n## Start\n\nTODO: start it.\n", crlf=False)

    edit_file(tmp_path, "SETUP.md",
              old_string="## Start\n\nTODO: start it.",
              new_string="## Start\n\nRun npm run dev")

    out = f.read_bytes()
    assert b"Run npm run dev" in out
    assert b"\r\n" not in out  # stays LF


def test_new_string_lf_written_as_crlf_on_crlf_file(tmp_path):
    # A multi-line new_string (LF) must be written with the file's CRLF style.
    f = tmp_path / "SETUP.md"
    _write(f, "line1\nOLD\nline3\n", crlf=True)

    edit_file(tmp_path, "SETUP.md", old_string="OLD", new_string="NEW-A\nNEW-B")

    out = f.read_bytes()
    assert b"NEW-A\r\nNEW-B" in out
    assert b"NEW-A\nNEW-B" not in out.replace(b"\r\n", b"\x00")  # the LF became CRLF


def test_old_string_not_found_raises(tmp_path):
    f = tmp_path / "SETUP.md"
    _write(f, "hello world\n", crlf=True)
    with pytest.raises(EditNotFoundError):
        edit_file(tmp_path, "SETUP.md", old_string="not here", new_string="x")


def test_non_unique_without_replace_all_raises(tmp_path):
    f = tmp_path / "SETUP.md"
    _write(f, "dup\ndup\n", crlf=True)
    with pytest.raises(EditNotUniqueError):
        edit_file(tmp_path, "SETUP.md", old_string="dup", new_string="x")


def test_old_string_with_line_number_artifacts_still_matches(tmp_path):
    # Small models copy the read tool's "<n>\t" line numbers / lone leading tabs
    # into old_string. Exact match fails, but the read-prefix fallback strips
    # exactly those artifacts and applies the edit.
    f = tmp_path / "SETUP.md"
    _write(f, "A\n\n---\n\n## Troubleshooting\n\n| Symptom |\n| row |\n\nfooter\n", crlf=True)

    polluted = "\t---\n\t\n163\t## Troubleshooting\n\t\n| Symptom |\n| row |"
    edit_file(tmp_path, "SETUP.md", old_string=polluted, new_string="---")

    out = f.read_bytes().replace(b"\r\n", b"\n")
    assert b"## Troubleshooting" not in out
    assert out == b"A\n\n---\n\nfooter\n"


def test_interior_whitespace_is_not_stripped(tmp_path):
    # The fallback only strips leading line-number/tab prefixes, never interior
    # or non-prefix whitespace — so it can't silently match unrelated content.
    f = tmp_path / "code.py"
    _write(f, "def f():\n    return 1\n", crlf=False)
    with pytest.raises(EditNotFoundError):
        # Not a read-prefix artifact; genuinely absent → must still fail.
        edit_file(tmp_path, "code.py", old_string="def f():\n        return 1", new_string="x")


def test_replace_all_on_crlf_file(tmp_path):
    f = tmp_path / "SETUP.md"
    _write(f, "dup\ndup\n", crlf=True)
    edit_file(tmp_path, "SETUP.md", old_string="dup", new_string="x", replace_all=True)
    out = f.read_bytes()
    assert out.count(b"x") == 2
    assert b"dup" not in out
    assert b"\r\n" in out
