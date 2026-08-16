"""Single-tenant shared-secret auth for pilot write/console paths.

Open (dev/test) mode
--------------------
Allowed only when ``FRONTLINE_OPEN_MODE=1`` **or** when neither
``FRONTLINE_AUTH_REQUIRED`` nor a non-empty ``FRONTLINE_API_KEY`` is set
(legacy local default). Production-style pilots should set::

    FRONTLINE_AUTH_REQUIRED=1
    FRONTLINE_API_KEY=<strong-secret>

Fail-closed
-----------
When ``FRONTLINE_AUTH_REQUIRED=1``, requests without a matching key are rejected
even if ``FRONTLINE_API_KEY`` is empty (forces configuration).

Credentials
-----------
HTTP: ``X-API-Key`` or ``Authorization: Bearer`` (query ``api_key`` still accepted
but discouraged).

WebSocket: prefer first-message ``{"type":"auth","api_key":"..."}`` or headers.
Query ``?api_key=`` remains a **deprecated** fallback for older clients/tests.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Query, Request, WebSocket, status


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _configured_key() -> str:
    return os.getenv("FRONTLINE_API_KEY", "").strip()


def auth_required() -> bool:
    """True when protected routes must present a valid key.

    Production-like deploys (ENV=production|staging, PILOT_HARDENED, SOC2_MODE)
    always require auth even if FRONTLINE_OPEN_MODE is mistakenly set.
    """
    try:
        from src.security.harden import is_production_like

        if is_production_like():
            return True
    except Exception:
        pass
    if _env_bool("FRONTLINE_OPEN_MODE", False):
        return False
    if _env_bool("FRONTLINE_AUTH_REQUIRED", False):
        return True
    return bool(_configured_key())


def is_open_mode() -> bool:
    return not auth_required()


def _extract_key(
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if api_key and api_key.strip():
        return api_key.strip()
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    return ""


def check_api_key(
    *,
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
    api_key: Optional[str] = None,
    allow_open: bool = True,
    allow_query_key: bool = True,
) -> None:
    """Raise 401 when auth is required and the provided key does not match.

    ``allow_open=False`` forces a configured key even when open mode is on
    (privacy-sensitive routes: DSR, etc.).
    ``allow_query_key=False`` rejects query-string keys (FIND-006 harden path).
    """
    if allow_open and is_open_mode():
        return
    expected = _configured_key()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication required (FRONTLINE_AUTH_REQUIRED=1 or "
                "privacy-sensitive route) but FRONTLINE_API_KEY is not configured."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = _extract_key(
        authorization=authorization, x_api_key=x_api_key, api_key=api_key
    )
    if not allow_query_key and api_key and not (x_api_key or authorization):
        # Key only appeared via query — reject when hardened.
        if _env_bool("FRONTLINE_AUTH_REQUIRED", False) or not allow_open:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key in query string is disabled; use X-API-Key or Authorization: Bearer.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Send X-API-Key or Authorization: Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_api_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> bool:
    """FastAPI dependency for HTTP routes."""
    # Query keys rejected unless FRONTLINE_ALLOW_QUERY_KEY=1 (hermetic/legacy opt-in).
    q = request.query_params.get("api_key")
    allow_query = _env_bool("FRONTLINE_ALLOW_QUERY_KEY", False)
    header_present = bool(
        (x_api_key and x_api_key.strip())
        or (authorization and authorization.strip())
    )
    if q and not allow_query and not header_present:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "API key in query string is disabled; use X-API-Key or "
                "Authorization: Bearer (set FRONTLINE_ALLOW_QUERY_KEY=1 only for tests)."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    check_api_key(
        authorization=authorization,
        x_api_key=x_api_key,
        api_key=q if allow_query else None,
        allow_query_key=allow_query,
    )
    return True


async def require_api_key_strict(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> bool:
    """Always require a valid API key — ignores open mode (DSR / sensitive).

    Query-string keys are rejected (use headers only).
    """
    q = request.query_params.get("api_key")
    header_present = bool(
        (x_api_key and x_api_key.strip())
        or (authorization and authorization.strip())
    )
    if q and not header_present:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key in query string is disabled for this route; use X-API-Key or Authorization: Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    check_api_key(
        authorization=authorization,
        x_api_key=x_api_key,
        api_key=None,
        allow_open=False,
        allow_query_key=False,
    )
    return True


async def require_ws_api_key(
    api_key: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> bool:
    """FastAPI dependency for WebSocket routes (headers preferred; query deprecated)."""
    check_api_key(authorization=authorization, x_api_key=x_api_key, api_key=api_key)
    return True


async def authenticate_websocket(websocket: WebSocket) -> None:
    """Authenticate a WebSocket before or immediately after accept.

    Order:
      1. Open mode → allow
      2. Header / deprecated query key
      3. Accept + first-message ``{"type":"auth","api_key":"..."}`` (preferred for browsers)

    Raises HTTPException on failure (caller should close with 1008).
    """
    if is_open_mode():
        return

    # Headers (non-browser clients) + deprecated query
    try:
        check_api_key(
            authorization=websocket.headers.get("authorization"),
            x_api_key=websocket.headers.get("x-api-key"),
            api_key=websocket.query_params.get("api_key"),
        )
        return
    except HTTPException:
        pass

    # Browser path: first message after accept
    if websocket.client_state.name != "CONNECTED":
        await websocket.accept()
    try:
        import asyncio

        raw = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"WebSocket auth required (send auth frame first): {type(e).__name__}",
        ) from e
    if not isinstance(raw, dict) or raw.get("type") != "auth":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='WebSocket auth required: first message must be {"type":"auth","api_key":"..."}',
        )
    check_api_key(api_key=str(raw.get("api_key") or ""))


__all__ = [
    "require_api_key",
    "require_api_key_strict",
    "require_ws_api_key",
    "check_api_key",
    "authenticate_websocket",
    "auth_required",
    "is_open_mode",
    "_configured_key",
]
