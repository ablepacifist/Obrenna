"""Loader for hardware_catalog.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parent / "hardware_catalog.json"


def resolve_ollama_pull_ref(catalog: dict, model_slug: str) -> str:
    """Return an Ollama pull reference for a catalog model id.

    If model_definitions.<slug>.source contains an owner/model pair,
    prefer that. Otherwise return the slug itself.
    """
    defs = catalog.get("model_definitions", {})
    row = defs.get(model_slug, {}) if isinstance(defs, dict) else {}
    if isinstance(row, dict):
        explicit = row.get("ollama_ref")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        source = row.get("source")
        if isinstance(source, str):
            match = re.search(r"([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", source)
            if match:
                return match.group(1)
    return model_slug


def validate_catalog_for_runtime(catalog: dict, runtime_kind: str = "ollama") -> list[str]:
    """Return validation errors for model provisionability in this catalog.

    For Ollama, each referenced model must resolve to a non-empty pull ref.
    For non-Ollama runtimes we only validate model id presence.
    """
    errors: list[str] = []
    refs: set[str] = set()

    def _collect(plan: dict):
        for key in ("orchestrator", "summarizer", "utility"):
            obj = plan.get(key)
            if isinstance(obj, dict) and obj.get("model"):
                refs.add(str(obj["model"]))
        helpers = plan.get("helpers")
        if isinstance(helpers, dict) and helpers.get("model"):
            refs.add(str(helpers["model"]))

    for block in ("gpu_tiers", "cpu_only_tiers", "apple_silicon_tiers"):
        plans = catalog.get(block, {}).get("plans", [])
        for plan in plans:
            if isinstance(plan, dict):
                _collect(plan)

    defs = catalog.get("model_definitions", {})
    for model_slug in sorted(refs):
        if model_slug not in defs:
            errors.append(f"Model '{model_slug}' is referenced by tiers but missing in model_definitions")
            continue
        if runtime_kind == "ollama":
            row = defs.get(model_slug, {})
            explicit = row.get("ollama_ref") if isinstance(row, dict) else None
            if not isinstance(explicit, str) or not explicit.strip():
                errors.append(f"Model '{model_slug}' is missing explicit 'ollama_ref'")
                continue
            pull_ref = resolve_ollama_pull_ref(catalog, model_slug)
            if not pull_ref.strip():
                errors.append(f"Model '{model_slug}' does not resolve to an Ollama pull ref")

    return errors


def load_catalog(path: str | Path | None = None) -> dict:
    """Load the hardware catalog from its JSON file.

    Args:
        path: Optional override path. Defaults to the bundled file.

    Returns:
        The parsed catalog dict.
    """
    target = Path(path) if path else _CATALOG_PATH
    with open(target) as f:
        catalog = json.load(f)

    errors = validate_catalog_for_runtime(catalog, runtime_kind="ollama")
    if errors:
        raise ValueError("Invalid hardware catalog for provisioning: " + "; ".join(errors))
    return catalog
