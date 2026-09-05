"""Sentry integration (item 47).

Real ``sentry-sdk`` when installed (``SENTRY_DSN`` set); otherwise a
structured in-house event sink with the same API, honestly labeled
``in-house``. Capture failures never crash business logic.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.observability.metrics import log_event

_EVENTS: list[dict[str, Any]] = []


def sdk_available() -> bool:
    try:
        import sentry_sdk  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def init(*, dsn: str | None = None) -> str:
    """Initialize the real SDK when available. Returns the active backend."""
    import os

    dsn = dsn or (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        return "in-house"
    try:
        import sentry_sdk  # type: ignore

        sentry_sdk.init(dsn=dsn, traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE") or "0.1"))
        return "sentry-sdk"
    except Exception:
        return "in-house"


def backend() -> str:
    try:
        import os

        if (os.getenv("SENTRY_DSN") or "").strip() and sdk_available():
            return "sentry-sdk"
    except Exception:
        pass
    return "in-house"


def capture_event(
    message: str, *, level: str = "error", extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    ev = {
        "event_id": f"sentry_{uuid.uuid4().hex[:12]}",
        "message": message,
        "level": level,
        "extra": extra or {},
        "platform": "python",
        "sdk": backend(),
    }
    _EVENTS.append(ev)
    try:
        log_event("sentry.event", **ev)
    except Exception:
        pass
    if backend() == "sentry-sdk":
        try:
            import sentry_sdk  # type: ignore

            sentry_sdk.capture_message(message, level=level)
        except Exception:
            pass
    return ev


def capture_exception(exc: BaseException, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if backend() == "sentry-sdk":
        try:
            import sentry_sdk  # type: ignore

            sentry_sdk.capture_exception(exc)
        except Exception:
            pass
    return capture_event(f"{type(exc).__name__}: {exc}", level="error", extra=extra)


def recent_events(limit: int = 200) -> list[dict[str, Any]]:
    return list(_EVENTS[-limit:])


__all__ = [
    "capture_event",
    "capture_exception",
    "recent_events",
    "init",
    "backend",
    "sdk_available",
]
