"""Observability hooks (feature #47) — structlog-shaped JSON + Prometheus text.

No hard dependency on prometheus_client/sentry; emits scrapeable metrics text
and bindable log events with interaction_id / pack_id.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_counters: dict[str, float] = defaultdict(float)
_histograms: dict[str, list[float]] = defaultdict(list)
_bound: dict[str, str] = {}


def bind(**kwargs: str) -> None:
    """Bind correlation fields for subsequent log events (thread-local-ish global for pilot)."""
    with _lock:
        _bound.update({k: str(v) for k, v in kwargs.items() if v is not None})


def clear_bind() -> None:
    with _lock:
        _bound.clear()


def log_event(event: str, **fields: Any) -> dict[str, Any]:
    rec = {
        "ts": time.time(),
        "event": event,
        **_bound,
        **{k: v for k, v in fields.items() if v is not None},
    }
    # stdout-friendly single line JSON (structlog style)
    print(json.dumps(rec, default=str), flush=True)
    return rec


def inc(name: str, value: float = 1.0, **labels: str) -> None:
    key = name if not labels else f"{name}|" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    with _lock:
        _counters[key] += value


def observe(name: str, value: float, **labels: str) -> None:
    key = name if not labels else f"{name}|" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    with _lock:
        _histograms[key].append(float(value))


def prometheus_text() -> str:
    lines = ["# HELP frontline_info Skew AI pilot metrics", "# TYPE frontline_info gauge", "frontline_info 1"]
    with _lock:
        for k, v in sorted(_counters.items()):
            metric = k.replace("|", "{") 
            if "{" in metric and not metric.endswith("}"):
                # name{labels}
                name, rest = k.split("|", 1)
                labs = ",".join(rest.split(","))
                lines.append(f"{name}{{{labs}}} {v}")
            else:
                lines.append(f"{k} {v}")
        for k, vals in sorted(_histograms.items()):
            if not vals:
                continue
            name = k.split("|", 1)[0]
            avg = sum(vals) / len(vals)
            lines.append(f"{name}_count {len(vals)}")
            lines.append(f"{name}_sum {sum(vals)}")
            lines.append(f"{name}_avg {avg}")
    return "\n".join(lines) + "\n"


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "counters": dict(_counters),
            "histograms": {k: {"n": len(v), "avg": (sum(v) / len(v) if v else 0)} for k, v in _histograms.items()},
            "bound": dict(_bound),
        }
