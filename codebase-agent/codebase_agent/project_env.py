"""Project-local environment for commands run inside a project.

A project keeps its database credentials, hostnames and API keys in its own
`.env` / `.Renviron`. Commands spawned by ``run_command`` inherited only the
agent process's environment, so a project's own connection helper --
``get_db_connection()``, ``Sys.getenv("DB_HOST")``, ``os.environ["DB_URL"]`` --
found nothing and failed. From the outside that is indistinguishable from
having no credentials at all, which is precisely the conclusion drawn when
``Rscript -e "source('shared/db_helpers.R')"`` was run and came back empty.

Loading them here makes a command behave the way running it by hand in that
directory does. The values go straight into the child process's environment:
they are never logged, never placed in a ``CommandResult``, and never reach
the model.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .system_env import refreshed_path

# .Renviron uses the same KEY=VALUE form; R reads it automatically only when it
# happens to be the working directory, so loading it explicitly makes the
# behaviour the same regardless of which subdirectory a command runs from.
ENV_FILENAMES = (".env", ".Renviron")
MAX_ENV_FILE_BYTES = 256_000

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

# A project file must not be able to replace the machinery the shell itself
# needs. A .env that sets PATH or SystemRoot would break every command rather
# than configure it.
PROTECTED_NAMES = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
    "TEMP", "TMP", "HOME", "USERPROFILE", "OS", "PYTHONHOME", "PYTHONPATH",
})


def parse_env_file(text: str) -> dict[str, str]:
    """Parse dotenv-style KEY=VALUE lines. No variable expansion, by design:
    a credential is a literal, and expanding ``$`` would corrupt passwords."""
    values: dict[str, str] = {}
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        values[key] = _parse_value(value.strip())
    return values


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            # Only double quotes carry escapes, matching shell and dotenv.
            return inner.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
        return inner
    # An unquoted value ends at a whitespace-preceded '#'. A '#' with no space
    # before it stays put -- it is a perfectly ordinary password character.
    comment = re.search(r"\s#", value)
    return value[: comment.start()].rstrip() if comment else value


def load_project_env(root: Path) -> dict[str, str]:
    """Values from the project's env files. Later files win over earlier ones."""
    values: dict[str, str] = {}
    for name in ENV_FILENAMES:
        path = root / name
        try:
            if not path.is_file() or path.stat().st_size > MAX_ENV_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values.update(parse_env_file(text))
    return values


def build_command_env(root: Path) -> dict[str, str]:
    """The environment a command runs with: the agent's, plus the project's."""
    env = dict(os.environ)
    # The agent's PATH is frozen at launch, so a program installed since then is
    # invisible to it even though the user's own shell finds it. Top it up from
    # the system's current PATH before the project's values are applied.
    path_key = "Path" if "Path" in env else "PATH"
    env[path_key] = refreshed_path(env.get(path_key, ""))
    for key, value in load_project_env(root).items():
        if key.upper() in PROTECTED_NAMES:
            continue
        env[key] = value
    return env
