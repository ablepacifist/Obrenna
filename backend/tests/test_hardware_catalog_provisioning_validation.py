from app.services.hardware_catalog import (
    load_catalog,
    resolve_ollama_pull_ref,
    tool_call_mode_for,
    validate_catalog_for_runtime,
)


def test_catalog_validation_for_ollama_has_no_errors():
    catalog = load_catalog()
    errors = validate_catalog_for_runtime(catalog, runtime_kind='ollama')
    assert errors == []


def test_invalid_tool_call_mode_is_flagged():
    # A model with a tool_call_mode outside the allowed enum must be flagged.
    catalog = {
        "model_definitions": {
            "bad-model": {"ollama_ref": "owner/bad", "tool_call_mode": "bogus"},
        },
        "gpu_tiers": {"plans": [{"id": "T", "rank": 1, "requires": {},
            "orchestrator": {"model": "bad-model", "quant": "Q4_K_M"}}]},
        "cpu_only_tiers": {"plans": []},
        "apple_silicon_tiers": {"plans": []},
    }
    errors = validate_catalog_for_runtime(catalog, runtime_kind='ollama')
    assert any("tool_call_mode" in e for e in errors)


def test_tool_call_mode_for_returns_explicit_values():
    catalog = load_catalog()
    # Stock orchestrators → native OpenAI tool calls.
    assert tool_call_mode_for(catalog, "qwen3.5-27b") == "openai_native"
    assert tool_call_mode_for(catalog, "qwen3.6-35b-a3b") == "openai_native"
    # Distilled orchestrators → prompt-JSON fallback adapter.
    assert tool_call_mode_for(catalog, "qwen3.5-9b-claude-opus-reasoning-distilled") == "prompt_json"
    assert tool_call_mode_for(catalog, "qwen3.5-4b-claude-opus-reasoning-distilled-v2") == "prompt_json"


def test_tool_call_mode_for_defaults_to_native():
    catalog = load_catalog()
    # Unknown / omitted mode defaults to openai_native.
    assert tool_call_mode_for(catalog, "not-a-real-model-slug") == "openai_native"


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
