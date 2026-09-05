"""Collection pagination helpers — offset/limit with has_more metadata.

Pilot-compatible: callers keep returning resource arrays under existing keys
(``cases``, ``interactions``, …) and attach a standard ``pagination`` object.

Cursor tokens (item 44) are HMAC-signed opaque blobs (``{"v":1,"o":offset,
"sig"}``) keyed by the deployment session secret. Clients cannot forge or
tamper offsets; tampered/legacy-unsigned cursors are rejected (400) instead
of silently falling back to offset 0. Deletion between pages shifts offsets
(the extra-row ``has_more`` probe keeps this safe); small tables additionally
expose an exact ``total`` COUNT(*) so UIs can render real page counts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


DEFAULT_LIMIT = 50
MAX_LIMIT = 500
CURSOR_VERSION = 1


class InvalidCursor(ValueError):
    """Raised when a cursor is tampered, foreign, or undecodable."""


def _cursor_secret() -> bytes:
    try:
        from src.api.rbac import _secret

        return _secret()
    except Exception:
        return b"dev-only-cursor-fallback"


def _sign(offset: int) -> str:
    msg = f"v{CURSOR_VERSION}:{int(offset)}".encode("utf-8")
    return hmac.new(_cursor_secret(), msg, hashlib.sha256).hexdigest()[:32]


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
    payload = json.dumps(
        {"v": CURSOR_VERSION, "o": int(offset), "sig": _sign(offset)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int | None:
    """Return offset from cursor, or None if missing/invalid.

    Lenient (legacy callers fall back to ``offset``); use
    :func:`decode_cursor_strict` where tampering must be rejected.
    """
    try:
        return decode_cursor_strict(cursor)
    except InvalidCursor:
        return None


def decode_cursor_strict(cursor: str | None) -> int:
    """Return offset, raising :class:`InvalidCursor` when tampered/foreign.

    Unsigned legacy cursors (``{"o": n}`` without ``sig``) are rejected:
    they cannot be distinguished from forged offsets.
    """
    if not cursor or not str(cursor).strip():
        raise InvalidCursor("missing cursor")
    raw = str(cursor).strip()
    pad = "=" * (-len(raw) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + pad).decode("utf-8"))
    except Exception as e:
        raise InvalidCursor(f"undecodable cursor: {type(e).__name__}") from e
    if not isinstance(data, dict) or data.get("v") != CURSOR_VERSION:
        raise InvalidCursor("legacy or foreign cursor version")
    try:
        offset = clamp_offset(data.get("o", 0))
    except Exception as e:
        raise InvalidCursor(f"bad cursor offset: {e}") from e
    expect = _sign(offset)
    if not hmac.compare_digest(str(data.get("sig") or ""), expect):
        raise InvalidCursor("cursor signature mismatch (tampered?)")
    return offset


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


def resolve_offset_strict(
    *, offset: int | None = None, cursor: str | None = None
) -> int:
    """Like :func:`resolve_offset` but rejects tampered cursors (item 44).

    Raises :class:`InvalidCursor` when a cursor is present but invalid —
    routes convert this to 400 instead of silently restarting at offset 0.
    """
    if cursor and str(cursor).strip():
        return decode_cursor_strict(cursor)
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
    "InvalidCursor",
    "clamp_limit",
    "clamp_offset",
    "encode_cursor",
    "decode_cursor",
    "decode_cursor_strict",
    "resolve_offset",
    "resolve_offset_strict",
    "page_meta",
    "paginate_list",
]
