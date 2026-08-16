"""Multi-worker registry. Shared DuckDB always; Redis/Postgres only if they ping."""

from __future__ import annotations

import json
import os
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

_REDIS_PREFIX = "skew:worker:"


def _redis_client():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis

        r = redis.Redis.from_url(url, socket_connect_timeout=0.15, socket_timeout=0.15)
        r.ping()
        return r
    except Exception:
        return None


def _postgres_conn():
    dsn = (os.getenv("FRONTLINE_OPS_DSN") or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or "").strip()
    if not dsn.startswith("postgres"):
        return None
    try:
        import psycopg

        conn = psycopg.connect(dsn, connect_timeout=1)
        return conn
    except Exception:
        return None


def backend_name() -> str:
    if _redis_client() is not None:
        return "redis"
    if _postgres_conn() is not None:
        return "postgres"
    return "duckdb"


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_registry (
            worker_id VARCHAR PRIMARY KEY,
            host VARCHAR,
            heartbeat_at TIMESTAMP NOT NULL,
            status VARCHAR NOT NULL
        )
        """
    )


def _write_duckdb(wid: str, host: str) -> None:
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO worker_registry (worker_id, host, heartbeat_at, status)
            VALUES (?, ?, ?, 'up')
            """,
            [wid, host, utc_now()],
        )


def register_worker(host: str = "local") -> dict[str, Any]:
    wid = "w_" + new_ulid()
    backend = backend_name()
    rec = {"worker_id": wid, "host": host, "status": "up", "backend": backend}
    # Always persist to the shared ops warehouse so workers on the same DB see each other.
    _write_duckdb(wid, host)
    if backend == "redis":
        r = _redis_client()
        if r is not None:
            r.setex(_REDIS_PREFIX + wid, 3600, json.dumps(rec))
    if backend == "postgres":
        conn = _postgres_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS worker_registry (
                            worker_id TEXT PRIMARY KEY,
                            host TEXT,
                            heartbeat_at TIMESTAMP NOT NULL,
                            status TEXT NOT NULL
                        )
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO worker_registry (worker_id, host, heartbeat_at, status)
                        VALUES (%s, %s, NOW(), 'up')
                        ON CONFLICT (worker_id) DO UPDATE SET heartbeat_at = NOW(), status = 'up'
                        """,
                        [wid, host],
                    )
                conn.commit()
            finally:
                conn.close()
    return rec


def list_workers() -> list[dict[str, Any]]:
    backend = backend_name()
    found: dict[str, dict[str, Any]] = {}
    if backend == "redis":
        r = _redis_client()
        if r is not None:
            for key in r.scan_iter(_REDIS_PREFIX + "*"):
                raw = r.get(key)
                if not raw:
                    continue
                rec = json.loads(raw)
                found[rec["worker_id"]] = rec
    if backend == "postgres":
        conn = _postgres_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT worker_id, host, status FROM worker_registry")
                    for a, b, c in cur.fetchall():
                        found[str(a)] = {
                            "worker_id": str(a),
                            "host": b,
                            "status": c,
                            "backend": backend,
                        }
            finally:
                conn.close()
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                "SELECT worker_id, host, status FROM worker_registry"
            ).fetchall()
        except Exception:
            rows = []
    for a, b, c in rows:
        found.setdefault(
            str(a),
            {"worker_id": str(a), "host": b, "status": c, "backend": backend},
        )
    return list(found.values())


def heartbeat(worker_id: str) -> dict[str, Any]:
    backend = backend_name()
    with ops_con() as con:
        _ensure(con)
        con.execute(
            "UPDATE worker_registry SET heartbeat_at = ?, status = 'up' WHERE worker_id = ?",
            [utc_now(), worker_id],
        )
    if backend == "redis":
        r = _redis_client()
        if r is not None:
            raw = r.get(_REDIS_PREFIX + worker_id)
            rec = json.loads(raw) if raw else {"worker_id": worker_id, "status": "up"}
            rec["status"] = "up"
            rec["backend"] = backend
            r.setex(_REDIS_PREFIX + worker_id, 3600, json.dumps(rec))
    return {"worker_id": worker_id, "status": "up", "backend": backend}


def worker_count() -> int:
    return len(list_workers())


__all__ = [
    "backend_name",
    "register_worker",
    "list_workers",
    "heartbeat",
    "worker_count",
]
