"""Typed streaming event models for the agent runtime.

Every event emitted by Python sidecar stdout follows the same JSON envelope:
  {"channel": "agent_event", "chat_id": "...", "type": "token|done|error", "payload": {...}}

Phase 1 supports: token, done, error.
Every event carries `type: str` and `payload: dict` for forward compatibility.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


# ── Event types ──────────────────────────────────────────────────────────────

EVENT_TYPE_TOKEN = "token"
EVENT_TYPE_DONE = "done"
EVENT_TYPE_ERROR = "error"
EVENT_TYPE_TOOL_CALL = "tool_call"
EVENT_TYPE_TOOL_RESULT = "tool_result"
EVENT_TYPE_TOOL_PROGRESS = "tool_progress"
VALID_EVENT_TYPES = (
    EVENT_TYPE_TOKEN, EVENT_TYPE_DONE, EVENT_TYPE_ERROR,
    EVENT_TYPE_TOOL_CALL, EVENT_TYPE_TOOL_RESULT, EVENT_TYPE_TOOL_PROGRESS,
)

CHANNEL_AGENT_EVENT = "agent_event"


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class TokenEvent:
    """Emitted per token during orchestrator streaming."""
    chat_id: str
    message_id: str = ""
    text: str = ""

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": EVENT_TYPE_TOKEN,
            "payload": {"text": self.text},
        }


@dataclass(slots=True)
class DoneEvent:
    """Emitted when the orchestrator has finished generating the response."""
    chat_id: str
    message_id: str = ""
    summary: str = ""

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": EVENT_TYPE_DONE,
            "payload": {"summary": self.summary},
        }


@dataclass(slots=True)
class ErrorEvent:
    """Emitted on any failure: orchestrator error, MCP failure, summarizer abort."""
    chat_id: str
    error_code: str = "internal_error"
    message: str = ""
    recoverable: bool = True

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": "",
            "type": EVENT_TYPE_ERROR,
            "payload": {
                "error_code": self.error_code,
                "message": self.message,
                "recoverable": self.recoverable,
            },
        }


@dataclass(slots=True)
class ToolCallEvent:
    """Emitted when the orchestrator model requests a tool call."""
    chat_id: str
    message_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": EVENT_TYPE_TOOL_CALL,
            "payload": {
                "tool_name": self.tool_name,
                "arguments": self.arguments,
                "call_id": self.call_id,
            },
        }


@dataclass(slots=True)
class ToolResultEvent:
    """Emitted after a tool has executed, containing the result."""
    chat_id: str
    message_id: str = ""
    tool_name: str = ""
    call_id: str = ""
    result: str = ""

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": EVENT_TYPE_TOOL_RESULT,
            "payload": {
                "tool_name": self.tool_name,
                "call_id": self.call_id,
                "result": self.result,
            },
        }


@dataclass(slots=True)
class ToolProgressEvent:
    """Emitted to show tool execution progress to the frontend."""
    chat_id: str
    message_id: str = ""
    tool_name: str = ""
    status: str = "pending"  # pending | running | done | error
    summary: str = ""

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": EVENT_TYPE_TOOL_PROGRESS,
            "payload": {
                "tool_name": self.tool_name,
                "status": self.status,
                "summary": self.summary,
            },
        }


# ── Generic envelope ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class StreamEvent:
    """Generic event envelope that wraps any typed event."""
    chat_id: str
    message_id: str = ""
    type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "channel": CHANNEL_AGENT_EVENT,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "type": self.type,
            "payload": self.payload,
        }

    def to_json_line(self) -> str:
        import json
        return json.dumps(self.to_envelope(), separators=(",", ":"))


# ── Factory helpers ──────────────────────────────────────────────────────────


def token_event(chat_id: str, text: str, message_id: str = "") -> StreamEvent:
    """Create a token stream event."""
    return StreamEvent(
        chat_id=chat_id,
        message_id=message_id,
        type=EVENT_TYPE_TOKEN,
        payload={"text": text},
    )


def done_event(chat_id: str, message_id: str = "", summary: str = "") -> StreamEvent:
    """Create a done stream event."""
    return StreamEvent(
        chat_id=chat_id,
        message_id=message_id,
        type=EVENT_TYPE_DONE,
        payload={"summary": summary},
    )


def error_event(
    chat_id: str,
    error_code: str = "internal_error",
    message: str = "",
    recoverable: bool = True,
) -> StreamEvent:
    """Create an error stream event."""
    return StreamEvent(
        chat_id=chat_id,
        type=EVENT_TYPE_ERROR,
        payload={
            "error_code": error_code,
            "message": message,
            "recoverable": recoverable,
        },
    )


def tool_call_event(
    chat_id: str,
    tool_name: str,
    call_id: str,
    arguments: dict[str, Any] | None = None,
    message_id: str = "",
) -> StreamEvent:
    """Create a tool call stream event."""
    return StreamEvent(
        chat_id=chat_id,
        message_id=message_id,
        type=EVENT_TYPE_TOOL_CALL,
        payload={
            "tool_name": tool_name,
            "arguments": arguments or {},
            "call_id": call_id,
        },
    )


def tool_result_event(
    chat_id: str,
    tool_name: str,
    call_id: str,
    result: str,
    message_id: str = "",
) -> StreamEvent:
    """Create a tool result stream event."""
    return StreamEvent(
        chat_id=chat_id,
        message_id=message_id,
        type=EVENT_TYPE_TOOL_RESULT,
        payload={
            "tool_name": tool_name,
            "call_id": call_id,
            "result": result,
        },
    )


def tool_progress_event(
    chat_id: str,
    tool_name: str,
    status: str = "pending",
    summary: str = "",
    message_id: str = "",
) -> StreamEvent:
    """Create a tool progress stream event."""
    return StreamEvent(
        chat_id=chat_id,
        message_id=message_id,
        type=EVENT_TYPE_TOOL_PROGRESS,
        payload={
            "tool_name": tool_name,
            "status": status,
            "summary": summary,
        },
    )


def new_message_id() -> str:
    """Generate a fresh message ID for assistant messages."""
    return uuid.uuid4().hex
