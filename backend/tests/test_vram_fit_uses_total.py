"""The context window must not collapse to ctx_min on capable hardware.

Regression pinned here: ``fit()`` was being sized against the momentary FREE
VRAM reading. Its ``required`` term already includes the model weight, so
comparing against free double-counts that weight whenever the model is already
resident -- nothing fits, and context collapses to ``ctx_min``. It also made
the resolved plan depend on whether Ollama happened to be warm.

The user-visible symptom was answers truncated mid-sentence: a turn on a 10GB
card ended at exactly 8192 tokens (prompt_eval 7583 + eval 609) because that
was the floor context, while the same card comfortably fits 16384 (7.21GB).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.hardware_resolver import LiveFreeResources, build_live, fit

CATALOG = json.loads(
    (Path(__file__).resolve().parents[1] / "app/services/hardware_catalog.json")
    .read_text(encoding="utf-8")
)


def _plan(plan_id: str = "T2-standard-fp16") -> dict:
    return [p for p in CATALOG["gpu_tiers"]["plans"] if p["id"] == plan_id][0]


class TestBuildLiveUsesTotal:
    def test_probe_shape_uses_total_not_free(self):
        """_probe_all()'s shape. free=2.7 is what a warm Ollama looks like;
        sizing on it is what collapsed the context."""
        live = build_live({
            "gpu_vram_total_gb": 10.0, "gpu_vram_free_gb": 2.7,
            "ram_total_gb": 32.0, "ram_free_gb": 4.0,
        })
        assert live.gpu_vram_free_gb == 10.0, "must size on total, not the warm-cache reading"
        assert live.ram_free_gb == 32.0

    def test_display_summary_shape_also_works(self):
        """detect_hardware()'s summary uses different key names."""
        live = build_live({"vram_gb": 10.0, "ram_gb": 32.0})
        assert live.gpu_vram_free_gb == 10.0
        assert live.ram_free_gb == 32.0

    def test_plan_is_the_same_warm_or_cold(self):
        """The resolved plan must not depend on whether the model is loaded."""
        cold = build_live({"gpu_vram_total_gb": 10.0, "gpu_vram_free_gb": 9.8})
        warm = build_live({"gpu_vram_total_gb": 10.0, "gpu_vram_free_gb": 2.7})
        assert cold.gpu_vram_free_gb == warm.gpu_vram_free_gb

    def test_no_gpu_at_all_is_still_zero(self):
        """A machine with no GPU must not be handed a phantom allowance."""
        assert build_live({"ram_gb": 16.0}).gpu_vram_free_gb == 0.0


class TestFitUsesTheHardware:
    def test_capable_card_gets_more_than_the_floor(self):
        """The actual bug: a 10GB card was being given ctx_min."""
        plan = _plan()
        live = build_live({
            "gpu_vram_total_gb": 10.0, "gpu_vram_free_gb": 2.7, "ram_total_gb": 32.0,
        })
        result = fit(plan, CATALOG, live)

        assert result["ctx"] > plan["orchestrator"]["ctx_min"], (
            "a 10GB card must not be pinned to the floor context"
        )
        assert result["ctx"] == plan["orchestrator"]["ctx_max"]
        # And it must still be an honest fit, not a number plucked from air.
        assert result["vram_required_gb"] <= 10.0

    def test_zero_vram_still_yields_the_floor_not_a_crash(self):
        """The pre-fix behaviour must remain correct for a genuinely tiny GPU —
        the fix is about not *inventing* scarcity, not about ignoring it."""
        plan = _plan()
        result = fit(plan, CATALOG, LiveFreeResources(gpu_vram_free_gb=0.0, ram_free_gb=0.0))
        assert result["ctx"] == plan["orchestrator"]["ctx_min"]

    def test_a_tight_card_shrinks_rather_than_maxing_out(self):
        """Shrink-toward-min must still work; otherwise this fix would just
        trade under-allocation for OOM on smaller cards."""
        plan = _plan()
        tight = fit(plan, CATALOG, LiveFreeResources(gpu_vram_free_gb=7.0, ram_free_gb=16.0))
        roomy = fit(plan, CATALOG, LiveFreeResources(gpu_vram_free_gb=24.0, ram_free_gb=64.0))
        assert tight["ctx"] <= roomy["ctx"]
        assert plan["orchestrator"]["ctx_min"] <= tight["ctx"] <= plan["orchestrator"]["ctx_max"]

    @pytest.mark.parametrize("plan_id", [p["id"] for p in CATALOG["gpu_tiers"]["plans"]])
    def test_every_gpu_tier_stays_within_its_declared_bounds(self, plan_id):
        plan = _plan(plan_id)
        orch = plan["orchestrator"]
        live = build_live({"vram_gb": 24.0, "ram_gb": 64.0})
        ctx = fit(plan, CATALOG, live)["ctx"]
        assert orch["ctx_min"] <= ctx <= orch["ctx_max"]
