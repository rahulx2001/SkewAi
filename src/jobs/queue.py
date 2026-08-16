"""Background job queue (feature #46) — Postgres-backed table or in-process.

Hermetic: default in-memory + DuckDB ``job_queue`` table. Workers call
``run_next``; no arq/redis required for pilot.
"""

from __future__ import annotations

import json
import traceback
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
    }
)


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
            finished_at TIMESTAMP
        )
        """
    )


def register_handler(job_type: str, fn: Callable[[dict[str, Any]], Any]) -> None:
    _HANDLERS[job_type] = fn


def enqueue(job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    jt = (job_type or "").strip()
    if jt not in ALLOWED_JOB_TYPES and jt not in _HANDLERS:
        raise ValueError(
            f"job_type not allowlisted: {job_type!r}; allowed={sorted(ALLOWED_JOB_TYPES)}"
        )
    jid = f"job_{new_ulid()}"
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO job_queue (job_id, job_type, status, payload_json)
            VALUES (?, ?, 'pending', ?)
            """,
            [jid, jt, json.dumps(payload or {})],
        )
    return {"job_id": jid, "job_type": jt, "status": "pending"}


def run_next() -> dict[str, Any] | None:
    with ops_con() as con:
        _ensure(con)
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
        con.execute(
            "UPDATE job_queue SET status='running', started_at=?, attempts=? WHERE job_id=?",
            [utc_now(), attempts + 1, jid],
        )
    payload = json.loads(payload_raw or "{}")
    fn = _HANDLERS.get(jtype)
    try:
        if fn is None:
            # Built-in no-op handlers for known pilot jobs
            result = _default_handler(jtype, payload)
        else:
            result = fn(payload)
        with ops_con() as con:
            con.execute(
                """
                UPDATE job_queue SET status='done', finished_at=?, result_json=?
                WHERE job_id=?
                """,
                [utc_now(), json.dumps(result if isinstance(result, dict) else {"result": result}), jid],
            )
        return {"job_id": jid, "status": "done", "result": result}
    except Exception as e:
        with ops_con() as con:
            con.execute(
                """
                UPDATE job_queue SET status='failed', finished_at=?, error=?
                WHERE job_id=?
                """,
                [utc_now(), f"{e}\n{traceback.format_exc()[-500:]}", jid],
            )
        return {"job_id": jid, "status": "failed", "error": str(e)}


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
