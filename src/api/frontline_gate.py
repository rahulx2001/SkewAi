"""FRONTLINE_ENABLED gate shared by HTTP middleware and WebSocket handlers.

``BaseHTTPMiddleware`` never sees WebSocket scopes — pure ASGI middleware in
``main.py`` handles both, and WS entrypoints also call ``ensure_frontline_enabled``
before accept as defense in depth.
"""

from __future__ import annotations

import os


def frontline_enabled() -> bool:
    """Live env read so tests can toggle FRONTLINE_ENABLED without reimport."""
    raw = os.getenv("FRONTLINE_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_frontline_surface_path(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/ws/")


__all__ = ["frontline_enabled", "is_frontline_surface_path"]
