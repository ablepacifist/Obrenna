"""Regression tests for model-status availability matching.

Guards the bug where an installed model showed "Not loaded" because the status
check compared the bare catalog slug against the runtime's fully-qualified ids
(e.g. "owner/name:tag") instead of the resolved Ollama pull ref.
"""
from app.routers.models import _ref_matches_available


def test_namespaced_ref_matches_tagged_runtime_id():
    # The real-world case: catalog pull ref vs Ollama's reported id with :latest.
    available = [
        "radenadri/qwen3.5-0.8b-claude-4.6-opus-reasoning-distilled-gguf:latest",
        "nomic-embed-text:latest",
    ]
    ref = "radenadri/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF"
    assert _ref_matches_available(ref, available) is True


def test_exact_match_with_tag():
    assert _ref_matches_available("granite4:micro-h", ["granite4:micro-h"]) is True


def test_distinct_granite_variants_do_not_match():
    # granite4:350m-h (hybrid) must NOT be considered installed when only the
    # plain granite4:350m is present — they are different models.
    assert _ref_matches_available("granite4:350m-h", ["granite4:350m"]) is False


def test_missing_model_is_not_available():
    assert _ref_matches_available("granite4:tiny-h", ["granite4:1b"]) is False


def test_empty_ref_is_not_available():
    assert _ref_matches_available("", ["granite4:1b"]) is False
