"""JSON-safe coercion for API list/detail responses (UTC timestamps)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.data.timeutil import ensure_aware_utc, to_iso_z


def ensure_utc(dt: datetime) -> datetime:
    """Normalize to aware UTC. Naive values are treated as already-UTC."""
    return ensure_aware_utc(dt)


def json_safe(value: Any) -> Any:
    """Recursively make a value JSON-serializable; datetimes → ISO-8601 UTC with Z."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return to_iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return str(value)


def json_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [json_safe(r) for r in rows]


__all__ = ["json_safe", "json_safe_rows", "ensure_utc"]
