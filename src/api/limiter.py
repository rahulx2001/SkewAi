"""Shared rate-limiter singleton for the Skew AI API.

Imported by `src/api/main.py` (which attaches it to the app) and by route
modules (which use the `@limiter.limit(...)` decorator).

slowapi uses an in-memory counter by default; swap for Redis in production.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# Per-IP key. Default is moderate; sensitive routes set tighter @limiter.limit.
# Production: put Redis behind slowapi or an edge rate limiter for multi-worker.
import os

_default = os.getenv("RATE_LIMIT_DEFAULT", "300 per hour")
limiter = Limiter(key_func=get_remote_address, default_limits=[_default])

__all__ = ["limiter"]
