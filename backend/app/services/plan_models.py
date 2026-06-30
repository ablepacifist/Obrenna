"""Resolve the hardware-tier managed plan into display-ready model info.

Single source of truth for what models the app shows anywhere: the orchestrator,
summarizer, and utility models assigned to the user's hardware tier in
hardware_catalog.json. No fictional/static model lists.
"""
from __future__ import annotations

from .hardware import resolve_managed_plan
from .hardware_catalog import load_catalog
from .model_names import format_display_name

_ROLE_LABELS = {
    "orchestrator": "Reasoner",
    "summarizer": "Summarizer",
    "utility": "Utility",
}


def _weight_gb(catalog: dict, model_id: str, quant: str) -> float:
    table = catalog.get("model_definitions", {}).get("_quant_weight_table_gb", {})
    row = table.get(model_id, {})
    if quant and quant in row:
        return float(row[quant])
    # Fall back to the smallest listed quant if the exact one is missing.
    if row:
        return float(min(row.values()))
    return 0.0


def resolve_plan_models(runtime_base_url: str | None = None) -> list[dict]:
    """Return the role-assigned models for the current hardware tier.

    Each entry: {role, label, model, display_name, quant, size_gb, size}.
    """
    plan = resolve_managed_plan(runtime_base_url=runtime_base_url)
    catalog = load_catalog()
    out: list[dict] = []
    for role, label in _ROLE_LABELS.items():
        ref = plan.get(role)
        if not isinstance(ref, dict) or not ref.get("model"):
            continue
        model = str(ref["model"])
        quant = str(ref.get("quant") or "")
        size_gb = _weight_gb(catalog, model, quant)
        out.append({
            "role": role,
            "label": label,
            "model": model,
            "display_name": format_display_name(model),
            "quant": quant,
            "size_gb": size_gb,
            "size": f"{size_gb:.1f} GB" if size_gb else "",
        })
    return out
