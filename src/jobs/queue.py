"""Background job queue (feature #46) — Postgres-backed table or in-process.

Hermetic: default in-memory + DuckDB ``job_queue`` table. Workers call
``run_next``; no arq/redis required for pilot.

Reliability (item 18):
- Atomic claim (``UPDATE ... WHERE status='pending'`` + explicit re-SELECT
  verification — DuckDB reports ``rowcount=None`` for UPDATEs, which a
  previous version misread as a lost race and leaked ``running`` jobs).
- Lease / visibility timeout: claims carry ``lease_owner`` + ``lease_expires``.
  ``run_next`` first reaps expired leases back to ``pending`` (crashed-worker
  recovery) so a dead worker never wedges the queue.
- Retry cap (``MAX_ATTEMPTS``) with terminal ``dead``/``failed`` states.
- Idempotent completion: finishing checks ownership + status; duplicate
  completions return the stored result instead of double-applying.
- ``Idempotency-Key`` style dedupe on enqueue: same key returns the existing
  job instead of inserting a duplicate.
"""

from __future__ import annotations

import json
import traceback
from datetime import timedelta
from typing import Any, Callable

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

_HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {}

# Known pilot job types (enqueue / run_next refuse free-form strings).
ALLOWED_JOB_TYPES = frozenset(
    {
        "audit_contact",
        "rebuild_clusters",
        "ingest_scale",
        "ingest_source",
        "recompute_anomalies",
        "scheduled_scan",
        "reenrich",
        "audit_export",
        "build_digest",
        "embedding_backfill",
        "rebuild_cluster_build",
        "erasure_drill",
    }
)

