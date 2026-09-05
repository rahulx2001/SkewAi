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

__all__ = ["limiter", "rate_limit_key"]
