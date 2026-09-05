"""OpenTelemetry integration (item 47).

Real SDK when installed (``pip install opentelemetry-sdk
opentelemetry-exporter-otlp`` + ``OTEL_EXPORTER_OTLP_ENDPOINT``); otherwise a
structured in-house span sink with the same API, honestly labeled
``in-house``. Either way:

- every span carries trace_id/span_id/request correlation IDs;
- instrumentation failures NEVER crash business logic (all SDK calls are
  guarded — observability is best-effort by design);
- :func:`recent_spans` exposes the in-house sink for tests and the pilot
  console.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from src.observability.metrics import bind, log_event

_SPANS: list[dict[str, Any]] = []
_SDK_TRACER = None
_SDK_AVAILABLE = False

try:  # Real SDK when the deployment installs it — never a hard dependency.
    from opentelemetry import trace as _ot_trace  # type: ignore

    _SDK_AVAILABLE = True
except Exception:
    _ot_trace = None  # type: ignore


def sdk_available() -> bool:
    return _SDK_AVAILABLE


def backend() -> str:
    if _SDK_AVAILABLE and _get_tracer() is not None:
        return "opentelemetry-sdk"
    return "in-house"


def _get_tracer():
    global _SDK_TRACER
    if not _SDK_AVAILABLE:
        return None
    if _SDK_TRACER is None:
        try:
            _SDK_TRACER = _ot_trace.get_tracer("skewai.frontline")
        except Exception:
            return None
    return _SDK_TRACER


def new_request_id() -> str:
    """Generate a correlation/request ID (``req_`` + short uuid)."""
    return "req_" + uuid.uuid4().hex[:12]


def bind_request(request_id: str, *, pack_id: str | None = None) -> None:
    """Bind correlation fields for subsequent log events in this context."""
    try:
        bind(request_id=request_id, pack_id=pack_id or "")
    except Exception:
        pass


def emit_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    duration_ms: float = 1.0,
) -> dict[str, Any]:
    """Record one span (in-house sink; SDK spans flow via start_span)."""
    span = {
        "name": name,
        "trace_id": f"tr_{uuid.uuid4().hex[:16]}",
        "span_id": f"sp_{uuid.uuid4().hex[:8]}",
        "duration_ms": duration_ms,
        "attributes": attributes or {},
        "instrumentation": backend(),
    }
    _SPANS.append(span)
    try:
        log_event("otel.span", **span)
    except Exception:
        pass
    return span


@contextmanager
def start_span(
    name: str, *, attributes: dict[str, Any] | None = None
) -> Iterator[dict[str, Any]]:
    """Timed span context manager (API requests, jobs, agent turns).

    Uses the real SDK span when available, always records to the in-house
    sink for the pilot console. Never raises.
    """
    start = time.perf_counter()
    sdk_span = None
    tracer = _get_tracer()
    if tracer is not None:
        try:
            sdk_span = tracer.start_span(name, attributes=attributes)
        except Exception:
            sdk_span = None
    try:
        yield {"name": name, "attributes": attributes or {}}
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        if sdk_span is not None:
            try:
                sdk_span.end()
            except Exception:
                pass
        try:
            emit_span(name, attributes=attributes, duration_ms=duration_ms)
        except Exception:
            pass


def recent_spans(limit: int = 200) -> list[dict[str, Any]]:
    return list(_SPANS[-limit:])


def clear_spans() -> None:
    del _SPANS[:]


__all__ = [
    "emit_span",
    "recent_spans",
    "clear_spans",
    "start_span",
    "new_request_id",
    "bind_request",
    "sdk_available",
    "backend",
]
