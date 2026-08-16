"""UTC timestamp helpers for the ops store and API wire format.

DuckDB ``TIMESTAMP`` columns store naive wall-clock values. We always write
**naive UTC** so a file moved between IST/UTC hosts does not reinterpret history.
API serialization appends ``Z`` so browsers do not treat values as local time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def to_naive_utc(dt: datetime | None = None) -> datetime:
    """Normalize to naive UTC for DuckDB TIMESTAMP inserts.

    - None → now (UTC wall clock, tz stripped)
    - aware → convert to UTC, strip tzinfo
    - naive → treated as already-UTC, returned as-is (no local shift)
    """
    if dt is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def utc_now() -> datetime:
    """Current time as naive UTC (same basis as ``to_naive_utc(None)``)."""
    return to_naive_utc(None)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Naive → assume UTC; aware → convert to UTC (for serialization)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_z(dt: datetime) -> str:
    """Serialize a datetime as ISO-8601 with trailing Z (UTC)."""
    return ensure_aware_utc(dt).isoformat().replace("+00:00", "Z")


def coerce_for_storage(value: Any) -> Any:
    """If value is datetime, return naive UTC; else pass through."""
    if isinstance(value, datetime):
        return to_naive_utc(value)
    return value


__all__ = [
    "to_naive_utc",
    "utc_now",
    "ensure_aware_utc",
    "to_iso_z",
    "coerce_for_storage",
]
