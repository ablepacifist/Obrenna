"""search_codebase: ripgrep-backed when available, Python fallback otherwise.

No bundled ripgrep binary in this version -- uses `rg` from PATH if present
(common on dev machines), and degrades to a plain Python walk+regex scan
rather than hard-failing when it isn't. Same exclusions as list_directory,
applied before results leave this process either way.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .excludes import is_excluded_dir, is_excluded_file, EXCLUDED_DIR_NAMES
from .fs_tools import is_binary
from .pathsafety import resolve_safe_path

MAX_FILE_SCAN_BYTES = 1_000_000


@dataclass
class SearchMatch:
    path: str
    line_number: int
    line: str


def search_codebase(
    root: Path,
    pattern: str,
    *,
    path: str = ".",
    regex: bool = True,
    case_sensitive: bool = False,
    max_results: int = 100,
) -> list[SearchMatch]:
    search_root = resolve_safe_path(root, path)
    if not search_root.is_dir():
        raise ValueError(f"Not a directory: {path}")

    rg = shutil.which("rg")
    if rg:
        return _search_with_ripgrep(rg, search_root, root, pattern, regex, case_sensitive, max_results)
    return _search_with_python(search_root, root, pattern, regex, case_sensitive, max_results)


def _search_with_ripgrep(
    rg_bin: str, search_root: Path, project_root: Path, pattern: str, regex: bool, case_sensitive: bool, max_results: int
) -> list[SearchMatch]:
    args = [rg_bin, "--line-number", "--no-heading", "--max-count", str(max_results)]
    if not regex:
        args.append("--fixed-strings")
    if not case_sensitive:
        args.append("--ignore-case")
    for d in EXCLUDED_DIR_NAMES:
        args.extend(["--glob", f"!{d}"])
    args.extend([pattern, str(search_root)])

    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return _search_with_python(search_root, project_root, pattern, regex, case_sensitive, max_results)

    matches: list[SearchMatch] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        file_path, line_no, text = parts
        try:
            rel = Path(file_path).resolve().relative_to(project_root.resolve())
        except ValueError:
            continue
        matches.append(SearchMatch(path=str(rel).replace("\\", "/"), line_number=int(line_no), line=text))
        if len(matches) >= max_results:
            break
    return matches


def _search_with_python(
    search_root: Path, project_root: Path, pattern: str, regex: bool, case_sensitive: bool, max_results: int
) -> list[SearchMatch]:
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        compiled = re.compile(pattern, flags)
    else:
        compiled = re.compile(re.escape(pattern), flags)

    matches: list[SearchMatch] = []

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
                        continue
                    raw = child.read_bytes()
                except OSError:
                    continue
                if is_binary(raw[:8000]):
                    continue
                text = raw.decode("utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), start=1):
                    if compiled.search(line):
                        rel = str(child.relative_to(project_root)).replace("\\", "/")
                        matches.append(SearchMatch(path=rel, line_number=i, line=line))
                        if len(matches) >= max_results:
                            return

    _walk(search_root)
    return matches
