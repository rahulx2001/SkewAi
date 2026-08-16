"""Collection pagination helpers — offset/limit with has_more metadata.

Pilot-compatible: callers keep returning resource arrays under existing keys
(``cases``, ``interactions``, …) and attach a standard ``pagination`` object.

Cursor tokens are optional opaque base64 of ``offset`` for clients that prefer
cursor-style query params later without a breaking change.
"""

from __future__ import annotations

import base64
import json
from typing import Any


DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def clamp_limit(limit: int | None, *, default: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT) -> int:
    if limit is None:
        return default
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    return min(max(n, 1), max_limit)


def clamp_offset(offset: int | None) -> int:
    if offset is None:
        return 0
    try:
        n = int(offset)
    except (TypeError, ValueError):
        return 0
    return max(n, 0)


def encode_cursor(offset: int) -> str:
    payload = json.dumps({"o": int(offset)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int | None:
    """Return offset from cursor, or None if missing/invalid."""
    if not cursor or not str(cursor).strip():
        return None
    raw = str(cursor).strip()
    pad = "=" * (-len(raw) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + pad).decode("utf-8"))
        return clamp_offset(data.get("o", 0))
    except Exception:
        return None


def resolve_offset(*, offset: int | None = None, cursor: str | None = None) -> int:
    """Prefer cursor when present; else offset; else 0.

    Cursor wins so clients can follow ``next_cursor`` without fighting a default
    ``offset=0`` query parameter from frameworks.
    """
    if cursor and str(cursor).strip():
        decoded = decode_cursor(cursor)
        if decoded is not None:
            return decoded
    if offset is not None:
        return clamp_offset(offset)
    return 0


def page_meta(
    *,
    limit: int,
    offset: int,
    returned: int,
    total: int | None = None,
) -> dict[str, Any]:
    """Build pagination metadata for a page of ``returned`` items.

    ``has_more`` is true when we filled the page (returned == limit), or when
    total is known and offset+returned < total.
    """
    if total is not None:
        has_more = offset + returned < total
    else:
        has_more = returned >= limit and returned > 0
    next_offset = offset + returned if has_more else None
    meta: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "returned": returned,
        "has_more": has_more,
        "next_offset": next_offset,
        "next_cursor": encode_cursor(next_offset) if next_offset is not None else None,
    }
    if total is not None:
        meta["total"] = total
    return meta


def paginate_list(
    rows: list[Any],
    *,
    limit: int | None = None,
    offset: int | None = None,
    cursor: str | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Slice an in-memory list and return (page, pagination meta)."""
    lim = clamp_limit(limit)
    off = resolve_offset(offset=offset, cursor=cursor)
    total = len(rows)
    page = rows[off : off + lim]
    return page, page_meta(limit=lim, offset=off, returned=len(page), total=total)


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "clamp_limit",
    "clamp_offset",
    "encode_cursor",
    "decode_cursor",
    "resolve_offset",
    "page_meta",
    "paginate_list",
]
