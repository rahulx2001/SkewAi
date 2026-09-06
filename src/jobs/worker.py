"""Standalone job worker — same loop the API lifespan runs in-process.

    python -m src.jobs.worker

Compose starts this as `frontline-worker` / `frontline-hardened-worker` so
enqueued jobs and the weekly erasure drill run even if the API process is
replaced. The in-process lifespan worker remains for single-container deploys;
lease claiming makes two workers safe.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 5.0
FAIRNESS_EVERY_S = 60.0


def worker_tick(*, run_fairness: bool = False) -> dict[str, Any]:
    """One pass: claim a job, maybe run the weekly drill, optionally fairness."""
    out: dict[str, Any] = {"job": None, "drill": None, "fairness": None}
    try:
        from src.jobs.queue import run_next

        out["job"] = run_next()
    except Exception:
        logger.exception("job_worker_run_next_failed")
    try:
        from src.compliance.erasure_drill import maybe_run_weekly_drill

        out["drill"] = maybe_run_weekly_drill()
    except Exception:
        logger.exception("job_worker_erasure_drill_failed")
    if run_fairness:
        try:
            from src.frontline.analytics import evaluate_fairness_circuit_breaker

            out["fairness"] = evaluate_fairness_circuit_breaker()
        except Exception:
            logger.exception("job_worker_fairness_failed")
    return out


def run_forever(*, interval_s: float | None = None) -> None:
    raw = os.getenv("FRONTLINE_WORKER_INTERVAL_S", "").strip()
    delay = float(interval_s) if interval_s is not None else (
        float(raw) if raw else DEFAULT_INTERVAL_S
    )
    delay = max(1.0, delay)
    last_fairness = 0.0
    while True:
        now = time.monotonic()
        due = (now - last_fairness) >= FAIRNESS_EVERY_S
        worker_tick(run_fairness=due)
        if due:
            last_fairness = now
        time.sleep(delay)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("frontline_job_worker_start")
    run_forever()


if __name__ == "__main__":
    main()
