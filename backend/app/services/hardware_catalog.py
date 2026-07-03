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
    Also validates the per-model ``tool_call_mode`` enum when present.
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
        row = defs.get(model_slug, {})
        if isinstance(row, dict):
            mode = row.get("tool_call_mode")
            if mode is not None and mode not in _VALID_TOOL_CALL_MODES:
                errors.append(
                    f"Model '{model_slug}' has invalid tool_call_mode '{mode}'. "
                    f"Must be one of {sorted(_VALID_TOOL_CALL_MODES)} (or omitted for the default)."
                )
            rd = row.get("reasoning_distilled")
            if rd is not None and not isinstance(rd, bool):
                errors.append(f"Model '{model_slug}' has invalid reasoning_distilled (must be bool)")
            for field in ("max_tool_rounds", "tool_result_budget"):
                v = row.get(field)
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v <= 0):
                    errors.append(f"Model '{model_slug}' has invalid {field} (must be a positive int)")
        if runtime_kind == "ollama":
            explicit = row.get("ollama_ref") if isinstance(row, dict) else None
            if not isinstance(explicit, str) or not explicit.strip():
                errors.append(f"Model '{model_slug}' is missing explicit 'ollama_ref'")
                continue
            pull_ref = resolve_ollama_pull_ref(catalog, model_slug)
            if not pull_ref.strip():
                errors.append(f"Model '{model_slug}' does not resolve to an Ollama pull ref")

    return errors


# Tool-calling strategies the runtime knows how to drive.
# - "openai_native": the model emits OpenAI delta.tool_calls; the streaming
#   parser handles them directly.
# - "prompt_json": the model lacks a native tool-call template, so the runtime
#   injects a tool contract into the prompt and the streaming layer scans the
#   text stream for a {"action":"tool_call",...} envelope.
_VALID_TOOL_CALL_MODES = {"openai_native", "prompt_json"}


def tool_call_mode_for(catalog: dict, model_slug: str) -> str:
    """Return the tool_call_mode for a model, defaulting to openai_native.

    Centralizes the default so callers (resolver, runtime) agree on the fallback
    when a model entry omits the field.
    """
    defs = catalog.get("model_definitions", {})
    row = defs.get(model_slug, {}) if isinstance(defs, dict) else {}
    if isinstance(row, dict):
        mode = row.get("tool_call_mode")
        if mode in _VALID_TOOL_CALL_MODES:
            return mode
    return "openai_native"


def reasoning_distilled_for(catalog: dict, model_slug: str) -> bool:
    """Return whether a model is a reasoning-distilled (always-CoT) variant.

    Defaults to False. This is the discriminator for the thinking-effort lever
    on tool-continuation rounds: distilled models need in-stream CoT to form
    their tool-call envelopes, stock models emit tool calls structurally. Keyed
    on model identity (read from the catalog) rather than ``tool_call_mode``
    because the two only correlate — mode is transport, distilled is capability,
    and a future distilled model could carry native transport.
    """
    defs = catalog.get("model_definitions", {})
    row = defs.get(model_slug, {}) if isinstance(defs, dict) else {}
    if isinstance(row, dict):
        return bool(row.get("reasoning_distilled", False))
    return False


def max_tool_rounds_for(catalog: dict, model_slug: str) -> int:
    """Per-orchestrator-model cap on chained tool calls in a single turn.

    Sourced from the catalog model_definition (mirrors tool_call_mode placement,
    since the round budget tracks model capability, not VRAM — which is already
    governed per-tier by ctx_max). Defaults to 3, a safe mid-tier value, when the
    field is absent.
    """
    defs = catalog.get("model_definitions", {})
    row = defs.get(model_slug, {}) if isinstance(defs, dict) else {}
    if isinstance(row, dict):
        val = row.get("max_tool_rounds")
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    return 3


def tool_result_budget_for(catalog: dict, model_slug: str) -> int:
    """Per-orchestrator-model char budget for compacting a single tool result.

    Sourced from the catalog model_definition. Defaults to 4000 chars when absent.
    """
    defs = catalog.get("model_definitions", {})
    row = defs.get(model_slug, {}) if isinstance(defs, dict) else {}
    if isinstance(row, dict):
        val = row.get("tool_result_budget")
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    return 4000


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
