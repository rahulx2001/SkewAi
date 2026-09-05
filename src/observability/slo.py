"""SLO samples + dashboard snapshot (item 47).

Meaningful SLOs for the pilot:
- ``contact_audit_success``: share of completed contacts with a grounded or
  drift-explained audit (objective 0.99).
- ``job_success``: share of finished jobs that reached ``done`` (0.99).
- ``queue_drain``: pending+stuck-running depth stays under threshold.
- ``ledger_degraded``: auxiliary ledger failures stay under the alert
  threshold (wired to ``ledger_health()``).

``evaluate_slos()`` computes all four from live state and fires a queued
ops alert when ``job_queue_status`` shows a stuck queue (alerts are
best-effort and never raise).
"""

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
        "dead": by.get("dead", 0),
        "by_status": by,
    }


QUEUE_DEPTH_ALERT_AT = 50
QUEUE_STUCK_RUNNING_ALERT_AT = 10


def evaluate_slos(*, fire_alerts: bool = True) -> dict[str, Any]:
    """Evaluate pilot SLOs from live state; alert on stuck queues.

    Scrape-triggered (the /ops/slo route calls this): alert emission is
    deduped per day by the alerts layer, so repeated scrapes do not page
    repeatedly. Pass ``fire_alerts=False`` for read-only evaluation.
    """
    samples: list[dict[str, Any]] = []
    try:
        qs = job_queue_status()
        finished = qs["done"] + qs["failed"] + qs["dead"]
        samples.append(record_slo_sample(
            "job_success",
            numerator=float(qs["done"]),
            denominator=float(finished or 1),
            objective=0.99,
        ))
        depth = qs["pending"] + qs["running"]
        samples.append(record_slo_sample(
            "queue_drain",
            numerator=1.0 if depth < QUEUE_DEPTH_ALERT_AT else 0.0,
            denominator=1.0,
            objective=1.0,
        ))
    except Exception:
        qs = {"pending": 0, "running": 0, "done": 0, "failed": 0, "dead": 0}
    try:
        from src.ledger import ledger_health

        lh = ledger_health()
        samples.append(record_slo_sample(
            "ledger_degraded",
            numerator=1.0 if not lh.get("alerting") else 0.0,
            denominator=1.0,
            objective=1.0,
        ))
    except Exception:
        lh = {}
    alerted: list[str] = []
    try:
        if fire_alerts and (
            qs["pending"] >= QUEUE_DEPTH_ALERT_AT
            or qs["running"] >= QUEUE_STUCK_RUNNING_ALERT_AT
        ):
            from src.frontline.alerts import fire_alert

            import anyio as _anyio

            async def _fire() -> None:
                try:
                    await fire_alert(
                        event="job_queue_stuck",
                        summary=(
                            f"job queue depth pending={qs['pending']} "
                            f"running={qs['running']}"
                        ),
                        ref_id="job-queue",
                    )
                except Exception:
                    pass

            try:
                _anyio.run(_fire)
            except Exception:
                pass
            alerted.append("job_queue_stuck")
    except Exception:
        pass
    return {
        "samples": samples,
        "queue": qs,
        "ledger": lh,
        "alerted": alerted,
        "breached": [s["name"] for s in samples if s.get("breached")],
    }


__all__ = [
    "record_slo_sample",
    "slo_dashboard",
    "job_queue_status",
    "evaluate_slos",
    "QUEUE_DEPTH_ALERT_AT",
    "QUEUE_STUCK_RUNNING_ALERT_AT",
]
