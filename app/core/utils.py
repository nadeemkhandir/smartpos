"""
Small shared helpers: UTC timestamps and input tidying.

Timestamps are stored as ISO-8601 UTC strings ("2026-09-10T14:03:11+00:00").
SQLite has no date type, and a sortable, timezone-explicit string keeps the
column readable and comparable with plain ``<`` / ``>``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime | None) -> str | None:
    """Serialise a datetime for storage, normalising it to UTC first."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(value: str | None) -> datetime | None:
    """Parse a stored timestamp, tolerating rows written without a zone."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def seconds_from_now(seconds: float) -> datetime:
    return utcnow() + timedelta(seconds=seconds)


def minutes_from_now(minutes: float) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def days_from_now(days: int) -> datetime:
    return utcnow() + timedelta(days=days)


def seconds_until(moment: datetime | None) -> int:
    """Whole seconds left before ``moment``; 0 once it has passed."""
    if moment is None:
        return 0
    return max(0, int((moment - utcnow()).total_seconds()))


def is_expired(moment: datetime | None) -> bool:
    return moment is None or moment <= utcnow()


def normalise_username(value: str | None) -> str:
    return (value or "").strip()


def normalise_email(value: str | None) -> str:
    return (value or "").strip().lower()


def is_email(value: str | None) -> bool:
    return bool(value) and bool(EMAIL_PATTERN.match(value.strip()))


def humanise_seconds(total: int) -> str:
    """``95`` -> ``1 minute 35 seconds``, for lockout and resend messages."""
    total = max(0, int(total))
    minutes, seconds = divmod(total, 60)

    parts = []
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds or not parts:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return " ".join(parts)
