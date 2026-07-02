"""Tests for ephemeral runtime clock context helpers."""

from datetime import datetime

from app.services.runtime_context import (
    build_runtime_context_message,
    build_relative_date_hint_message,
    get_runtime_clock_context,
    resolve_relative_date_hints,
)


class TestRuntimeClockContext:
    def test_returns_dynamic_current_clock_fields(self):
        context = get_runtime_clock_context()
        parsed = datetime.fromisoformat(context.iso_datetime)

        assert context.year == parsed.year
        assert context.date_iso == parsed.strftime("%Y-%m-%d")
        assert context.timezone
        assert context.utc_offset

    def test_compact_runtime_message_shape(self):
        message = build_runtime_context_message(compact=True)
        assert message["role"] == "system"
        assert message["name"] == "runtime_context_clock"
        assert "Today is" in message["content"]
        assert "Current year:" in message["content"]
        assert "Current date:" in message["content"]
        assert "Resolve relative dates" in message["content"]

    def test_full_runtime_message_shape(self):
        message = build_runtime_context_message(compact=False)
        assert message["role"] == "system"
        assert message["name"] == "runtime_context_clock"
        assert "Runtime context:" in message["content"]
        assert "Current year is" in message["content"]
        assert "Current local date is" in message["content"]
        assert "Current local datetime is" in message["content"]

    def test_resolve_relative_date_hints_last_year(self):
        resolved = resolve_relative_date_hints("Show me last year revenue")
        assert resolved is not None
        assert "last_year" in resolved
        assert int(resolved["last_year"]) == int(resolved["runtime_year"]) - 1

    def test_resolve_relative_date_hints_empty_when_no_phrases(self):
        resolved = resolve_relative_date_hints("Summarize quarterly trends")
        assert resolved is None

    def test_build_relative_date_hint_message(self):
        message = build_relative_date_hint_message("What happened this week and last year?")
        assert message is not None
        assert message["role"] == "system"
        assert message["name"] == "runtime_relative_dates"
        assert "this_week" in message["content"]
        assert "last_year" in message["content"]
