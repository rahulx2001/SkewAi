"""SLO samples + dashboard snapshot."""

from __future__ import annotations

from typing import Any

from src.jobs.queue import _ensure as _ensure_jobs
from src.data.warehouse import ops_con
from src.observability.metrics import observe, snapshot

_SAMPLES: list[dict[str, Any]] = []


def record_slo_sample(
    name: str,
    *,
    numerator: float,
    denominator: float,
    objective: float = 0.99,
) -> dict[str, Any]:
    ratio = (numerator / denominator) if denominator else 1.0
    sample = {
        "name": name,
        "ratio": ratio,
        "objective": objective,
        "breached": ratio < objective,
        "numerator": numerator,
        "denominator": denominator,
    }
    _SAMPLES.append(sample)
    observe(f"slo_{name}", ratio)
    return sample


def slo_dashboard() -> dict[str, Any]:
    return {"samples": list(_SAMPLES), "metrics": snapshot()}


def job_queue_status() -> dict[str, Any]:
    with ops_con(read_only=True) as con:
        try:
            _ensure_jobs(con)
            rows = con.execute(
                "SELECT status, COUNT(*) FROM job_queue GROUP BY status"
            ).fetchall()
        except Exception:
            rows = []
    by = {str(s): int(n) for s, n in rows}
    return {
        "pending": by.get("pending", 0),
        "running": by.get("running", 0),
        "done": by.get("done", 0) + by.get("completed", 0),
        "failed": by.get("failed", 0),
        "by_status": by,
    }


__all__ = ["record_slo_sample", "slo_dashboard", "job_queue_status"]