MAX_ATTEMPTS = 3
DEFAULT_LEASE_S = 300


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS job_queue (
            job_id VARCHAR PRIMARY KEY,
            job_type VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            payload_json VARCHAR,
            result_json VARCHAR,
            error VARCHAR,
            attempts INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT current_timestamp,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            lease_owner VARCHAR,
            lease_expires TIMESTAMP,
            idempotency_key VARCHAR
        )
        """
    )
    # Forward-compatible lease columns for pre-item-18 tables.
    for ddl in (
        "ALTER TABLE job_queue ADD COLUMN lease_owner VARCHAR",
        "ALTER TABLE job_queue ADD COLUMN lease_expires TIMESTAMP",
        "ALTER TABLE job_queue ADD COLUMN idempotency_key VARCHAR",
    ):
        try:
            con.execute(ddl)
        except Exception:
            pass


def register_handler(job_type: str, fn: Callable[[dict[str, Any]], Any]) -> None:
    _HANDLERS[job_type] = fn


def enqueue(
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    jt = (job_type or "").strip()
    if jt not in ALLOWED_JOB_TYPES and jt not in _HANDLERS:
        raise ValueError(
            f"job_type not allowlisted: {job_type!r}; allowed={sorted(ALLOWED_JOB_TYPES)}"
        )
    with ops_con() as con:
        _ensure(con)
        # Idempotent enqueue: same key returns the existing live job.
        if idempotency_key:
            try:
                row = con.execute(
                    """
                    SELECT job_id, job_type, status FROM job_queue
                    WHERE idempotency_key = ? AND status IN ('pending', 'running')
                    """,
                    [idempotency_key],
                ).fetchone()
            except Exception:
                row = None
            if row:
                return {"job_id": row[0], "job_type": row[1], "status": row[2],
                        "duplicate": True}
        jid = f"job_{new_ulid()}"
        con.execute(
            """
            INSERT INTO job_queue (job_id, job_type, status, payload_json, idempotency_key)
            VALUES (?, ?, 'pending', ?, ?)
            """,
            [jid, jt, json.dumps(payload or {}), idempotency_key],
        )
    return {"job_id": jid, "job_type": jt, "status": "pending"}


def _reap_expired_leases(con, *, now) -> int:
    """Return expired ``running`` leases to ``pending`` (crashed-worker recovery).

    Each reap counts as an attempt; jobs exhausting MAX_ATTEMPTS go ``dead``.
    Returns the number of jobs reaped.
    """
    try:
        stale = con.execute(
            """
            SELECT job_id, attempts FROM job_queue
            WHERE status = 'running' AND lease_expires IS NOT NULL AND lease_expires < ?
            """,
            [now],
        ).fetchall()
    except Exception:
        return 0
    n = 0
    for jid, attempts in stale:
        attempts = int(attempts or 0) + 1
        if attempts >= MAX_ATTEMPTS:
            con.execute(
                """
                UPDATE job_queue
                SET status = 'dead', finished_at = ?, lease_owner = NULL,
                    lease_expires = NULL,
                    error = ? WHERE job_id = ? AND status = 'running'
                """,
                [now, f"lease expired {attempts}x; worker presumed crashed", jid],
            )
        else:
            con.execute(
                """
                UPDATE job_queue
                SET status = 'pending', attempts = ?, lease_owner = NULL,
                    lease_expires = NULL, started_at = NULL,
                    error = ? WHERE job_id = ? AND status = 'running'
                """,
                [attempts, f"lease expired; requeued (attempt {attempts})", jid],
            )
        n += 1
    return n


def run_next(
    *,
    worker_id: str | None = None,
    lease_s: int = DEFAULT_LEASE_S,
) -> dict[str, Any] | None:
    """Claim and run one pending job (at-most-one-worker executes it).

    - Reaps expired leases first (visibility timeout).
    - Claims atomically; verifies the claim with an explicit re-SELECT
      (DuckDB UPDATE rowcount is unreliable — never infer races from it).
    - Completion is idempotent: only the lease owner transitions
      running -> done/failed/pending.
    """
    owner = worker_id or f"worker_{new_ulid()}"
    now = utc_now()
    lease_until = now + timedelta(seconds=max(1, int(lease_s)))
    with ops_con() as con:
        _ensure(con)
        _reap_expired_leases(con, now=now)
        row = con.execute(
            """
            SELECT job_id, job_type, payload_json, attempts
            FROM job_queue WHERE status = 'pending'
            ORDER BY created_at ASC LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        jid, jtype, payload_raw, attempts = row[0], row[1], row[2], int(row[3] or 0)
        if int(attempts or 0) >= MAX_ATTEMPTS:
            con.execute(
                "UPDATE job_queue SET status='dead', finished_at=?, error=? WHERE job_id=? AND status='pending'",
                [now, f"max attempts ({MAX_ATTEMPTS}) exceeded", jid],
            )
            return {"job_id": jid, "status": "dead", "error": "max attempts exceeded"}
        con.execute(
            """
            UPDATE job_queue
            SET status='running', started_at=?, attempts=?, lease_owner=?, lease_expires=?
            WHERE job_id=? AND status='pending'
            """,
            [now, attempts + 1, owner, lease_until, jid],
        )
        # Explicit verification — never trust rowcount (None/-1 on DuckDB).
        check = con.execute(
            "SELECT status, lease_owner FROM job_queue WHERE job_id = ?", [jid]
        ).fetchone()
        if not check or check[0] != "running" or check[1] != owner:
            return None  # lost the race; another worker claimed it
    payload = json.loads(payload_raw or "{}")
    fn = _HANDLERS.get(jtype)
    try:
        from src.observability.otel import start_span as _span

        with _span(f"job.{jtype}", attributes={"job_id": jid, "owner": owner}):
            if fn is None:
                # Built-in no-op handlers for known pilot jobs
                result = _default_handler(jtype, payload)
            else:
                result = fn(payload)
        return _finish(jid, owner, ok=True, result=result)
    except Exception as e:
        return _finish(jid, owner, ok=False, error=e)


