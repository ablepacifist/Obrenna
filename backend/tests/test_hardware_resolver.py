"""Tests for the hardware resolver — validates exact tier mapping."""
from __future__ import annotations

import pytest

from app.services.hardware_catalog import load_catalog
from app.services.hardware_resolver import (
    HardwareFingerprint,
    LiveFreeResources,
    choose_and_validate,
    fit,
    resolve_helper_count,
    resolve_top_level,
)


@pytest.fixture
def catalog():
    return load_catalog()


# ===========================================================================
# Reference hardware tests (from the spec)
# ===========================================================================

def test_rx580_i5_7500_16gb_t1_floor_fp32(catalog):
    """RX 580 8GB + i5-7500 (4c/4t) + 16GB DDR4 — T1-floor-fp32, helpers=1."""
    fp = HardwareFingerprint(
        gpu_vendor="amd",
        gpu_name="Radeon RX 580 8GB",
        gpu_vram_total_gb=8,
        gpu_fp16_support=False,
        gpu_backends_available=["vulkan"],
        cpu_physical_cores=4,
        cpu_threads=4,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=6.8, ram_free_gb=11.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T1-floor-fp32"
    assert result["orchestrator"]["model"] == "qwen3.5-4b-claude-opus-reasoning-distilled-v2"
    assert result["orchestrator"]["quant"] == "Q5_K_M"
    assert result["helper_count"] == 1  # C0: peak=1, R-16gb: ceiling=3 → min(1,3)=1


def test_rx580_ryzen3_3500x_16gb_t1_floor_2_helpers(catalog):
    """RX 580 8GB + Ryzen 3 3500X (6c) + 16GB DDR4 — T1-floor-fp32, helpers=2."""
    fp = HardwareFingerprint(
        gpu_vendor="amd",
        gpu_name="Radeon RX 580 8GB",
        gpu_vram_total_gb=8,
        gpu_fp16_support=False,
        gpu_backends_available=["vulkan"],
        cpu_physical_cores=6,
        cpu_threads=6,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=6.8, ram_free_gb=11.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T1-floor-fp32"
    # C1: peak=2, R-16gb: ceiling=3 → min(2,3)=2
    assert result["helper_count"] == 2


def test_rtx3060_32gb_t3_plus(catalog):
    """RTX 3060 12GB + Ryzen 7 5800X (8c/16t) + 32GB DDR4 — T3-plus."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_name="RTX 3060 12GB",
        gpu_vram_total_gb=12,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda", "vulkan"],
        cpu_physical_cores=8,
        cpu_threads=16,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=10.5, ram_free_gb=26.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T3-plus"
    assert result["orchestrator"]["model"] == "qwen3.5-9b-claude-opus-reasoning-distilled"
    assert result["orchestrator"]["quant"] == "Q6_K"


def test_gpu_less_32gb_ddr5_cl1_minimum(catalog):
    """GPU-less 32GB DDR5 dual-channel 6-core — CL1-minimum (CPU-only)."""
    fp = HardwareFingerprint(
        gpu_vendor="intel",
        gpu_name="Iris Xe (integrated)",
        gpu_vram_total_gb=0,
        gpu_is_integrated=True,
        gpu_fp16_support=False,
        gpu_backends_available=[],
        cpu_physical_cores=6,
        cpu_threads=12,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr5",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=22.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL1-minimum"
    assert result["orchestrator"]["model"] == "qwen3.5-4b-claude-opus-reasoning-distilled-v2"
    assert result["orchestrator"]["quant"] == "Q5_K_M"


def test_4gb_polaris_rejects(catalog):
    """4GB Polaris + 8GB RAM — must reject, not silently CPU-fallback."""
    fp = HardwareFingerprint(
        gpu_vendor="amd",
        gpu_name="RX 570 4GB",
        gpu_vram_total_gb=4,
        gpu_fp16_support=False,
        gpu_backends_available=["vulkan"],
        cpu_physical_cores=4,
        cpu_threads=4,
        cpu_isa_flags=["avx2"],
        ram_total_gb=8,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=2.8, ram_free_gb=4.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "reject"
    assert result["recommended_setup_mode"] == "byo"
    assert result["orchestrator"] is None


# ===========================================================================
# Ranking tests — best-fitting plan is selected (descending rank)
# ===========================================================================

def test_16gb_fp16_gpu_gets_t4_high(catalog):
    """16GB VRAM + fp16 → T4-high, not T3-plus."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=16,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda", "vulkan"],
        cpu_physical_cores=8,
        cpu_threads=16,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr5",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=14.0, ram_free_gb=26.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T4-high"
    assert result["orchestrator"]["model"] == "qwen3.5-9b-claude-opus-reasoning-distilled"
    assert result["orchestrator"]["quant"] == "Q8_0"


def test_8gb_fp16_gpu_gets_t2_not_t1(catalog):
    """8GB VRAM + fp16 → T2-standard-fp16, NOT T1-floor-fp32."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=8,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda", "vulkan"],
        cpu_physical_cores=6,
        cpu_threads=12,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=6.0, ram_free_gb=11.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T2-standard-fp16"
    assert result["orchestrator"]["model"] == "qwen3.5-9b-claude-opus-reasoning-distilled"


def test_24gb_fp16_gpu_gets_t5_workstation(catalog):
    """24GB VRAM + fp16 → T5-workstation."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=24,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda", "vulkan"],
        cpu_physical_cores=16,
        cpu_threads=24,
        cpu_isa_flags=["avx2"],
        ram_total_gb=48,
        ram_type="ddr5",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=22.0, ram_free_gb=40.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T5-workstation"
    assert result["orchestrator"]["model"] == "qwen3.5-27b"


