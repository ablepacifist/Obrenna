"""search_codebase: ripgrep-backed when available, Python fallback otherwise.

No bundled ripgrep binary in this version -- uses `rg` from PATH if present
(common on dev machines), and degrades to a plain Python walk+regex scan
rather than hard-failing when it isn't. Same exclusions, same visibility rules
and the same context lines apply to both, so a query gives the same answer
whichever backend happens to exist on the connected machine.

Why --json rather than rg's default `path:line:text` lines: the search root is
absolute, so on Windows every output line starts "C:\\..." and the drive
letter's colon is indistinguishable from the field separator. Splitting on ":"
mangled every match -- the parsed "line number" was the rest of the path, and
int() on it raised out of the whole call, so a search that found things
reported nothing at all. --json has no such ambiguity.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .excludes import (
    EXCLUDED_DIR_NAMES,
    EXCLUDED_FILE_NAMES,
    EXCLUDED_FILE_SUFFIXES,
    is_excluded_dir,
    is_excluded_file,
)
from .fs_tools import is_binary
from .pathsafety import resolve_safe_path

MAX_FILE_SCAN_BYTES = 1_000_000
DEFAULT_CONTEXT_LINES = 2
RG_TIMEOUT_SECONDS = 20


@dataclass
class SearchMatch:
    path: str
    line_number: int
    line: str
    # Surrounding source. A lone matching line can't be told apart from a call
    # site, which is how a caller ends up unsure whether a definition it just
    # found actually exists.
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)


@dataclass
class SearchOutcome:
    """Matches plus enough diagnostics to tell "not found" from "not looked".

    A bare list of matches is indistinguishable from "the symbol is not in this
    project" when it comes back empty -- so an empty result from a capped
    search, a fallback backend, or a skipped oversized file all read as proof
    of absence. These fields make that distinction available to the caller.
    """

    matches: list[SearchMatch]
    backend: str
    # How many files were examined. None means the backend cannot say -- never
    # 0, which would read as "looked at nothing" and is the opposite claim.
    files_scanned: int | None
    files_with_matches: int = 0
    files_skipped_large: int = 0
    truncated: bool = False


def search_codebase(
    root: Path,
    pattern: str,
    *,
    path: str = ".",
    regex: bool = True,
    case_sensitive: bool = False,
    max_results: int = 100,
    context: int = DEFAULT_CONTEXT_LINES,
) -> SearchOutcome:
    search_root = resolve_safe_path(root, path)
    if not search_root.is_dir():
        raise ValueError(f"Not a directory: {path}")

    if regex:
        # Validated here so both backends reject the same patterns, and as a
        # ValueError: re.error does not subclass it, so an invalid pattern
        # would otherwise sail past the caller's except clause and surface as
        # an unexplained "unexpected error".
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression {pattern!r}: {exc}") from exc

    outcome: SearchOutcome | None = None
    rg_bin = shutil.which("rg")
    if rg_bin:
        outcome = _search_with_ripgrep(
            rg_bin, search_root, root, pattern, regex, case_sensitive, max_results
        )
    if outcome is None:
        outcome = _search_with_python(
            search_root, root, pattern, regex, case_sensitive, max_results
        )

    _attach_context(outcome.matches, root, context)
    return outcome


def _search_with_ripgrep(
    rg_bin: str,
    search_root: Path,
    project_root: Path,
    pattern: str,
    regex: bool,
    case_sensitive: bool,
    max_results: int,
) -> SearchOutcome | None:
    """Returns None when rg could not be used, so the caller can fall back."""
    args = [rg_bin, "--json"]
    # rg's defaults skip dotfiles and anything gitignored; the Python walk skips
    # neither. Without these two flags the same query returns different results
    # depending on whether rg happens to be installed -- and a project's .env,
    # which is both hidden and gitignored, is invisible to search on exactly the
    # machines where rg exists.
    args.extend(["--hidden", "--no-ignore"])
    if not regex:
        args.append("--fixed-strings")
    if not case_sensitive:
        args.append("--ignore-case")
    args.extend(_exclusion_globs())
    # -e, not positional: a pattern beginning with "-" is otherwise read as a flag.
    args.extend(["-e", pattern, "--", str(search_root)])

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=RG_TIMEOUT_SECONDS,
            # Explicit, not incidental: the agent is normally launched detached,
            # so it has no usable stdin handle, and on Windows spawning a child
            # that inherits it fails outright with "The handle is invalid".
            # Without this, rg silently never runs in production.
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    # 0 = matched, 1 = no matches (a real answer). Anything else is rg failing.
    if proc.returncode not in (0, 1):
        return None
    outcome = _parse_ripgrep_json(proc.stdout, project_root, max_results)
    if not outcome.matches:
        # Only on the empty path, and only then: this is the one case where the
        # caller needs to know the difference between "searched 1400 files and
        # it isn't there" and "searched nothing". rg's own summary can't answer
        # it -- stats.searches counts files that matched, so it reports 0 here.
        outcome.files_scanned = _count_searchable_files(rg_bin, search_root)
    return outcome


def _exclusion_globs() -> list[str]:
    """The same deny-list the Python walk applies, expressed as rg globs."""
    globs: list[str] = []
    for name in EXCLUDED_DIR_NAMES:
        globs.extend(["--glob", f"!{name}"])
    for name in EXCLUDED_FILE_NAMES:
        globs.extend(["--glob", f"!{name}"])
    for suffix in EXCLUDED_FILE_SUFFIXES:
        globs.extend(["--glob", f"!*{suffix}"])
    return globs


def _count_searchable_files(rg_bin: str, search_root: Path) -> int | None:
    """How many files rg would have looked in. Cheap: --files never reads content."""
    args = [rg_bin, "--files", "--hidden", "--no-ignore"]
    args.extend(_exclusion_globs())
    args.extend(["--", str(search_root)])
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=RG_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode not in (0, 1):
        return None
    return sum(1 for line in proc.stdout.splitlines() if line.strip())


def _parse_ripgrep_json(stdout: str, project_root: Path, max_results: int) -> SearchOutcome:
    matches: list[SearchMatch] = []
    files_with_matches = 0
    truncated = False
    root_resolved = project_root.resolve()

    for raw in stdout.splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}

        if etype == "begin":
            files_with_matches += 1
            continue
        if etype != "match":
            continue
        if len(matches) >= max_results:
            truncated = True
            continue

        path_text = _rg_text(data.get("path"))
        line_number = data.get("line_number")
        if path_text is None or not isinstance(line_number, int):
            continue
        rel = _relative_path(Path(path_text), root_resolved)
        if rel is None:
            continue
        line = (_rg_text(data.get("lines")) or "").rstrip("\r\n")
        matches.append(SearchMatch(path=rel, line_number=line_number, line=line))

    return SearchOutcome(
        matches=matches,
        backend="ripgrep",
        # rg's --json stream says nothing about files it read and discarded;
        # its summary "searches" counts only files that matched. Left unknown
        # here and filled by the caller when it actually matters.
        files_scanned=None,
        files_with_matches=files_with_matches,
        truncated=truncated,
    )


def _rg_text(obj: object) -> str | None:
    """rg reports text as {"text": ...}, or {"bytes": base64} when not UTF-8."""
    if not isinstance(obj, dict):
        return None
    text = obj.get("text")
    if isinstance(text, str):
        return text
    encoded = obj.get("bytes")
    if isinstance(encoded, str):
        try:
            return base64.b64decode(encoded).decode("utf-8", errors="replace")
        except ValueError:  # binascii.Error subclasses ValueError
            return None
    return None


def _relative_path(candidate: Path, root_resolved: Path) -> str | None:
    try:
        return str(candidate.resolve().relative_to(root_resolved)).replace("\\", "/")
    except (ValueError, OSError):
        return None


def _attach_context(matches: list[SearchMatch], project_root: Path, context: int) -> None:
    """Fill in before/after lines by re-reading each matched file once.

    Done here rather than via rg's -C so both backends produce identical shapes
    and the grouping logic exists in one place.
    """
    if context <= 0 or not matches:
        return
    by_file: dict[str, list[SearchMatch]] = {}
    for match in matches:
        by_file.setdefault(match.path, []).append(match)
    for rel, group in by_file.items():
        try:
            lines = (project_root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for match in group:
            index = match.line_number - 1
            if not 0 <= index < len(lines):
                continue
            match.before = lines[max(0, index - context):index]
            match.after = lines[index + 1:index + 1 + context]


def _search_with_python(
    search_root: Path,
    project_root: Path,
    pattern: str,
    regex: bool,
    case_sensitive: bool,
    max_results: int,
) -> SearchOutcome:
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern if regex else re.escape(pattern), flags)

    matches: list[SearchMatch] = []
    counters = {"scanned": 0, "skipped_large": 0, "truncated": 0}

    def _walk(dir_path: Path) -> None:
        if len(matches) >= max_results:
            return
        try:
            children = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for child in children:
            if len(matches) >= max_results:
                return
            if child.is_dir():
                if is_excluded_dir(child.name):
                    continue
                _walk(child)
            elif child.is_file():
                if is_excluded_file(child.name):
                    continue
                try:
                    if child.stat().st_size > MAX_FILE_SCAN_BYTES:
                        counters["skipped_large"] += 1
                        continue
                    raw = child.read_bytes()
                except OSError:
                    continue
                if is_binary(raw[:8000]):
                    continue
                counters["scanned"] += 1
                text = raw.decode("utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), start=1):
                    if compiled.search(line):
                        rel = str(child.relative_to(project_root)).replace("\\", "/")
                        matches.append(SearchMatch(path=rel, line_number=i, line=line))
                        if len(matches) >= max_results:
                            counters["truncated"] = 1
                            return

    _walk(search_root)
    return SearchOutcome(
        matches=matches,
        backend="python",
        files_scanned=counters["scanned"],
        files_with_matches=len({m.path for m in matches}),
        files_skipped_large=counters["skipped_large"],
        truncated=bool(counters["truncated"]),
    )
