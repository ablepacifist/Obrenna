from app.services.hardware_catalog import (
    load_catalog,
    resolve_ollama_pull_ref,
    validate_catalog_for_runtime,
)


def test_catalog_validation_for_ollama_has_no_errors():
    catalog = load_catalog()
    errors = validate_catalog_for_runtime(catalog, runtime_kind='ollama')
    assert errors == []


def test_pull_ref_resolution_uses_source_when_present():
    catalog = load_catalog()
    ref = resolve_ollama_pull_ref(catalog, 'qwen3.5-0.8b-claude-opus-reasoning-distilled')
    assert ref == 'radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF'


def test_pull_ref_resolution_falls_back_to_model_slug():
    # Unknown slug (not in model_definitions) returns itself unchanged.
    catalog = load_catalog()
    ref = resolve_ollama_pull_ref(catalog, 'not-a-real-model-slug')
    assert ref == 'not-a-real-model-slug'


def test_pull_ref_resolution_uses_explicit_ollama_ref():
    # Every catalog model resolves to a namespaced/library ref, never a bare slug.
    catalog = load_catalog()
    ref = resolve_ollama_pull_ref(catalog, 'qwen3.5-27b')
    assert ref == 'qwen3.5:27b'
