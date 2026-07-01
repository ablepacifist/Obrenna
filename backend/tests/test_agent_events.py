"""Tests for agent streaming events."""
import json

from app.agent.events import (
    CHANNEL_AGENT_EVENT,
    EVENT_TYPE_DONE,
    EVENT_TYPE_ERROR,
    EVENT_TYPE_THINKING_DELTA,
    EVENT_TYPE_TOKEN,
    StreamEvent,
    done_event,
    error_event,
    thinking_delta_event,
    token_event,
    new_message_id,
)


def test_token_event_envelope():
    """Test token event produces correct envelope."""
    evt = token_event("chat1", "hello", "msg1")
    env = evt.to_envelope()
    assert env["channel"] == CHANNEL_AGENT_EVENT
    assert env["chat_id"] == "chat1"
    assert env["type"] == EVENT_TYPE_TOKEN
    assert env["payload"]["text"] == "hello"
    assert env["message_id"] == "msg1"


def test_done_event_envelope():
    """Test done event produces correct envelope."""
    evt = done_event("chat1", "msg1", "summary text")
    env = evt.to_envelope()
    assert env["type"] == EVENT_TYPE_DONE
    assert env["payload"]["summary"] == "summary text"


def test_error_event_envelope():
    """Test error event produces correct envelope."""
    evt = error_event("chat1", "timeout", "Worker timed out", False)
    env = evt.to_envelope()
    assert env["type"] == EVENT_TYPE_ERROR
    assert env["payload"]["error_code"] == "timeout"
    assert env["payload"]["recoverable"] is False


def test_stream_event_json_line():
    """Test StreamEvent serializes to valid JSON line."""
    evt = StreamEvent(
        chat_id="chat1",
        message_id="msg1",
        type=EVENT_TYPE_TOKEN,
        payload={"text": "test"},
    )
    line = evt.to_json_line()
    parsed = json.loads(line)
    assert parsed["type"] == EVENT_TYPE_TOKEN


def test_new_message_id_uniqueness():
    """Test that generated message IDs are unique."""
    ids = {new_message_id() for _ in range(100)}
    assert len(ids) == 100


def test_event_type_constants():
    """Test event type constants."""
    assert EVENT_TYPE_TOKEN == "token"
    assert EVENT_TYPE_DONE == "done"
    assert EVENT_TYPE_ERROR == "error"
    assert CHANNEL_AGENT_EVENT == "agent_event"


def test_thinking_delta_event_shape():
    """Test thinking_delta event produces the correct envelope."""
    evt = thinking_delta_event("chat1", text="reasoning chunk", message_id="msg1")
    env = evt.to_envelope()
    assert env["channel"] == CHANNEL_AGENT_EVENT
    assert env["chat_id"] == "chat1"
    assert env["type"] == EVENT_TYPE_THINKING_DELTA
    assert env["type"] == "thinking_delta"
    assert env["payload"]["text"] == "reasoning chunk"
    assert env["message_id"] == "msg1"

    line = evt.to_json_line()
    parsed = json.loads(line)
    assert parsed["type"] == "thinking_delta"
    assert parsed["payload"]["text"] == "reasoning chunk"
