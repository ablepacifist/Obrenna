from __future__ import annotations

import json

from app.model_runtime.config import RuntimeConfig
from app.services.provisioning.adapters import (
    OllamaAdapter,
    PullProgress,
    adapter_for,
    normalize_model_ref,
    source_to_ollama_ref,
)


class _FakeResponse:
    def __init__(self, payload=None, lines=None):
        self._payload = payload
        self._lines = lines or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    def __init__(self, *, timeout=None):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url):
        assert url.endswith('/api/tags')
        return _FakeResponse(
            payload={
                'models': [
                    {'name': 'radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF:latest'},
                    {'name': 'jewelzufo/unsloth_granite-4.0-h-350m-GGUF:latest'},
                ]
            }
        )

    def stream(self, method, url, json=None):
        assert method == 'POST'
        assert url.endswith('/api/pull')
        assert json and 'name' in json
        lines = [
            '{"status":"downloading","completed":50,"total":100}',
            '{"status":"downloading","completed":100,"total":100}',
            '{"status":"success","done":true}',
        ]
        return _FakeResponse(lines=lines)


def test_normalize_and_source_ref_parsing():
    assert normalize_model_ref('  Foo/Bar:Latest ') == 'foo/bar:latest'
    assert source_to_ollama_ref('community GGUF, radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF, HF') == 'radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF'


def test_adapter_selection_ollama():
    cfg = RuntimeConfig(base_url='http://localhost:11434/v1')
    chosen = adapter_for(cfg)
    assert isinstance(chosen, OllamaAdapter)


def test_ollama_adapter_list_and_pull(monkeypatch):
    monkeypatch.setattr('app.services.provisioning.adapters.httpx.Client', _FakeClient)
    cfg = RuntimeConfig(base_url='http://localhost:11434/v1')
    adapter = OllamaAdapter(cfg)

    installed = adapter.list_installed_models()
    assert 'radenadri/qwen3.5-0.8b-claude-4.6-opus-reasoning-distilled-gguf:latest' in installed

    progress = list(adapter.pull_model('radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF'))
    assert len(progress) == 3
    assert all(isinstance(p, PullProgress) for p in progress)
    assert progress[0].percent == 50
    assert progress[-1].done is True
