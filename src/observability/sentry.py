"""Sentry-compatible event capture (no hard sentry-sdk dependency)."""

from __future__ import annotations

from typing import Any

from src.observability.metrics import log_event

_EVENTS: list[dict[str, Any]] = []


def capture_event(message: str, *, level: str = "error", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ev = {
        "event_id": f"sentry_{len(_EVENTS)+1}",
        "message": message,
        "level": level,
        "extra": extra or {},
        "platform": "python",
        "sdk": "skew-sentry-compat",
    }
    _EVENTS.append(ev)
    log_event("sentry.event", **ev)
    return ev


def recent_events() -> list[dict[str, Any]]:
    return list(_EVENTS)


__all__ = ["capture_event", "recent_events"]
