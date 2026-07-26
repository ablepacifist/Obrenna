"""edit_file: the only primitive for modifying an existing file.

Deliberately no whole-file-overwrite primitive for existing files -- an
exact old_string -> new_string replacement (uniqueness-checked) makes it
structurally hard to silently destroy unrelated content, the same contract
this agent's own author (Claude Code) uses for editing files.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .backups import record_backup
from .fs_tools import WRITE_BYTE_CAP, FsError, is_binary
from .pathsafety import resolve_safe_path

# read_file numbers lines as "<n>\t<content>"; a model reconstructing an
# old_string from that display sometimes leaves a leading "<n>\t" or a lone
# leading tab on a line. Strip exactly those, nothing else.
_READ_LINE_PREFIX_RE = re.compile(r"^(?:\d+\t|\t)")


def _strip_read_line_prefixes(text: str) -> str:
    return "\n".join(_READ_LINE_PREFIX_RE.sub("", ln) for ln in text.split("\n"))


class EditConflictError(FsError):
    """The file changed on disk since it was last read."""


class EditNotFoundError(FsError):
    """old_string was not found in the file."""


class EditNotUniqueError(FsError):
    """old_string matched more than once and replace_all was not set."""


@dataclass
class EditResult:
    change_id: str
    content_hash: str


def edit_file(
    root: Path,
    relative_path: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    expected_content_hash: Optional[str] = None,
) -> EditResult:
    # An empty old_string matches "nothing, everywhere": with replace_all it
    # degenerates to a no-op that still reports success — a confused model once
    # used exactly that to fake a file deletion and believed it worked. Reject
    # it with guidance toward the real primitives instead.
    if not old_string:
        raise FsError(
            "old_string must not be empty. To remove a section, pass that section's exact "
            "text as old_string with an empty new_string. To delete a whole file, use the "
            "delete_file tool."
        )
    if old_string == new_string:
        raise FsError("old_string and new_string are identical -- there is nothing to change")

    target = resolve_safe_path(root, relative_path, for_write=True)
    if not target.is_file():
        raise FsError(f"Not a file: {relative_path}")

    raw = target.read_bytes()
    if is_binary(raw[:8000]):
        raise FsError(f"Refusing to edit binary file: {relative_path}")

    current_hash = hashlib.sha256(raw).hexdigest()
    if expected_content_hash is not None and current_hash != expected_content_hash:
        raise EditConflictError(
            f"'{relative_path}' changed on disk since it was last read -- read it again before editing"
        )

    text = raw.decode("utf-8", errors="replace")

    # Line-ending-tolerant matching. read_file normalizes CRLF/CR to LF in the
    # numbered content it returns, so a model's old_string arrives LF-only even
    # when the file on disk is CRLF (the Windows default — the common case).
    # Matching the raw CRLF text against an LF old_string would ALWAYS miss on a
    # multi-line span, making edits structurally impossible on CRLF files. So we
    # match in a normalized LF space and restore the file's original newline
    # style on write, never reflowing line endings the user didn't touch.
    def _to_lf(s: str) -> str:
        return s.replace("\r\n", "\n").replace("\r", "\n")

    norm_text = _to_lf(text)
    norm_old = _to_lf(old_string)
    norm_new = _to_lf(new_string)

    count = norm_text.count(norm_old)
    if count == 0:
        # Fallback: small models routinely copy the read tool's line-number/tab
        # display prefixes ("163\t", a lone leading tab) into old_string, so an
        # otherwise-correct multi-line span never matches. Strip only those
        # read-format artifacts from the START of each line and retry. This is a
        # last resort (exact match already failed) targeted at the numbered-read
        # format — it does not touch interior whitespace, so it won't silently
        # match unrelated content.
        deartifacted = _strip_read_line_prefixes(norm_old)
        if deartifacted != norm_old and norm_text.count(deartifacted) >= 1:
            norm_old = deartifacted
            count = norm_text.count(norm_old)
    if count == 0:
        raise EditNotFoundError(f"old_string not found in {relative_path}")
    if count > 1 and not replace_all:
        raise EditNotUniqueError(
            f"old_string matches {count} times in {relative_path} -- add more surrounding "
            f"context to make it unique, or pass replace_all=true"
        )

    new_text_lf = norm_text.replace(norm_old, norm_new, -1 if replace_all else 1)
    # Restore the file's dominant newline style so a CRLF file stays CRLF.
    newline = "\r\n" if "\r\n" in text else ("\r" if "\r" in text else "\n")
    new_text = new_text_lf.replace("\n", newline) if newline != "\n" else new_text_lf
    new_data = new_text.encode("utf-8")
    if len(new_data) > WRITE_BYTE_CAP:
        raise FsError(f"Resulting content too large ({len(new_data)} bytes, cap is {WRITE_BYTE_CAP})")

    change_id = record_backup(root, target, relative_path)
    target.write_bytes(new_data)

    return EditResult(change_id=change_id, content_hash=hashlib.sha256(new_data).hexdigest())