def test_32gb_fp16_gpu_gets_t6_enthusiast(catalog):
    """32GB VRAM + fp16 → T6-enthusiast."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=32,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda", "vulkan"],
        cpu_physical_cores=16,
        cpu_threads=24,
        cpu_isa_flags=["avx2"],
        ram_total_gb=64,
        ram_type="ddr5",
        ram_channels=4,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=28.0, ram_free_gb=56.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "gpu"
    assert result["plan_id"] == "T6-enthusiast"
    assert result["orchestrator"]["model"] == "qwen3.6-35b-a3b"


# ===========================================================================
# Apple Silicon tests
# ===========================================================================

def test_apple_48gb_gets_a4(catalog):
    """Apple Silicon 48GB → A4."""
    fp = HardwareFingerprint(
        gpu_vendor="apple",
        unified_mem_gb=48,
        os="macos",
        cpu_physical_cores=10,
        cpu_threads=10,
        cpu_isa_flags=["avx2"],
        ram_total_gb=48,
    )
    live = LiveFreeResources(gpu_vram_free_gb=40.0, ram_free_gb=38.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "apple"
    assert result["plan_id"] == "A4"
    assert result["orchestrator"]["model"] == "qwen3.6-35b-a3b"


def test_apple_32gb_gets_a3(catalog):
    """Apple Silicon 32GB → A3."""
    fp = HardwareFingerprint(
        gpu_vendor="apple",
        unified_mem_gb=32,
        os="macos",
        cpu_physical_cores=8,
        cpu_threads=8,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
    )
    live = LiveFreeResources(gpu_vram_free_gb=26.0, ram_free_gb=24.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "apple"
    assert result["plan_id"] == "A3"
    assert result["orchestrator"]["model"] == "qwen3.5-27b"


# ===========================================================================
# CPU-only tier tests
# ===========================================================================

def test_cl3_strong(catalog):
    """64GB DDR5 dual-channel 12-core → CL3-strong, MoE orchestrator."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=12,
        cpu_threads=24,
        cpu_isa_flags=["avx2"],
        ram_total_gb=64,
        ram_type="ddr5",
        ram_channels=2,
        os="linux",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=50.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL3-strong"
    assert result["orchestrator"]["model"] == "qwen3.6-35b-a3b"


def test_cl4_workstation(catalog):
    """96GB DDR5 quad-channel 16-core → CL4-workstation."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=16,
        cpu_threads=32,
        cpu_isa_flags=["avx2"],
        ram_total_gb=96,
        ram_type="ddr5",
        ram_channels=4,
        os="linux",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=80.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL4-workstation"


def test_cl0_lite_below_32gb(catalog):
    """32GB DDR4 single-channel → CL0-lite (fails CL1's DDR5+channels requirement)."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=6,
        cpu_threads=6,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr4",
        ram_channels=1,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=22.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL0-lite"


# ===========================================================================
# Conservative detection tests — unknown fields block higher tiers
# ===========================================================================

def test_unknown_ram_channels_blocks_cl1(catalog):
    """Unknown RAM channels → cannot qualify for CL1-minimum."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=6,
        cpu_threads=12,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr5",
        ram_channels=0,  # unknown
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=22.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL0-lite"


def test_missing_avx2_blocks_cpu_only_tiers(catalog):
    """No AVX2 detected → CPU-only tiers blocked."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=12,
        cpu_threads=24,
        cpu_isa_flags=[],  # no AVX2
        ram_total_gb=64,
        ram_type="ddr5",
        ram_channels=2,
        os="linux",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=50.0)
    result = choose_and_validate(fp, catalog, live)

    # CL1 requires avx2, CL0 does not — but CL0 requires ram_gb >= 16 which is met
    # However, CL0 is the only tier that doesn't require avx2
    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL0-lite"


