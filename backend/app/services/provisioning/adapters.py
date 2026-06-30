from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterator

import httpx

from ...model_runtime.config import RuntimeConfig


def _root_url(base_url: str) -> str:
    base = (base_url or "http://localhost:11434/v1").rstrip("/")
    for suffix in ("/v1", "/api"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _api_url(cfg: RuntimeConfig, path: str) -> str:
    return f"{_root_url(cfg.base_url)}/api/{path.lstrip('/')}"


def normalize_model_ref(name: str) -> str:
    return (name or "").strip().lower()


def source_to_ollama_ref(source: str | None) -> str | None:
    if not source:
        return None
    match = re.search(r"([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", source)
    return match.group(1) if match else None


@dataclass
class PullProgress:
    status: str
    completed: int = 0
    total: int = 0
    percent: int = 0
    done: bool = False
    error: str | None = None


class RuntimeAdapter:
    def list_installed_models(self) -> set[str]:
        raise NotImplementedError

    def list_loaded_models(self) -> set[str]:
        """Models currently resident in memory (i.e. actively serving).

        Returns an empty set when the runtime cannot report this. Callers
        must treat "unknown" as "not loaded", never as "all loaded".
        """
        return set()

    def pull_model(self, model_ref: str) -> Iterator[PullProgress]:
        raise NotImplementedError


class GenericOpenAIAdapter(RuntimeAdapter):
    """Fallback adapter: can list models but cannot pull models."""

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg

    def list_installed_models(self) -> set[str]:
        url = self.cfg.url("models")
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=self.cfg.headers)
            resp.raise_for_status()
            data = resp.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        out: set[str] = set()
        for it in items or []:
            if isinstance(it, dict):
                name = it.get("id") or it.get("name") or ""
                if name:
                    out.add(normalize_model_ref(name))
            elif isinstance(it, str):
                out.add(normalize_model_ref(it))
        return out

    def pull_model(self, model_ref: str) -> Iterator[PullProgress]:
        yield PullProgress(
            status="failed",
            error=f"Runtime does not support pull: {self.cfg.runtime_kind}",
            done=True,
        )


class OllamaAdapter(RuntimeAdapter):
    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg

    def list_installed_models(self) -> set[str]:
        url = _api_url(self.cfg, "tags")
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()

        models = payload.get("models", []) if isinstance(payload, dict) else []
        out: set[str] = set()
        for it in models:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("model") or ""
            if name:
                out.add(normalize_model_ref(name))
        return out

    def list_loaded_models(self) -> set[str]:
        """Query Ollama's /api/ps for models currently loaded in memory."""
        url = _api_url(self.cfg, "ps")
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                payload = resp.json()
        except Exception:
            return set()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        out: set[str] = set()
        for it in models:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("model") or ""
            if name:
                out.add(normalize_model_ref(name))
        return out

    def pull_model(self, model_ref: str) -> Iterator[PullProgress]:
        name = model_ref.strip()
        url = _api_url(self.cfg, "pull")
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", url, json={"name": name, "stream": True}) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    status = str(event.get("status") or "downloading")
                    completed = int(event.get("completed") or 0)
                    total = int(event.get("total") or 0)
                    percent = int((completed * 100) / total) if total > 0 else 0
                    done = bool(event.get("done", False)) or status.lower() in {
                        "success",
                        "done",
                    }
                    yield PullProgress(
                        status=status,
                        completed=completed,
                        total=total,
                        percent=percent,
                        done=done,
                    )


def adapter_for(cfg: RuntimeConfig) -> RuntimeAdapter:
    if cfg.runtime_kind == "ollama":
        return OllamaAdapter(cfg)
    return GenericOpenAIAdapter(cfg)