def _finish(
    jid: str,
    owner: str,
    *,
    ok: bool,
    result: Any = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Idempotent completion: only the lease owner may transition the job.

    A duplicate completion (job already done/failed) returns the stored
    result instead of double-applying side effects.
    """
    now = utc_now()
    with ops_con() as con:
        _ensure(con)
        cur = con.execute(
            "SELECT status, attempts, result_json, error FROM job_queue WHERE job_id = ?",
            [jid],
        ).fetchone()
        if not cur:
            return {"job_id": jid, "status": "unknown", "error": "job vanished"}
        status, attempts, result_json, err = cur[0], int(cur[1] or 0), cur[2], cur[3]
        if status in ("done", "failed", "dead"):
            try:
                stored = json.loads(result_json or "{}")
            except (json.JSONDecodeError, TypeError):
                stored = {}
            return {"job_id": jid, "status": status, "result": stored,
                    "duplicate_completion": True}
        if status != "running":
            return {"job_id": jid, "status": status, "error": err or "not running"}
        if ok:
            con.execute(
                """
                UPDATE job_queue
                SET status='done', finished_at=?, result_json=?,
                    lease_owner=NULL, lease_expires=NULL
                WHERE job_id=? AND status='running' AND lease_owner=?
                """,
                [now, json.dumps(result if isinstance(result, dict) else {"result": result}), jid, owner],
            )
            return {"job_id": jid, "status": "done", "result": result}
        n = attempts
        if n >= MAX_ATTEMPTS:
            con.execute(
                """
                UPDATE job_queue SET status='failed', finished_at=?, error=?,
                    lease_owner=NULL, lease_expires=NULL
                WHERE job_id=? AND status='running' AND lease_owner=?
                """,
                [now, f"{error}\n{traceback.format_exc()[-500:]}", jid, owner],
            )
        else:
            con.execute(
                """
                UPDATE job_queue SET status='pending', finished_at=NULL, error=?,
                    lease_owner=NULL, lease_expires=NULL, started_at=NULL
                WHERE job_id=? AND status='running' AND lease_owner=?
                """,
                [f"retry {n}/{MAX_ATTEMPTS}: {error}", jid, owner],
            )
        return {"job_id": jid, "status": "failed", "error": str(error)}


def _default_handler(jtype: str, payload: dict[str, Any]) -> dict[str, Any]:
    if jtype == "audit_contact":
        return {"ok": True, "interaction_id": payload.get("interaction_id"), "deferred": True}
    if jtype == "rebuild_clusters":
        pack = payload.get("pack_id") or "automotive_nhtsa"
        try:
            from src.ml_runtime.clustering import rebuild_clusters

            return rebuild_clusters(pack)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if jtype == "ingest_scale":
        return {"ok": True, "queued": True, "pack_id": payload.get("pack_id")}
    if jtype == "ingest_source":
        pack = payload.get("pack_id") or "automotive_nhtsa"
        try:
            from src.domains.source_ingest import ingest_source

            return ingest_source(
                pack,
                payload.get("source") or "service",
                payload.get("csv_path") or "",
                mapping_path=payload.get("mapping_path"),
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if jtype == "scheduled_scan":
        pack = payload.get("pack_id") or "automotive_nhtsa"
        try:
            from src.frontline.fleet_scan import run_fleet_scan

            return run_fleet_scan(
                pack,
                rebuild_clusters=bool(payload.get("rebuild_clusters", False)),
                alert=bool(payload.get("alert", True)),
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if jtype == "reenrich":
        try:
            from src.frontline.reenrich import backfill_brief

            return backfill_brief(
                payload.get("interaction_id") or "",
                case_id=payload.get("case_id"),
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if jtype == "embedding_backfill":
        from src.ml_runtime.embedding_backfill import job_handler as _emb_bf

        return _emb_bf(payload)
    if jtype == "rebuild_cluster_build":
        from src.ml_runtime.cluster_builds import rebuild_cluster_build

        return rebuild_cluster_build(
            payload.get("pack_id") or "automotive_nhtsa",
            payload.get("embedding_version") or "",
            k=int(payload.get("k") or 5),
            dry_run=bool(payload.get("dry_run")),
        )
    if jtype == "recompute_anomalies":
        pack = payload.get("pack_id") or "automotive_nhtsa"
        try:
            from src.ml_runtime.anomalies import recompute_weekly_anomalies

            rows = recompute_weekly_anomalies(
                pack,
                category=payload.get("category"),
                entity_2=payload.get("entity_2"),
            )
            return {"ok": True, "pack_id": pack, "rows": len(rows)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if jtype == "audit_export":
        return {"ok": True, "deferred": True, "params": payload}
    if jtype == "build_digest":
        return {"ok": True, "deferred": True, "params": payload}
    if jtype == "erasure_drill":
        from src.compliance.erasure_drill import maybe_run_weekly_drill, run_erasure_drill

        if payload.get("weekly"):
            return maybe_run_weekly_drill() or {"ok": True, "skipped": True, "reason": "not_due"}
        return run_erasure_drill()
    # Unknown types must not echo arbitrary payloads (allowlist gate on enqueue).
    raise ValueError(f"no handler for job_type: {jtype!r}")


def list_jobs(*, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with ops_con(read_only=True) as con:
        try:
            _ensure(con)
            sql = "SELECT job_id, job_type, status, attempts, created_at, finished_at FROM job_queue"
            params: list[Any] = []
            if status:
                sql += " WHERE status = ?"
                params.append(status)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = con.execute(sql, params).fetchall()
        except Exception:
            return []
    cols = ["job_id", "job_type", "status", "attempts", "created_at", "finished_at"]
    return [dict(zip(cols, r)) for r in rows]
