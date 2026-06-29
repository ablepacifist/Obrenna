"""Hardware detection with a graceful mock fallback.

Probes stable facts needed by the resolver (GPU vendor, fp16 support,
CPU cores, ISA flags, RAM channels, etc.) with best-effort logic. Anything
that fails falls back to conservative defaults so the setup flow always works.

The Windows/macOS full probe path is left as TODOs for future implementation.
"""
from __future__ import annotations

import platform
import subprocess
from typing import Any

from .hardware_resolver import (
    HardwareFingerprint,
    LiveFreeResources,
    build_fingerprint,
    choose_and_validate,
)
from .hardware_catalog import load_catalog


def detect_hardware() -> dict[str, Any]:
    """Return a display-friendly hardware summary (backward-compatible)."""
    info = _probe_all()
    return _build_display_summary(info)


def probe_all() -> dict[str, Any]:
    """Return the full probe dict (stable facts + live resources)."""
    return _probe_all()


def resolve_managed_plan(detected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a managed plan from detected hardware.

    Args:
        detected: Probe dict. If None, calls _probe_all() first.

    Returns:
        ManagedPlanResponse dict (see hardware_resolver.choose_and_validate).
    """
    if detected is None:
        detected = _probe_all()

    fp = build_fingerprint(detected)
    live = LiveFreeResources(
        gpu_vram_free_gb=detected.get("gpu_vram_free_gb") or 0.0,
        ram_free_gb=detected.get("ram_free_gb") or 0.0,
    )

    catalog = load_catalog()
    plan = choose_and_validate(fp, catalog, live)

    # Add detection warnings based on incomplete probing
    plan["detection_warnings"] = _compute_warnings(detected)
    return plan


def _probe_all() -> dict[str, Any]:
    """Probe all hardware facts needed by the resolver.

    Returns a dict with both stable facts and live resources.
    """
    os_name = _os_name()
    probe: dict[str, Any] = {
        "os": os_name,
        "cpu_physical_cores": _cpu_physical_cores(),
        "cpu_threads": _cpu_threads(),
        "cpu_isa_flags": _cpu_isa_flags(),
        "ram_total_gb": _ram_total_gb(),
        "ram_type": _ram_type(os_name),
        "ram_channels": _ram_channels(os_name),
        "storage_is_ssd": True,  # best-effort: assume SSD
        "driver_version": "",
        "gpu_vendor": "none",
        "gpu_name": "",
        "gpu_vram_total_gb": 0.0,
        "gpu_vram_free_gb": 0.0,
        "gpu_fp16_support": False,
        "gpu_backends_available": [],
        "gpu_is_integrated": False,
        "unified_mem_gb": 0.0,
    }

    # GPU probing
    _probe_nvidia(probe)
    if probe["gpu_vendor"] == "none":
        _probe_apple(probe)
    if probe["gpu_vendor"] == "none":
        _probe_generic_gpu(probe, os_name)

    return probe


def _os_name() -> str:
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        platform.system(), platform.system().lower() or "unknown"
    )


def _cpu_physical_cores() -> int:
    try:
        import psutil
        cores = psutil.cpu_count(logical=False)
        return cores or 0
    except Exception:
        return 0


def _cpu_threads() -> int:
    try:
        import psutil
        threads = psutil.cpu_count(logical=True)
        return threads or 0
    except Exception:
        return 0


def _cpu_isa_flags() -> list[str]:
    """Detect CPU ISA flags. Best-effort for now."""
    flags: list[str] = []
    try:
        # AVX2: check via sysctl on macOS, lscpu on Linux, or CPUID on Windows
        system = platform.system()
        if system == "Darwin":
            try:
                out = subprocess.check_output(
                    ["sysctl", "machdep.cpu.features"],
                    stderr=subprocess.DEVNULL,
                ).decode().strip()
                if "AVX2" in out:
                    flags.append("avx2")
            except Exception:
                pass
        elif system == "Linux":
            try:
                with open("/proc/cpuinfo") as f:
                    content = f.read()
                if "avx2" in content.lower():
                    flags.append("avx2")
            except Exception:
                pass
        elif system == "Windows":
            # Best-effort: assume AVX2 on modern Windows machines
            # TODO: probe via CPUID instruction
            try:
                import psutil
                if psutil.cpu_count(logical=True) >= 4:
                    flags.append("avx2")
            except Exception:
                pass
    except Exception:
        pass

    # TODO: AVX-512 detection via CPUID (critical for Intel 12th+ gen fusion)
    return flags


def _ram_total_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return None


def _ram_type(os_name: str) -> str:
    """Detect RAM type (DDR4/DDR5). Best-effort."""
    try:
        system = platform.system()
        if system == "Darwin":
            # macOS doesn't expose DDR type reliably
            return "unknown"
        elif system == "Linux":
            try:
                out = subprocess.check_output(
                    ["dmidecode", "-t", "memory"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                if "DDR5" in out:
                    return "ddr5"
                if "DDR4" in out:
                    return "ddr4"
            except Exception:
                pass
        elif system == "Windows":
            # TODO: query WMI Win32_PhysicalMemory for MemoryType
            pass
    except Exception:
        pass
    return "unknown"


def _ram_channels(os_name: str) -> int:
    """Detect RAM channel count. Best-effort."""
    try:
        system = platform.system()
        if system == "Darwin":
            # macOS: check via memory bus configuration
            # TODO: more precise detection
            return 2  # unified memory on Apple Silicon is effectively dual
        elif system == "Linux":
            try:
                out = subprocess.check_output(
                    ["lshw", "-class", "memory", "-short"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                # Count slots in use as rough proxy
                return max(1, out.count("DIMM"))
            except Exception:
                return 1
        elif system == "Windows":
            # TODO: query WMI Win32_PhysicalMemoryArray
            pass
    except Exception:
        pass
    return 0  # unknown — resolver will degrade conservatively


def _probe_nvidia(probe: dict[str, Any]) -> None:
    """Probe NVIDIA GPUs via nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return

        gpus: list[dict[str, Any]] = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    vram_total = round(float(parts[1]) / 1024, 1)
                    vram_free = round(float(parts[2]) / 1024, 1)
                except ValueError:
                    continue
                gpus.append({
                    "name": parts[0],
                    "vram_total_gb": vram_total,
                    "vram_free_gb": vram_free,
                })

        if gpus:
            # Pick the discrete GPU with the most VRAM
            best = max(gpus, key=lambda g: g["vram_total_gb"])
            probe["gpu_vendor"] = "nvidia"
            probe["gpu_name"] = best["name"]
            probe["gpu_vram_total_gb"] = best["vram_total_gb"]
            probe["gpu_vram_free_gb"] = best["vram_free_gb"]
            # NVIDIA GPUs with compute capability 6.0+ support fp16
            # Best-effort: assume fp16 if VRAM >= 4GB (Pascal+)
            probe["gpu_fp16_support"] = best["vram_total_gb"] >= 4
            probe["gpu_backends_available"] = ["cuda", "vulkan"]
            probe["gpu_is_integrated"] = False
    except Exception:
        pass  # No NVIDIA GPU / driver


def _probe_apple(probe: dict[str, Any]) -> None:
    """Probe Apple Silicon unified memory."""
    if platform.system() != "Darwin":
        return

    try:
        import psutil
        total_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        if total_gb >= 8:
            probe["gpu_vendor"] = "apple"
            probe["unified_mem_gb"] = total_gb
            # Apple Silicon: fp16 supported, Metal backend
            probe["gpu_fp16_support"] = True
            probe["gpu_backends_available"] = ["metal"]
            probe["gpu_is_integrated"] = True
            # Apple Silicon: free memory is shared
            try:
                free_gb = round(psutil.virtual_memory().available / (1024 ** 3), 1)
                probe["gpu_vram_free_gb"] = free_gb
                probe["ram_free_gb"] = free_gb
            except Exception:
                probe["gpu_vram_free_gb"] = 0.0
                probe["ram_free_gb"] = 0.0
    except Exception:
        pass


def _probe_generic_gpu(probe: dict[str, Any], os_name: str) -> None:
    """Probe non-NVIDIA GPUs. Best-effort."""
    system = platform.system()

    if system == "Linux":
        # Try to detect AMD/Intel via Vulkan or lspci
        try:
            out = subprocess.check_output(
                ["lspci", "-vnni"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            if "vga" in out.lower() or "3d" in out.lower():
                # GPU detected via lspci
                if "amd" in out.lower() or "ati" in out.lower() or "radeon" in out.lower():
                    probe["gpu_vendor"] = "amd"
                elif "intel" in out.lower():
                    probe["gpu_vendor"] = "intel"

                probe["gpu_backends_available"] = ["vulkan"]
                probe["gpu_fp16_support"] = False  # conservative default

                # Try to get VRAM from lspci or /sys
                try:
                    with open("/proc/driver/nvidia/gpus/0/memory/0/dedicated_gpu_total_mem") as f:
                        probe["gpu_vram_total_gb"] = round(int(f.read().strip()) / (1024 ** 2), 1)
                except Exception:
                    pass
        except Exception:
            pass

    elif system == "Windows":
        # TODO: full Windows GPU probe via WMI, DirectX, or Vulkan
        # Best-effort: check if nvidia-smi already ran; otherwise assume no discrete GPU
        pass


def _build_display_summary(probe: dict[str, Any]) -> dict[str, Any]:
    """Build the display-friendly summary for the existing /api/system/hardware route."""
    gpu_info = []
    if probe.get("gpu_vendor") != "none":
        gpu_info.append({
            "name": probe.get("gpu_name", "Unknown GPU"),
            "vram_gb": probe.get("gpu_vram_total_gb"),
        })

    # Keep backward-compatible recommended_profile logic
    vram = probe.get("gpu_vram_total_gb") or 0
    ram = probe.get("ram_total_gb") or 0
    if (vram >= 8) or ram >= 24:
        profile = "local"
    else:
        profile = "external_endpoint"

    return {
        "os": probe["os"],
        "cpu": _cpu_display_name(probe),
        "ram_gb": probe["ram_total_gb"],
        "gpu": gpu_info,
        "vram_gb": probe.get("gpu_vram_total_gb"),
        "recommended_profile": profile,
    }


def _cpu_display_name(probe: dict[str, Any]) -> str:
    """Build a display-friendly CPU name."""
    name = platform.processor() or platform.machine() or "Unknown CPU"
    cores = probe.get("cpu_physical_cores", 0)
    if cores:
        name = f"{name} — {cores}-core"
    return name


def _compute_warnings(detected: dict[str, Any]) -> list[str]:
    """Compute detection warnings for incomplete probe data."""
    warnings: list[str] = []

    if detected.get("ram_channels", 0) == 0:
        warnings.append("RAM channel count unknown; conservative routing skipped DDR5 and dual-channel tiers.")

    if detected.get("ram_type") == "unknown":
        warnings.append("RAM type unknown; conservative routing skipped DDR5-only tiers.")

    if "avx2" not in detected.get("cpu_isa_flags", []):
        warnings.append("AVX2 support unknown; conservative routing skipped tiers requiring AVX2.")

    if detected.get("gpu_vendor") == "amd":
        if detected.get("gpu_fp16_support") is False and detected.get("gpu_backends_available"):
            pass  # AMD without fp16 is expected for older cards
        elif not detected.get("gpu_backends_available"):
            warnings.append("GPU backend support not fully detected; conservative tier selection applied.")

    return warnings
