"""Shared time helpers for the fleet package (single source for ISO timestamps)."""
from __future__ import annotations

from datetime import datetime, timezone


def iso_now() -> str:
    """UTC ISO-8601 with millisecond precision and a trailing Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
