"""Loader and validator for architecture_config.json.

Reads the architecture decision record at startup and validates that
the key fields required by the agent runtime are present.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = [
    "agent_runtime",
    "mcp_tools",
    "permission_broker",
    "ipc",
    "failure_modes",
]

_REQUIRED_AGENT_RUNTIME_KEYS = [
    "roles",
    "streaming",
    "orchestration",
]

_REQUIRED_ROLES = [
    "orchestrator",
    "summarizer",
    "utility",
]

_REQUIRED_STREAMING_KEYS = [
    "event_types",
    "envelope_format",
    "event_channel",
    "fields",
]

_REQUIRED_MCP_TOOLS_KEY = ["allowed"]

_REQUIRED_IPC_KEYS = [
    "mcp_proxy_transport",
    "mcp_proxy_env_var",
    "sidecar_stdout_channel",
]

_REQUIRED_FAILURE_MODE_KEYS = [
    "sidecar_startup_failure",
    "mcp_server_startup_failure",
    "worker_timeout",
    "summarizer_failure",
    "orchestrator_error",
]

_CONFIG_FILE_NAME = "architecture_config.json"


def _find_config() -> Path:
    """Locate architecture_config.json relative to this module's package."""
    module_dir = Path(__file__).resolve().parent
    candidate = module_dir / _CONFIG_FILE_NAME
    if candidate.exists():
        return candidate
    fallback = Path.cwd() / _CONFIG_FILE_NAME
    if fallback.exists():
        return fallback
    return candidate


def load_config() -> dict[str, Any]:
    """Load and validate architecture_config.json.

    Returns the parsed config dict. Raises ValueError if required keys
    are missing so that startup fails fast.
    """
    config_path = _find_config()

    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("architecture_config.json not found at %s; using defaults", config_path)
        return _default_config()
    except Exception as exc:
        logger.error("Failed to read architecture_config.json: %s", exc)
        raise

    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in architecture_config.json: %s", exc)
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    _validate_config(config)
    return config


def _validate_config(config: dict[str, Any]) -> None:
    """Raise ValueError if required top-level or nested keys are missing."""
    for key in _REQUIRED_KEYS:
        if key not in config:
            raise ValueError(f"architecture_config.json missing required key: {key}")

    # agent_runtime
    ar = config["agent_runtime"]
    for key in _REQUIRED_AGENT_RUNTIME_KEYS:
        if key not in ar:
            raise ValueError(f"agent_runtime missing required key: {key}")

    roles = ar.get("roles", {})
    for role in _REQUIRED_ROLES:
        if role not in roles:
            raise ValueError(f"agent_runtime.roles missing role: {role}")

    streaming = ar.get("streaming", {})
    for key in _REQUIRED_STREAMING_KEYS:
        if key not in streaming:
            raise ValueError(f"agent_runtime.streaming missing key: {key}")

    # mcp_tools
    mcp = config.get("mcp_tools", {})
    if "allowed" not in mcp:
        raise ValueError("mcp_tools missing 'allowed' list")
    _validate_allowed_tool_schemas(mcp["allowed"])

    # ipc
    ipc = config.get("ipc", {})
    for key in _REQUIRED_IPC_KEYS:
        if key not in ipc:
            raise ValueError(f"ipc missing key: {key}")

    # failure_modes
    fm = config.get("failure_modes", {})
    for key in _REQUIRED_FAILURE_MODE_KEYS:
        if key not in fm:
            raise ValueError(f"failure_modes missing key: {key}")

    # services (optional section, but validate if present)
    if "services" in config:
        validate_services_config(config["services"])


def _validate_allowed_tool_schemas(allowed: list[Any]) -> None:
    """Ensure every allowed tool has a canonical schema in TOOL_DEFS.

    The allowlist in architecture_config.json carries only name/description/category;
    the real input schemas live in ``mcp/tools.py::TOOL_DEFS``. An allowed tool with
    no matching TOOL_DEFS entry would be shipped to the model with empty parameters
    (the model could never call it correctly), so fail fast at startup naming the
    offending tool. Imported lazily to avoid any import-order coupling with mcp.tools.
    """
    if not isinstance(allowed, list):
        raise ValueError("mcp_tools.allowed must be a list")
    from ..mcp.tools import tool_def_by_name  # local import avoids circular coupling

    for entry in allowed:
        if not isinstance(entry, dict):
            raise ValueError(f"mcp_tools.allowed entry is not an object: {entry!r}")
        name = entry.get("name")
        if not name:
            raise ValueError("mcp_tools.allowed entry has no 'name'")
        canonical = tool_def_by_name(name)
        if canonical is None:
            raise ValueError(
                f"Allowed tool '{name}' is not defined in mcp/tools.py::TOOL_DEFS. "
                f"Add it to TOOL_DEFS or remove it from the allowlist."
            )
        if not canonical.get("inputSchema"):
            raise ValueError(
                f"TOOL_DEFS entry for '{name}' has no 'inputSchema' — the model "
                f"would receive empty parameters."
            )


