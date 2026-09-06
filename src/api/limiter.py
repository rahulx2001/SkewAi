"""Shared rate-limiter singleton for the Skew AI API.

Imported by `src/api/main.py` (which attaches it to the app) and by route
modules (which use the `@limiter.limit(...)` decorator).

slowapi uses an in-memory counter by default; swap for Redis in production
via ``RATELIMIT_STORAGE_URI`` (slowapi/limits). The key function prefers
session / API-key identity over client IP so a Vite proxy or reverse proxy
does not collapse every browser into one global bucket.
"""

from __future__ import annotations

import hashlib
import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def rate_limit_key(request) -> str:
    """Bucket by principal when present, else client IP."""
    api_key = (request.headers.get("x-api-key") or "").strip()
    if not api_key:
        auth = (request.headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    session = (request.headers.get("x-frontline-session") or "").strip()
    if not session:
        try:
            from src.api.rbac import session_token_from_cookies

            session = session_token_from_cookies(getattr(request, "cookies", {}) or {})
        except Exception:
            session = ""
    session = (session or "").strip()
    ident = session or api_key
    if ident:
        digest = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:16]
        kind = "sess" if session else "key"
        return f"{kind}:{digest}"
    return get_remote_address(request)


_default = os.getenv("RATE_LIMIT_DEFAULT", "300 per hour")
_storage = (os.getenv("RATELIMIT_STORAGE_URI") or os.getenv("RATE_LIMIT_STORAGE_URI") or "").strip()
_kwargs: dict = {"key_func": rate_limit_key, "default_limits": [_default]}
if _storage:
    _kwargs["storage_uri"] = _storage
limiter = Limiter(**_kwargs)

# WebSocket connect budget (slowapi is HTTP-only). 30 connects / 60s / client.
_WS_CONNECT_LIMIT = 30
_WS_WINDOW_S = 60.0
_ws_hits: dict[str, list[float]] = {}


def check_ws_connect_rate(client_key: str) -> bool:
    """Return True if this WebSocket connect is within budget."""
    import time

    now = time.time()
    key = (client_key or "unknown").strip() or "unknown"
    window = [t for t in _ws_hits.get(key, []) if now - t < _WS_WINDOW_S]
    if len(window) >= _WS_CONNECT_LIMIT:
        _ws_hits[key] = window
        return False
    window.append(now)
    _ws_hits[key] = window
    return True


__all__ = ["limiter", "rate_limit_key", "check_ws_connect_rate"]
