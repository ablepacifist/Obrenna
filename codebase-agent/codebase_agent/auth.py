"""This agent's own durable identity.

Generated once on first run and persisted -- presented automatically on every
connection to Obrenna. The user never types or copies this value; a human
approves it once by name, in Obrenna's UI, after the agent has already
connected.
"""
from __future__ import annotations

import socket
import uuid

from .storage import DEVICE_ID_FILE, ensure_data_dir


def get_or_create_device_id() -> str:
    ensure_data_dir()
    if DEVICE_ID_FILE.exists():
        device_id = DEVICE_ID_FILE.read_text().strip()
        if device_id:
            return device_id
    device_id = uuid.uuid4().hex
    DEVICE_ID_FILE.write_text(device_id)
    return device_id


def default_device_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "Unknown device"