def _default_config() -> dict[str, Any]:
    """Return a minimal valid config when the JSON file is absent."""
    return {
        "agent_runtime": {
            "roles": {
                "orchestrator": {"thinking_mode": "on", "thinking_filter": "xml_think_tags"},
                "summarizer": {"thinking_mode": "off"},
                "utility": {"thinking_mode": "off"},
            },
            "streaming": {
                "phase": 1,
                "event_types": ["token", "done", "error"],
                "envelope_format": "json",
                "event_channel": "agent_event",
                "fields": ["chat_id", "message_id", "type", "payload"],
            },
"orchestration": {
                 "worker_timeout_seconds": 12,
                 "max_worker_failures": None,
                 "summarizer_failure_policy": "fallback_then_error",
                 "evidence_pack_compact": True,
             },
        },
        "mcp_tools": {
            "allowed": [],
            "restricted_worker_tools": ["spawn_worker"],
            "spawn_worker_blocked_in_prompts": True,
        },
        "permission_broker": {
            "capabilities": {
                "get_location": {
                    "grant_persistence": "session",
                    "prompt_on_first_use": True,
                    "default_decision": "denied",
                }
            }
        },
        "ipc": {
            "mcp_proxy_transport": "loopback_tcp",
            "mcp_proxy_env_var": "OBRENNA_MCP_PROXY_URL",
            "default_proxy_bind": "127.0.0.1",
            "sidecar_stdout_channel": "events",
            "event_line_separator": "newline",
        },
        "failure_modes": {
            "sidecar_startup_failure": "report_error_no_fake_ui",
            "mcp_server_startup_failure": "emit_typed_error_event",
            "mcp_proxy_timeout": "return_tool_error_with_correlation_id",
            "worker_timeout": "failure_marker_in_evidence_pack",
            "summarizer_failure": "fallback_then_error",
            "orchestrator_error": "emit_typed_error_persist_clean_message",
            "frontend_disconnect": "reload_from_persisted_history",
        },
        "services": {
            "web_search": {
                "provider": "duckduckgo",
                "max_results_default": 5,
                "max_results_limit": 10,
                "timeout_seconds": 10,
                "cache_ttl_seconds": 300,
                "brave_api_key_env": "BRAVE_SEARCH_API_KEY",
                "serpapi_key_env": "SERPAPI_API_KEY",
            }
        },
    }


# Module-level cached config — loaded once at import time.
_config_cache: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """Return the cached architecture config (loaded once)."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def get_streaming_config() -> dict[str, Any]:
    """Return agent_runtime.streaming section."""
    return get_config()["agent_runtime"]["streaming"]


def get_failure_modes() -> dict[str, str]:
    """Return failure_modes section."""
    return get_config()["failure_modes"]


def get_mcp_tools_config() -> dict[str, Any]:
    """Return mcp_tools section."""
    return get_config()["mcp_tools"]


def get_permission_broker_config() -> dict[str, Any]:
    """Return permission_broker section."""
    return get_config()["permission_broker"]


def get_orchestration_config() -> dict[str, Any]:
    """Return agent_runtime.orchestration section."""
    return get_config()["agent_runtime"]["orchestration"]


def get_services_config() -> dict[str, Any]:
    """Return services section (search providers, etc.)."""
    return get_config().get("services", {})


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_SUPPORTED_PROVIDERS = ["duckduckgo", "brave", "serpapi"]


def validate_services_config(services: dict[str, Any]) -> None:
    """Validate services.web_search configuration."""
    web_search = services.get("web_search", {})
    if web_search:
        provider = web_search.get("provider", "duckduckgo")
        if provider not in DEFAULT_SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported web_search provider: {provider}. "
                f"Supported: {DEFAULT_SUPPORTED_PROVIDERS}"
            )
        max_results_limit = web_search.get("max_results_limit", 10)
        if max_results_limit < 1 or max_results_limit > 50:
            raise ValueError(
                f"web_search.max_results_limit must be between 1 and 50, got {max_results_limit}"
            )
