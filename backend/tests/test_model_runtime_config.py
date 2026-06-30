from app.model_runtime.config import RuntimeConfig


def test_runtime_kind_detects_ollama_from_default_port():
    cfg = RuntimeConfig(base_url="http://localhost:11434/v1")
    assert cfg.runtime_kind == "ollama"
    assert cfg.supports_pull is True
    assert cfg.supports_streaming_progress is True


def test_runtime_kind_generic_openai_compatible_when_not_ollama():
    cfg = RuntimeConfig(base_url="http://localhost:8000/v1", provider="openai_compatible")
    assert cfg.runtime_kind == "openai_compatible_unknown"
    assert cfg.supports_pull is False
    assert cfg.supports_streaming_progress is False
