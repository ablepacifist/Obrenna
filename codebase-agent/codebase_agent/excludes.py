"""Default exclusions applied inside the agent, before results ever leave it."""
from __future__ import annotations

EXCLUDED_DIR_NAMES = {
    ".git", ".hg", ".svn",
    "node_modules", "venv", ".venv", "env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", "target", ".next", ".nuxt", "coverage",
    ".codebase-agent-backups",
}

EXCLUDED_FILE_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Cargo.lock", "composer.lock",
}

EXCLUDED_FILE_SUFFIXES = (
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".7z",
    ".woff", ".woff2", ".ttf", ".eot",
)


def is_excluded_dir(name: str) -> bool:
    return name in EXCLUDED_DIR_NAMES


def is_excluded_file(name: str) -> bool:
    if name in EXCLUDED_FILE_NAMES:
        return True
    return name.lower().endswith(EXCLUDED_FILE_SUFFIXES)
