"""OTel-compatible span emitter (no hard OpenTelemetry dependency)."""

from __future__ import annotations

import time
from typing import Any

from src.observability.metrics import log_event

_SPANS: list[dict[str, Any]] = []


def emit_span(name: str, *, attributes: dict[str, Any] | None = None, duration_ms: float = 1.0) -> dict[str, Any]:
    span = {
        "name": name,
        "trace_id": f"tr_{int(time.time() * 1000)}",
        "span_id": f"sp_{len(_SPANS)+1}",
        "duration_ms": duration_ms,
        "attributes": attributes or {},
        "instrumentation": "otel-compatible",
    }
    _SPANS.append(span)
    log_event("otel.span", **span)
    return span


def recent_spans() -> list[dict[str, Any]]:
    return list(_SPANS)


__all__ = ["emit_span", "recent_spans"]
