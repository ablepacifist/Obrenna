"""Hardware detection with a graceful mock fallback.

Real detection where cheap (CPU/RAM via psutil, NVIDIA GPU via nvidia-smi). Anything
that fails falls back to sensible mock values so the setup flow always works. The
Windows PowerShell/WMI path is left as a TODO seam.
"""
from __future__ import annotations

import platform
import subprocess
from typing import Any


def detect_hardware() -> dict[str, Any]:
    info: dict[str, Any] = {
        "os": _os_name(),
        "cpu": _cpu(),
        "ram_gb": _ram_gb(),
        "gpu": [],
        "vram_gb": None,
        "recommended_profile": "external_endpoint",
    }

    gpus = _nvidia_gpus()
    if gpus:
        info["gpu"] = gpus
        vram = max((g["vram_gb"] or 0) for g in gpus)
        info["vram_gb"] = vram or None

    info["recommended_profile"] = _recommend(info)
    return info


def _os_name() -> str:
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        platform.system(), platform.system().lower() or "unknown"
    )


def _cpu() -> str:
    # platform.processor() is often empty on Linux; fall back to a generic label.
    name = platform.processor() or platform.machine() or "Unknown CPU"
    try:
        import psutil  # noqa: PLC0415

        cores = psutil.cpu_count(logical=True)
        if cores:
            name = f"{name} — {cores}-core"
    except Exception:  # noqa: BLE001
        pass
    return name


def _ram_gb() -> float | None:
    try:
        import psutil  # noqa: PLC0415

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:  # noqa: BLE001
        return None


def _nvidia_gpus() -> list[dict[str, Any]]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return []
        gpus: list[dict[str, Any]] = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    vram_gb = round(float(parts[1]) / 1024, 1)
                except ValueError:
                    vram_gb = None
                gpus.append({"name": parts[0], "vram_gb": vram_gb})
        return gpus
    except Exception:  # noqa: BLE001 - no NVIDIA GPU / driver
        return []


def _recommend(info: dict[str, Any]) -> str:
    vram = info.get("vram_gb")
    ram = info.get("ram_gb") or 0
    # Enough dedicated VRAM, or lots of (e.g. unified) memory -> local is viable.
    if (vram and vram >= 8) or ram >= 24:
        return "local"
    return "external_endpoint"
