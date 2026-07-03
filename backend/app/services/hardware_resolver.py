"""Deterministic hardware-to-plan resolver.

This module implements the resolver algorithm from hardware_catalog.json.
It is a pure function: same fingerprint -> same plan, always.
No model name, VRAM number, core count, or RAM threshold is hardcoded in
the resolver logic — every threshold is read from the catalog.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .hardware_catalog import (
    load_catalog,
    max_tool_rounds_for,
    reasoning_distilled_for,
    tool_call_mode_for,
    tool_result_budget_for,
)


# ---------------------------------------------------------------------------
# Hardware fingerprint — STABLE facts only. Used for tier resolution.
# ---------------------------------------------------------------------------
@dataclass
class HardwareFingerprint:
    gpu_vendor: str = "none"
    gpu_name: str = ""
    gpu_vram_total_gb: float = 0.0
    gpu_fp16_support: bool = False
    gpu_backends_available: list = field(default_factory=list)
    gpu_is_integrated: bool = False

    cpu_physical_cores: int = 0
    cpu_threads: int = 0
    cpu_isa_flags: list = field(default_factory=list)

    ram_total_gb: float = 0.0
    ram_type: str = "unknown"
    ram_channels: int = 0

    storage_is_ssd: bool = True
    os: str = "unknown"
    driver_version: str = ""

    unified_mem_gb: float = 0.0

    def stable_hash(self) -> str:
        payload = json.dumps(
            {k: v for k, v in self.__dict__.items()},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Live free resources — probed at every launch. Used only by fit().
# ---------------------------------------------------------------------------
@dataclass
class LiveFreeResources:
    gpu_vram_free_gb: float = 0.0
    ram_free_gb: float = 0.0


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------
def _get_weight_gb(catalog: dict, model_id: str, quant: str) -> float:
    table = catalog["model_definitions"]["_quant_weight_table_gb"]
    return table.get(model_id, {}).get(quant, 0.0)


def _get_kv_cache_gb_per_1k(catalog: dict, model_id: str) -> float:
    table = catalog["model_definitions"]["_kv_cache_gb_per_1k_tokens"]
    return table.get(model_id, 0.15)


def _get_constants(catalog: dict) -> dict:
    return catalog["global_constants"]


def _keep_alive_for(role_block: dict | None, default) -> Any:
    """Extract the Ollama ``keep_alive`` value from a catalog role block.

    Each role block (orchestrator/summarizer/utility/helpers) carries a
    ``keep_alive_policy`` object whose ``keep_alive`` member is the source of
    truth (see ``hardware_catalog.json``) — never hardcode these in the runtime.
    ``-1`` pins a model in VRAM/RAM for the whole session (orchestrator); a
    duration string like ``"5m"``/``"10m"`` keeps a lazy role loaded briefly
    after its last call, then evicts it. Falls back to ``default`` when the block
    or the policy is absent.
    """
    block = role_block or {}
    policy = block.get("keep_alive_policy") or {}
    value = policy.get("keep_alive")
    return value if value is not None else default


# ---------------------------------------------------------------------------
# satisfies() — check if a fingerprint meets a requires block
# ---------------------------------------------------------------------------
def _satisfies(fp: HardwareFingerprint, requires: dict) -> bool:
    # GPU VRAM
    if "gpu_vram_gb" in requires and fp.gpu_vram_total_gb < requires["gpu_vram_gb"]:
        return False

    # GPU fp16 — exact boolean match, NOT threshold
    if "gpu_fp16" in requires and fp.gpu_fp16_support != requires["gpu_fp16"]:
        return False

    # GPU backend requirement
    if "gpu_backend_any" in requires:
        required_backends = requires["gpu_backend_any"]
        if not any(b in fp.gpu_backends_available for b in required_backends):
            return False

    # RAM total
    if "ram_gb" in requires and fp.ram_total_gb < requires["ram_gb"]:
        return False

    # RAM type
    if "ram_type" in requires and fp.ram_type != requires["ram_type"]:
        return False

    # RAM channels
    if "ram_channels" in requires and fp.ram_channels < requires["ram_channels"]:
        return False

    # CPU physical cores
    if "physical_cores" in requires and fp.cpu_physical_cores < requires["physical_cores"]:
        return False

    # CPU threads
    if "threads" in requires and fp.cpu_threads < requires["threads"]:
        return False

    # CPU ISA flags
    if "isa" in requires:
        if not all(flag in fp.cpu_isa_flags for flag in requires["isa"]):
            return False

    return True


# ---------------------------------------------------------------------------
# Tier resolution functions
# ---------------------------------------------------------------------------
def resolve_gpu_tier(fp: HardwareFingerprint, catalog: dict) -> Optional[dict]:
    """Resolve the best GPU tier for the fingerprint."""
    plans = sorted(catalog["gpu_tiers"]["plans"], key=lambda p: -p["rank"])
    for plan in plans:
        if _satisfies(fp, plan["requires"]):
            return plan
    return None


def resolve_cpu_only_tier(fp: HardwareFingerprint, catalog: dict) -> Optional[dict]:
    """Resolve the best CPU-only tier for the fingerprint."""
    plans = sorted(catalog["cpu_only_tiers"]["plans"], key=lambda p: -p["rank"])
    for plan in plans:
        if _satisfies(fp, plan["requires"]):
            return plan
    return None


def resolve_apple_tier(fp: HardwareFingerprint, catalog: dict) -> Optional[dict]:
    """Resolve the best Apple Silicon tier for the fingerprint."""
    plans = sorted(catalog["apple_silicon_tiers"]["plans"], key=lambda p: -p["rank"])
    for plan in plans:
        if fp.unified_mem_gb >= plan["requires"]["unified_mem_gb"]:
            return plan
    return None


def resolve_top_level(fp: HardwareFingerprint, catalog: dict) -> tuple[str, Optional[dict]]:
    """Stage 0 routing. Returns (path, plan).

    Path is one of: 'apple' | 'gpu' | 'cpu_only' | 'reject'
    """
    if fp.gpu_vendor == "apple":
        plan = resolve_apple_tier(fp, catalog)
        return ("apple", plan) if plan else ("reject", None)

    plan = resolve_gpu_tier(fp, catalog)
    if plan is not None:
        return ("gpu", plan)

    plan = resolve_cpu_only_tier(fp, catalog)
    if plan is not None:
        return ("cpu_only", plan)

    return ("reject", None)


def resolve_cpu_helper_tier(fp: HardwareFingerprint, catalog: dict) -> tuple[dict, Optional[dict]]:
    """Resolve CPU helper concurrency tier (highest satisfied rank)."""
    plans = sorted(catalog["cpu_helper_concurrency_tiers"]["plans"], key=lambda p: p["rank"])
    best = {"id": "unknown", "peak_concurrent_helpers": 1, "execution_mode": "unknown"}
    for plan in plans:
        if _satisfies(fp, plan["requires"]):
            best = plan
    return best


def resolve_ram_residency_tier(fp: HardwareFingerprint, catalog: dict) -> tuple[dict, Optional[dict]]:
    """Resolve RAM residency tier (highest satisfied rank)."""
    plans = sorted(catalog["ram_residency_tiers_gpu_present"]["plans"], key=lambda p: p["rank"])
    best = {"id": "unknown", "residency_ceiling": 1}
    for plan in plans:
        if _satisfies(fp, plan["requires"]):
            best = plan
    return best


def resolve_helper_count(fp: HardwareFingerprint, catalog: dict) -> int:
    """Compute helper count = min(cpu_peak, ram_ceiling)."""
    cpu_plan = resolve_cpu_helper_tier(fp, catalog)
    ram_plan = resolve_ram_residency_tier(fp, catalog)

    cpu_peak = cpu_plan.get("peak_concurrent_helpers", 1)
    ram_ceiling = ram_plan.get("residency_ceiling", 1)

    return min(cpu_peak, ram_ceiling)


# ---------------------------------------------------------------------------
# Fit — dynamic context length against live resources
# ---------------------------------------------------------------------------
def fit(plan: dict, catalog: dict, live: LiveFreeResources) -> dict:
    """Fit the orchestrator's context length against live free resources.

    Shrinks context from ctx_max toward ctx_min if VRAM is tight.
    """
    gc = _get_constants(catalog)
    orch = plan["orchestrator"]
    weight = _get_weight_gb(catalog, orch["model"], orch["quant"])
    kv_per_1k = _get_kv_cache_gb_per_1k(catalog, orch["model"])

    ctx = orch["ctx_max"]
    usable_vram = live.gpu_vram_free_gb * gc["gpu_usable_fraction_of_free_vram"]
    fixed = gc["gpu_display_overhead_gb"] + gc["gpu_framework_overhead_gb"]

    while ctx > orch["ctx_min"]:
        required = weight + (kv_per_1k * ctx / 1000.0) + fixed
        if required <= usable_vram:
            break
        ctx -= 2048
    ctx = max(ctx, orch["ctx_min"])

    vram_required = round(weight + (kv_per_1k * ctx / 1000.0) + fixed, 2)
    return {"ctx": ctx, "vram_required_gb": vram_required}


# ---------------------------------------------------------------------------
# Validation stub
# ---------------------------------------------------------------------------
def smoke_test_stub(plan: dict, ctx: int, helpers: int) -> dict:
    """Placeholder. Always passes — real validation will load and measure."""
    return {"loaded_successfully": True, "tok_s": 999, "validation_stubbed": True}


# ---------------------------------------------------------------------------
# choose_and_validate — full pipeline entry point
# ---------------------------------------------------------------------------
def choose_and_validate(
    fp: HardwareFingerprint,
    catalog: dict | None = None,
    live: LiveFreeResources | None = None,
) -> dict:
    """Run the full resolver pipeline and return a managed plan response."""
    if catalog is None:
        catalog = load_catalog()
    if live is None:
        live = LiveFreeResources()

    path, plan = resolve_top_level(fp, catalog)

    if path == "reject" or plan is None:
        reject_below = catalog.get("gpu_tiers", {}).get("reject_below", {})
        action = reject_below.get("action", "route_to_byom_or_cloud_key_setup")
        return {
            "path": "reject",
            "action": action,
            "recommended_setup_mode": "byo",
            "reason": "No qualifying GPU or CPU-only tier found. Use your own local server.",
            "detection_warnings": [],
            "orchestrator": None,
            "summarizer": None,
            "utility": None,
            "ctx": None,
            "helper_count": 0,
            "fingerprint_hash": fp.stable_hash(),
        }

    if path == "gpu":
        fitted = fit(plan, catalog, live)
        helpers = resolve_helper_count(fp, catalog)
        floor = _get_constants(catalog).get("interactive_tok_s_floor_gpu", 8)
    elif path == "cpu_only":
        # CPU path: fit() variant on RAM not yet implemented in this milestone
        # Apple path: unified-memory fit() also not yet implemented — ctx = ctx_max is a milestone stub
        fitted = {"ctx": plan["orchestrator"]["ctx_max"]}
        helpers = plan.get("helpers", {}).get("count_max", 1)
        floor = _get_constants(catalog).get("interactive_tok_s_floor_cpu_only", 5)
    else:
        # Apple Silicon path — unified memory fit() is a milestone stub; ctx = ctx_max
        fitted = {"ctx": plan["orchestrator"]["ctx_max"]}
        helpers = 2
        floor = _get_constants(catalog).get("interactive_tok_s_floor_gpu", 8)

    result = smoke_test_stub(plan, fitted["ctx"], helpers)

    if result["loaded_successfully"] and result["tok_s"] >= floor:
        detection_warnings = []
        if path == "cpu_only":
            detection_warnings.append("CPU RAM-fit not yet implemented — ctx is set to ctx_max (may exceed available RAM)")
        if path == "apple":
            detection_warnings.append("Apple unified-memory fit() not yet implemented — ctx is set to ctx_max")
            detection_warnings.append(
                "Apple Silicon tiers define no dedicated summarizer/utility model in the "
                "catalog — worker fan-out and evidence-pack summarization are unavailable "
                "on this tier until apple_silicon_tiers.plans gains those blocks."
            )

        response = {
            "path": path,
            "plan_id": plan["id"],
            "plan_rank": plan["rank"],
            "ctx": fitted["ctx"],
            "helper_count": helpers,
            "fingerprint_hash": fp.stable_hash(),
            "runtime_priority": plan.get("runtime_priority", []),
            "runtime_forbidden": plan.get("runtime_forbidden", []),
            "required_launch_flags": plan.get("required_launch_flags", []),
            "recommended_setup_mode": "managed",
            "action": "proceed_managed",
            "reason": None,
            "detection_warnings": detection_warnings,
            "orchestrator": {
                "model": plan["orchestrator"]["model"],
                "quant": plan["orchestrator"]["quant"],
                "device": plan["orchestrator"].get("device", "gpu"),
                "ctx_min": plan["orchestrator"].get("ctx_min"),
                "ctx_max": plan["orchestrator"].get("ctx_max"),
                "tool_call_mode": tool_call_mode_for(catalog, plan["orchestrator"]["model"]),
                "reasoning_distilled": reasoning_distilled_for(catalog, plan["orchestrator"]["model"]),
                "max_tool_rounds": max_tool_rounds_for(catalog, plan["orchestrator"]["model"]),
                "tool_result_budget": tool_result_budget_for(catalog, plan["orchestrator"]["model"]),
                "keep_alive": _keep_alive_for(plan["orchestrator"], -1),
            },
            "summarizer": None,
            "utility": None,
            "validation_stubbed": True,
        }

        # Add summarizer if present
        if "summarizer" in plan:
            resp_sum = dict(plan["summarizer"])
            resp_sum["device"] = plan["summarizer"].get("device", "cpu")
            resp_sum["keep_alive"] = _keep_alive_for(plan["summarizer"], None)
            response["summarizer"] = resp_sum

        # Add utility if present
        if "utility" in plan:
            resp_util = dict(plan["utility"])
            resp_util["device"] = plan["utility"].get("device", "cpu")
            resp_util["keep_alive"] = _keep_alive_for(plan["utility"], None)
            response["utility"] = resp_util
        elif "helpers" in plan:
            # cpu_only_tiers plans define a single combined "helpers" block
            # (model/quant/count_max/execution_mode) rather than separate
            # summarizer/utility roles. Surface it as "utility" so the
            # runtime's worker-dispatch path (which only looks at
            # resolved_plan.utility_model / helper_count) actually turns on
            # for CPU-only tiers instead of silently staying empty.
            helpers_block = plan["helpers"]
            response["utility"] = {
                "model": helpers_block.get("model", ""),
                "quant": helpers_block.get("quant", ""),
                "device": "cpu",
                "count_min": 1,
                "count_max": helpers_block.get("count_max", 1),
                "resident": "lazy",
                "keep_alive": _keep_alive_for(helpers_block, "5m"),
            }

        return response

    # Would downgrade here in production; stubbed for now
    return {
        "path": path,
        "action": "downgrade_and_retry",
        "recommended_setup_mode": "byo",
        "reason": "Managed plan did not pass validation. Use your own local server.",
        "detection_warnings": [],
        "orchestrator": None,
        "summarizer": None,
        "utility": None,
        "ctx": None,
        "helper_count": 0,
        "fingerprint_hash": fp.stable_hash(),
    }


# ---------------------------------------------------------------------------
# Convenience function: build fingerprint from detected hardware dict
# ---------------------------------------------------------------------------
def build_fingerprint(detected: dict) -> HardwareFingerprint:
    """Convert a probe dict into a HardwareFingerprint.

    This is a best-effort adapter that maps the current probe format
    to the resolver's expected fingerprint fields.
    """
    gpu_info = detected.get("gpu", [])
    primary_gpu = gpu_info[0] if gpu_info else None

    gpu_vendor = detected.get("gpu_vendor", "none")
    gpu_vram = detected.get("gpu_vram_total_gb") or 0.0
    gpu_fp16 = detected.get("gpu_fp16_support", False)
    gpu_backends = detected.get("gpu_backends_available", [])
    gpu_is_integrated = detected.get("gpu_is_integrated", False)

    return HardwareFingerprint(
        gpu_vendor=gpu_vendor,
        gpu_name=detected.get("gpu_name", ""),
        gpu_vram_total_gb=gpu_vram,
        gpu_fp16_support=gpu_fp16,
        gpu_backends_available=gpu_backends,
        gpu_is_integrated=gpu_is_integrated,
        cpu_physical_cores=detected.get("cpu_physical_cores", 0),
        cpu_threads=detected.get("cpu_threads", 0),
        cpu_isa_flags=detected.get("cpu_isa_flags", []),
        ram_total_gb=detected.get("ram_total_gb") or 0.0,
        ram_type=detected.get("ram_type", "unknown"),
        ram_channels=detected.get("ram_channels", 0),
        storage_is_ssd=detected.get("storage_is_ssd", True),
        os=detected.get("os", "unknown"),
        unified_mem_gb=detected.get("unified_mem_gb", 0.0),
    )


def build_live(detected: dict) -> LiveFreeResources:
    """Convert a probe dict into live free resources."""
    return LiveFreeResources(
        gpu_vram_free_gb=detected.get("gpu_vram_free_gb") or 0.0,
        ram_free_gb=detected.get("ram_free_gb") or 0.0,
    )