def test_amd_no_vulkan_skips_t1(catalog):
    """8GB AMD GPU without Vulkan → cannot match T1-floor-fp32."""
    fp = HardwareFingerprint(
        gpu_vendor="amd",
        gpu_vram_total_gb=8,
        gpu_fp16_support=False,
        gpu_backends_available=[],  # no Vulkan
        cpu_physical_cores=6,
        cpu_threads=6,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=6.8, ram_free_gb=11.0)
    result = choose_and_validate(fp, catalog, live)

    # T1 requires gpu_backend_any: ["vulkan"], so it should skip
    # T0 requires gpu_vram_gb >= 6 and gpu_fp16 = false — this matches
    assert result["path"] == "gpu"
    assert result["plan_id"] == "T0-subfloor"


# ===========================================================================
# Helper count tests
# ===========================================================================

def test_helper_count_c0_r16(catalog):
    """C0 (4c, peak=1) + R-16gb (ceiling=3) → min(1,3)=1."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=8,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda"],
        cpu_physical_cores=4,
        cpu_threads=4,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
    )
    assert resolve_helper_count(fp, catalog) == 1


def test_helper_count_c5_r16(catalog):
    """C5 (16c, peak=6) + R-16gb (ceiling=3) → min(6,3)=3 (RAM-bound)."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=16,
        gpu_fp16_support=True,
        gpu_backends_available=["cuda"],
        cpu_physical_cores=16,
        cpu_threads=24,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
    )
    assert resolve_helper_count(fp, catalog) == 3


def test_helper_count_c1_r32(catalog):
    """C1 (6c, peak=2) + R-32gb (ceiling=6) → min(2,6)=2."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=8,
        gpu_fp16_support=False,
        gpu_backends_available=["vulkan"],
        cpu_physical_cores=6,
        cpu_threads=6,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr5",
        ram_channels=2,
    )
    assert resolve_helper_count(fp, catalog) == 2


# ===========================================================================
# Fit tests — context shrinks when VRAM is tight
# ===========================================================================

def test_fit_gpu_context_shrinks(catalog):
    """When free VRAM is tight, fit() shrinks context from ctx_max toward ctx_min."""
    plan = {
        "orchestrator": {
            "model": "qwen3.5-9b-claude-opus-reasoning-distilled",
            "quant": "Q4_K_M",
            "device": "gpu",
            "ctx_min": 8192,
            "ctx_max": 16384,
        }
    }
    # Plenty of VRAM: full ctx_max (~4GB weight + KV cache + overhead, 12GB free → 10.2 usable)
    live_fertile = LiveFreeResources(gpu_vram_free_gb=12.0, ram_free_gb=12.0)
    result_fertile = fit(plan, catalog, live_fertile)
    assert result_fertile["ctx"] == 16384
    assert result_fertile["vram_required_gb"] > 0

    # Very tight VRAM: should clamp to ctx_min
    live_tight = LiveFreeResources(gpu_vram_free_gb=2.0, ram_free_gb=12.0)
    result_tight = fit(plan, catalog, live_tight)
    assert result_tight["ctx"] == 8192  # ctx_min


def test_fit_never_drops_below_ctx_min(catalog):
    """Fit must never produce ctx below ctx_min."""
    plan = {
        "orchestrator": {
            "model": "qwen3.5-9b-claude-opus-reasoning-distilled",
            "quant": "Q4_K_M",
            "device": "gpu",
            "ctx_min": 8192,
            "ctx_max": 16384,
        }
    }
    live_extreme = LiveFreeResources(gpu_vram_free_gb=0.1, ram_free_gb=12.0)
    result = fit(plan, catalog, live_extreme)
    assert result["ctx"] == 8192


# ===========================================================================
# Top-level routing tests
# ===========================================================================

def test_top_level_gpu(catalog):
    """NVIDIA GPU with 16GB → 'gpu' path."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia", gpu_vram_total_gb=16, gpu_fp16_support=True,
        gpu_backends_available=["cuda"], cpu_physical_cores=8, cpu_threads=16,
        cpu_isa_flags=["avx2"], ram_total_gb=32, ram_type="ddr5", ram_channels=2,
        os="linux",
    )
    path, plan = resolve_top_level(fp, catalog)
    assert path == "gpu"
    assert plan is not None
    assert plan["id"] == "T4-high"


