"""Static model catalog with a fit assessment against detected hardware.

NOTE: model downloading is intentionally NOT implemented in this milestone. The setup
flow's download step is simulated client-side. This catalog only informs the
recommendation; connecting to an already-running local server (BYO) is the real path.
"""
from __future__ import annotations

from typing import Any

_CATALOG = [
    {"id": "reasoner", "name": "Qwen 2.5 14B", "role": "Main reasoner", "size_gb": 9.2},
    {"id": "summarizer", "name": "Phi-3.5 Mini", "role": "Summarizer", "size_gb": 2.3},
    {"id": "utility", "name": "Llama 3.2 3B", "role": "Utility", "size_gb": 2.0},
    {"id": "big", "name": "Llama 3.1 70B", "role": "Optional", "size_gb": 39.0},
    {"id": "med", "name": "Mistral 7B", "role": "Optional", "size_gb": 4.4},
]


def catalog_with_fit(hardware: dict[str, Any]) -> list[dict[str, Any]]:
    budget = _memory_budget_gb(hardware)
    out: list[dict[str, Any]] = []
    for m in _CATALOG:
        fit, note = _assess(m["size_gb"], budget)
        out.append(
            {
                "id": m["id"],
                "name": m["name"],
                "role": m["role"],
                "size": f"{m['size_gb']:.1f} GB",
                "size_gb": m["size_gb"],
                "fit": fit,
                "note": note,
            }
        )
    return out


def _memory_budget_gb(hardware: dict[str, Any]) -> float:
    vram = hardware.get("vram_gb") or 0
    ram = hardware.get("ram_gb") or 0
    # Prefer VRAM; otherwise assume ~70% of system RAM is usable for a model.
    return float(vram) if vram else round(ram * 0.7, 1)


def _assess(size_gb: float, budget: float) -> tuple[str, str]:
    if budget <= 0:
        return "warn", "Couldn't read your memory — fit is uncertain."
    if size_gb <= budget * 0.6:
        return "ok", "Runs well on your machine"
    if size_gb <= budget:
        return "warn", "Will run slowly under load"
    return "bad", "Too large for this machine"
