"""Tests for architecture_config.json loader."""
import json
import tempfile
from pathlib import Path

import pytest

from app.services.architecture_config import (
    _validate_config,
    get_config,
    get_streaming_config,
    get_failure_modes,
    get_mcp_tools_config,
    get_permission_broker_config,
    get_orchestration_config,
    load_config,
)


def test_default_config_keys():
    """Test that default config has all required top-level keys."""
    default = {
        "agent_runtime": {
            "roles": {"orchestrator": {}, "summarizer": {}, "utility": {}},
            "streaming": {
                "event_types": ["token", "done", "error"],
                "envelope_format": "json",
                "event_channel": "agent_event",
                "fields": ["chat_id", "message_id", "type", "payload"],
            },
            "orchestration": {
                "worker_timeout_seconds": 12,
                "max_worker_failures": None,
                "summarizer_failure_policy": "hard_abort",
                "evidence_pack_compact": True,
            },
        },
        "mcp_tools": {"allowed": [], "restricted_worker_tools": [], "spawn_worker_blocked_in_prompts": True},
        "permission_broker": {"capabilities": {}},
        "ipc": {
            "mcp_proxy_transport": "loopback_tcp",
            "mcp_proxy_env_var": "OBRENNA_MCP_PROXY_URL",
            "sidecar_stdout_channel": "events",
            "event_line_separator": "newline",
        },
        "failure_modes": {
            "sidecar_startup_failure": "report_error_no_fake_ui",
            "mcp_server_startup_failure": "emit_typed_error_event",
            "worker_timeout": "failure_marker_in_evidence_pack",
            "summarizer_failure": "hard_abort_turn",
            "orchestrator_error": "emit_typed_error_persist_clean_message",
        },
    }
    _validate_config(default)  # Should not raise


def test_validate_missing_top_level_key():
    """Test that missing top-level key raises ValueError."""
    config = {"mcp_tools": {"allowed": []}, "permission_broker": {}, "ipc": {}, "failure_modes": {}}
    with pytest.raises(ValueError, match="agent_runtime"):
        _validate_config(config)


def test_validate_missing_streaming_key():
    """Test that missing streaming config key raises ValueError."""
    config = {
        "agent_runtime": {"roles": {"orchestrator": {}, "summarizer": {}, "utility": {}}, "orchestration": {}},
        "mcp_tools": {"allowed": []},
        "permission_broker": {},
        "ipc": {"mcp_proxy_transport": "tcp", "mcp_proxy_env_var": "X", "sidecar_stdout_channel": "e"},
        "failure_modes": {"sidecar_startup_failure": "e", "mcp_server_startup_failure": "e", "worker_timeout": "e",
                          "summarizer_failure": "e", "orchestrator_error": "e"},
    }
    with pytest.raises(ValueError, match="streaming"):
        _validate_config(config)


def test_validate_missing_mcp_tools_allowed():
    """Test that missing mcp_tools.allowed raises ValueError."""
    config = {
        "agent_runtime": {
            "roles": {"orchestrator": {}, "summarizer": {}, "utility": {}},
            "streaming": {"event_types": [], "envelope_format": "json", "event_channel": "e", "fields": []},
            "orchestration": {"worker_timeout_seconds": 12, "max_worker_failures": None,
                              "summarizer_failure_policy": "hard_abort", "evidence_pack_compact": True},
        },
        "mcp_tools": {},
        "permission_broker": {},
        "ipc": {"mcp_proxy_transport": "tcp", "mcp_proxy_env_var": "X", "sidecar_stdout_channel": "e"},
        "failure_modes": {"sidecar_startup_failure": "e", "mcp_server_startup_failure": "e", "worker_timeout": "e",
                          "summarizer_failure": "e", "orchestrator_error": "e"},
    }
    with pytest.raises(ValueError, match="allowed"):
        _validate_config(config)


def test_load_config_from_file():
    """Test loading from actual file."""
    config = load_config()
    assert "agent_runtime" in config
    assert "mcp_tools" in config
    assert config["ipc"]["mcp_proxy_transport"] == "loopback_tcp"


def test_get_streaming_config():
    """Test streaming config helper."""
    sc = get_streaming_config()
    assert "token" in sc["event_types"]
    assert "done" in sc["event_types"]
    assert "error" in sc["event_types"]
    assert "tool_call" in sc["event_types"]
    assert "tool_result" in sc["event_types"]
    assert "tool_progress" in sc["event_types"]
    assert sc["envelope_format"] == "json"


def test_get_failure_modes():
    """Test failure modes helper."""
    fm = get_failure_modes()
    assert fm["summarizer_failure"] == "hard_abort_turn"
    assert fm["worker_timeout"] == "failure_marker_in_evidence_pack"


def test_get_mcp_tools_config():
    """Test MCP tools config helper."""
    mcp = get_mcp_tools_config()
    assert "allowed" in mcp
    assert "spawn_worker_blocked_in_prompts" in mcp


def test_get_permission_broker_config():
    """Test permission broker config helper."""
    pb = get_permission_broker_config()
    assert "capabilities" in pb


def test_get_orchestration_config():
    """Test orchestration config helper."""
    oc = get_orchestration_config()
    assert oc["worker_timeout_seconds"] == 12
    assert oc["summarizer_failure_policy"] == "hard_abort"
