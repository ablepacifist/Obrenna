"""Ephemeral runtime context helpers for date/time grounding.

This module provides per-turn clock context for orchestrator prompts.
Values are always computed at runtime and must not be persisted as memory.
"""
from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Winnipeg"


@dataclass(frozen=True)
class RuntimeClockContext:
    iso_datetime: str
    human_date: str
    timezone: str
    weekday: str
    year: int
    date_iso: str
    time_iso: str
    utc_offset: str


def get_runtime_clock_context(timezone: str | None = None) -> RuntimeClockContext:
    """Return runtime clock context using configured timezone if available."""
    selected_timezone = (timezone or os.getenv("OBRENNA_TIMEZONE") or DEFAULT_TIMEZONE).strip()

    try:
        now = datetime.datetime.now(ZoneInfo(selected_timezone))
        timezone_name = selected_timezone
    except ZoneInfoNotFoundError:
        now = datetime.datetime.now().astimezone()
        timezone_name = now.tzname() or "Local"

    return RuntimeClockContext(
        iso_datetime=now.isoformat(),
        human_date=now.strftime("%A, %B %d, %Y"),
        timezone=timezone_name,
        weekday=now.strftime("%A"),
        year=now.year,
        date_iso=now.strftime("%Y-%m-%d"),
        time_iso=now.strftime("%H:%M:%S"),
        utc_offset=now.strftime("%z"),
    )


_RELATIVE_DATE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("today", r"\btoday\b"),
    ("tomorrow", r"\btomorrow\b"),
    ("yesterday", r"\byesterday\b"),
    ("this_week", r"\bthis\s+week\b"),
    ("last_week", r"\blast\s+week\b"),
    ("next_week", r"\bnext\s+week\b"),
    ("this_month", r"\bthis\s+month\b"),
    ("last_month", r"\blast\s+month\b"),
    ("this_year", r"\bthis\s+year\b"),
    ("last_year", r"\blast\s+year\b"),
)


def _week_range(anchor_date: datetime.date) -> str:
    """Return ISO week range Monday..Sunday for ``anchor_date``."""
    start = anchor_date - datetime.timedelta(days=anchor_date.weekday())
    end = start + datetime.timedelta(days=6)
    return f"{start.isoformat()}..{end.isoformat()}"


def _month_shift(anchor_date: datetime.date, delta_months: int) -> tuple[int, int]:
    """Shift month from ``anchor_date`` by ``delta_months`` and return (year, month)."""
    month_index = (anchor_date.year * 12 + (anchor_date.month - 1)) + delta_months
    year = month_index // 12
    month = (month_index % 12) + 1
    return year, month


def resolve_relative_date_hints(
    user_message: str,
    *,
    timezone: str | None = None,
) -> dict[str, str] | None:
    """Resolve relative-date phrases from ``user_message`` against runtime clock."""
    msg = (user_message or "").lower()
    matches = [key for key, pattern in _RELATIVE_DATE_PATTERNS if re.search(pattern, msg)]
    if not matches:
        return None

    clock = get_runtime_clock_context(timezone)
    today = datetime.date.fromisoformat(clock.date_iso)
    resolved: dict[str, str] = {
        "runtime_today": today.isoformat(),
        "runtime_year": str(clock.year),
    }

    for key in matches:
        if key == "today":
            resolved["today"] = today.isoformat()
        elif key == "tomorrow":
            resolved["tomorrow"] = (today + datetime.timedelta(days=1)).isoformat()
        elif key == "yesterday":
            resolved["yesterday"] = (today - datetime.timedelta(days=1)).isoformat()
        elif key == "this_week":
            resolved["this_week"] = _week_range(today)
        elif key == "last_week":
            resolved["last_week"] = _week_range(today - datetime.timedelta(days=7))
        elif key == "next_week":
            resolved["next_week"] = _week_range(today + datetime.timedelta(days=7))
        elif key == "this_month":
            resolved["this_month"] = today.strftime("%Y-%m")
        elif key == "last_month":
            y, m = _month_shift(today, -1)
            resolved["last_month"] = f"{y:04d}-{m:02d}"
        elif key == "this_year":
            resolved["this_year"] = str(today.year)
        elif key == "last_year":
            resolved["last_year"] = str(today.year - 1)

    return resolved


def build_relative_date_hint_message(
    user_message: str,
    *,
    timezone: str | None = None,
) -> dict[str, str] | None:
    """Build compact relative-date resolution hint message when phrases are present."""
    resolved = resolve_relative_date_hints(user_message, timezone=timezone)
    if not resolved:
        return None
    parts = [f"- {k}: {v}" for k, v in resolved.items()]
    return {
        "role": "system",
        "name": "runtime_relative_dates",
        "content": "Resolved relative dates for this request:\n" + "\n".join(parts),
    }


def build_runtime_context_message(*, compact: bool = False, timezone: str | None = None) -> dict[str, str]:
    """Build an ephemeral runtime context system message for the orchestrator."""
    clock = get_runtime_clock_context(timezone)
    if compact:
        content = (
            f"Today is {clock.human_date}.\n"
            f"Current year: {clock.year}.\n"
            f"Current date: {clock.date_iso}.\n"
            f"Timezone: {clock.timezone} (UTC offset {clock.utc_offset}).\n"
            "Resolve relative dates using this date.\n"
            "Use get_time for exact current time."
        )
    else:
        content = (
            "Runtime context:\n"
            f"- Today is {clock.human_date}.\n"
            f"- Current year is {clock.year}.\n"
            f"- Current local date is {clock.date_iso}.\n"
            f"- Current local timezone is {clock.timezone} (UTC offset {clock.utc_offset}).\n"
            f"- Current local datetime is {clock.iso_datetime}.\n"
            "- Treat relative dates like today, tomorrow, yesterday, last year, next month, "
            "and this quarter relative to this runtime context.\n"
            "- If the user asks for exact current time, timezone conversion, or live clock data, use get_time."
        )
    return {
        "role": "system",
        "name": "runtime_context_clock",
        "content": content,
    }