def test_top_level_cpu_only(catalog):
    """No GPU + 64GB DDR5 → 'cpu_only' path."""
    fp = HardwareFingerprint(
        gpu_vendor="none", gpu_vram_total_gb=0, gpu_fp16_support=False,
        cpu_physical_cores=12, cpu_threads=24, cpu_isa_flags=["avx2"],
        ram_total_gb=64, ram_type="ddr5", ram_channels=2, os="linux",
    )
    path, plan = resolve_top_level(fp, catalog)
    assert path == "cpu_only"
    assert plan is not None
    assert plan["id"] == "CL3-strong"


def test_top_level_reject(catalog):
    """4GB GPU + 8GB RAM → 'reject' path."""
    fp = HardwareFingerprint(
        gpu_vendor="amd", gpu_vram_total_gb=4, gpu_fp16_support=False,
        gpu_backends_available=["vulkan"], cpu_physical_cores=4, cpu_threads=4,
        cpu_isa_flags=["avx2"], ram_total_gb=8, ram_type="ddr4", ram_channels=2,
        os="windows",
    )
    path, plan = resolve_top_level(fp, catalog)
    assert path == "reject"
    assert plan is None


# ===========================================================================
# Conservative fallback tests — missing detection fields block higher tiers
# ===========================================================================

def test_missing_ram_type_blocks_cl1(catalog):
    """Missing ram_type (unknown) → cannot qualify for CL1-minimum, falls to CL0-lite."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=6,
        cpu_threads=12,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="unknown",  # not ddr5
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=22.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL0-lite"


def test_missing_gpu_fp16_blocks_t2(catalog):
    """8GB GPU without fp16 → T1-floor-fp32, NOT T2-standard-fp16."""
    fp = HardwareFingerprint(
        gpu_vendor="nvidia",
        gpu_vram_total_gb=8,
        gpu_fp16_support=False,  # explicitly False
        gpu_backends_available=["cuda"],  # no Vulkan, so T1 blocked
        cpu_physical_cores=6,
        cpu_threads=12,
        cpu_isa_flags=["avx2"],
        ram_total_gb=16,
        ram_type="ddr4",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=6.0, ram_free_gb=11.0)
    result = choose_and_validate(fp, catalog, live)

    # T1 requires vulkan backend, T0 requires gpu_vram>=6 + gpu_fp16=false
    assert result["path"] == "gpu"
    assert result["plan_id"] == "T0-subfloor"


def test_missing_avx2_blocks_all_cpu_tiers_with_isa_requirement(catalog):
    """No AVX2 → blocks CL1+ (which requires avx2), CL0-lite has no isa requirement."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=12,
        cpu_threads=24,
        cpu_isa_flags=[],  # no AVX2
        ram_total_gb=64,
        ram_type="ddr5",
        ram_channels=2,
        os="linux",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=50.0)
    result = choose_and_validate(fp, catalog, live)

    # CL0-lite requires only ram_gb >= 16, no isa requirement
    assert result["path"] == "cpu_only"
    assert result["plan_id"] == "CL0-lite"


def test_cpu_only_path_includes_detection_warnings(catalog):
    """CPU-only path should include a warning that RAM-fit is stubbed."""
    fp = HardwareFingerprint(
        gpu_vendor="none",
        gpu_vram_total_gb=0,
        gpu_fp16_support=False,
        cpu_physical_cores=6,
        cpu_threads=12,
        cpu_isa_flags=["avx2"],
        ram_total_gb=32,
        ram_type="ddr5",
        ram_channels=2,
        os="windows",
    )
    live = LiveFreeResources(gpu_vram_free_gb=0, ram_free_gb=22.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "cpu_only"
    assert "plan_id" in result
    assert len(result.get("detection_warnings", [])) >= 1


def test_apple_path_includes_detection_warnings(catalog):
    """Apple Silicon path should include a warning that unified-memory fit is stubbed."""
    fp = HardwareFingerprint(
        gpu_vendor="apple",
        unified_mem_gb=16,
        os="macos",
        cpu_physical_cores=8,
        cpu_threads=8,
        cpu_isa_flags=[],
        ram_total_gb=16,
    )
    live = LiveFreeResources(gpu_vram_free_gb=12.0, ram_free_gb=10.0)
    result = choose_and_validate(fp, catalog, live)

    assert result["path"] == "apple"
    assert result["plan_id"] == "A1"
    assert len(result.get("detection_warnings", [])) >= 1
