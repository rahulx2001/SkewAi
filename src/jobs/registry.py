"""Multi-worker registry. Shared DuckDB always; Redis/Postgres only if they ping."""

from __future__ import annotations

import json
import os
from typing import Any

from datetime import timedelta

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

_REDIS_PREFIX = "skew:worker:"
WORKER_TTL_S = 90


def is_live_heartbeat(heartbeat_at, *, now=None, ttl_s: int = WORKER_TTL_S) -> bool:
    """True when heartbeat_at is within ttl_s of now. Pure."""
    if heartbeat_at is None:
        return False
    current = now or utc_now()
    try:
        hb = heartbeat_at.replace(tzinfo=None)
        cur = current.replace(tzinfo=None)
    except Exception:
        return False
    age = (cur - hb).total_seconds()
    return 0 <= age <= max(1, int(ttl_s))


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
    prune_stale_workers()
    if host == "api":
        # One live API process: prior uvicorn on this DB is gone.
        cutoff = utc_now() - timedelta(seconds=WORKER_TTL_S + 1)
        with ops_con() as con:
            _ensure(con)
            con.execute(
                """
                UPDATE worker_registry
                SET status = 'stale', heartbeat_at = ?
                WHERE host = 'api' AND status = 'up'
                """,
                [cutoff],
            )
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
    now = utc_now()
    with ops_con(read_only=True) as con:
        try:
            rows = con.execute(
                "SELECT worker_id, host, status, heartbeat_at FROM worker_registry"
            ).fetchall()
        except Exception:
            rows = []
    for a, b, c, hb in rows:
        if not is_live_heartbeat(hb, now=now):
            continue
        found.setdefault(
            str(a),
            {"worker_id": str(a), "host": b, "status": c, "backend": backend},
        )
    return list(found.values())


def prune_stale_workers(*, ttl_s: int = WORKER_TTL_S) -> int:
    """Mark stale DuckDB workers down so restarts do not inflate the count."""
    cutoff = utc_now() - timedelta(seconds=max(1, int(ttl_s)))
    with ops_con() as con:
        _ensure(con)
        con.execute(
            "UPDATE worker_registry SET status = 'stale' WHERE heartbeat_at < ? AND status = 'up'",
            [cutoff],
        )
        n = con.execute(
            "SELECT COUNT(*) FROM worker_registry WHERE heartbeat_at < ?",
            [cutoff],
        ).fetchone()
    return int(n[0] if n else 0)


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


# ── Distributed close claims (item 31) ──────────────────────────────────────
# Two workers (processes, replicas) must never close the same interaction
# twice and open duplicate cases. The in-process registry + asyncio.Lock
# cover one process; THIS covers the fleet:
#   - Redis (when REDIS_URL is set): SET NX EX — atomic, auto-expiring.
#   - Fallback: shared ops-DB table with PK dedupe (INSERT-or-takeover),
#     the "database ON CONFLICT dedupe" for single-box multi-worker deploys.
# Claims are terminal records (never deleted): a second claimant learns the
# close is already owned and stands down — idempotent across processes.

_CLOSE_PREFIX = "skew:close:"
CLOSE_CLAIM_TTL_S = 600


def _ensure_close_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS interaction_close_claims (
            interaction_id VARCHAR PRIMARY KEY,
            owner VARCHAR NOT NULL,
            claimed_at TIMESTAMP NOT NULL
        )
        """
    )


def acquire_close_claim(
    interaction_id: str,
    owner: str,
    *,
    ttl_s: int = CLOSE_CLAIM_TTL_S,
) -> bool:
    """Atomically claim the close for *interaction_id*. True when owned."""
    return acquire_close_claim_info(
        interaction_id, owner, ttl_s=ttl_s
    )["acquired"]


def acquire_close_claim_info(
    interaction_id: str,
    owner: str,
    *,
    ttl_s: int = CLOSE_CLAIM_TTL_S,
) -> dict[str, Any]:
    """Like acquire_close_claim, plus takeover detail (audit 5.1).

    Returns {"acquired": bool, "takeover": bool}: takeover=True means this
    worker took over an EXPIRED claim from a (presumed dead) worker — the
    caller must check for an already-inserted case before allocating.
    """
    iid = (interaction_id or "").strip()
    own = (owner or "").strip() or "unknown"
    if not iid:
        return {"acquired": False, "takeover": False}
    r = _redis_client()
    if r is not None:
        try:
            got = bool(r.set(_CLOSE_PREFIX + iid, own, nx=True, ex=max(1, int(ttl_s))))
            return {"acquired": got, "takeover": False}
        except Exception:
            pass
    now = utc_now()
    cutoff = now - timedelta(seconds=max(1, int(ttl_s)))
    with ops_con() as con:
        _ensure_close_table(con)
        try:
            con.execute(
                """
                INSERT INTO interaction_close_claims
                (interaction_id, owner, claimed_at) VALUES (?, ?, ?)
                """,
                [iid, own, now],
            )
            return {"acquired": True, "takeover": False}
        except Exception:
            pass
        # PK conflict: owned already — unless stale, then take over.
        try:
            row = con.execute(
                "SELECT owner, claimed_at FROM interaction_close_claims WHERE interaction_id = ?",
                [iid],
            ).fetchone()
        except Exception:
            return {"acquired": False, "takeover": False}
        if not row:
            return {"acquired": False, "takeover": False}
        if row[0] == own:
            return {"acquired": True, "takeover": False}
        try:
            claimed_at = row[1].replace(tzinfo=None) if hasattr(row[1], "replace") else None
        except Exception:
            claimed_at = None
        if claimed_at is not None and claimed_at < cutoff.replace(tzinfo=None):
            try:
                con.execute(
                    """
                    UPDATE interaction_close_claims
                    SET owner = ?, claimed_at = ?
                    WHERE interaction_id = ? AND claimed_at = ?
                    """,
                    [own, now, iid, row[1]],
                )
                check = con.execute(
                    "SELECT owner FROM interaction_close_claims WHERE interaction_id = ?",
                    [iid],
                ).fetchone()
                took = bool(check and check[0] == own)
                return {"acquired": took, "takeover": took}
            except Exception:
                return {"acquired": False, "takeover": False}
        return {"acquired": False, "takeover": False}


def close_claim_owner(interaction_id: str) -> str | None:
    """Current close-claim owner, if any (Redis first, then DB)."""
    iid = (interaction_id or "").strip()
    if not iid:
        return None
    r = _redis_client()
    if r is not None:
        try:
            raw = r.get(_CLOSE_PREFIX + iid)
            if raw:
                return raw.decode() if isinstance(raw, bytes) else str(raw)
        except Exception:
            pass
    with ops_con(read_only=True) as con:
        try:
            _ensure_close_table(con)
            row = con.execute(
                "SELECT owner FROM interaction_close_claims WHERE interaction_id = ?",
                [iid],
            ).fetchone()
        except Exception:
            return None
    return str(row[0]) if row else None


def heartbeat_close_claim(interaction_id: str, owner: str) -> bool:
    """Refresh a close claim while the close body runs (audit 5.1).

    A worker that is alive but slow keeps ownership; only a truly dead
    worker's claim expires and becomes re-acquirable. Returns False when
    the claim is gone or owned by someone else.
    """
    iid = (interaction_id or "").strip()
    own = (owner or "").strip()
    if not iid or not own:
        return False
    r = _redis_client()
    if r is not None:
        try:
            cur = r.get(_CLOSE_PREFIX + iid)
            cur = cur.decode() if isinstance(cur, bytes) else cur
            if cur == own:
                r.expire(_CLOSE_PREFIX + iid, CLOSE_CLAIM_TTL_S)
                return True
            return False
        except Exception:
            pass
    with ops_con() as con:
        _ensure_close_table(con)
        try:
            con.execute(
                "UPDATE interaction_close_claims SET claimed_at = ?"
                " WHERE interaction_id = ? AND owner = ?",
                [utc_now(), iid, own],
            )
            row = con.execute(
                "SELECT owner FROM interaction_close_claims WHERE interaction_id = ?",
                [iid],
            ).fetchone()
            return bool(row and row[0] == own)
        except Exception:
            return False


_SLICE_PREFIX = "skew:slice:"
SLICE_CLAIM_TTL_S = 300


def _ensure_slice_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS slice_claims (
            slice_key VARCHAR PRIMARY KEY,
            owner VARCHAR NOT NULL,
            claimed_at TIMESTAMP NOT NULL
        )
        """
    )


def acquire_slice_claim(
    slice_key: str,
    owner: str,
    *,
    ttl_s: int = SLICE_CLAIM_TTL_S,
) -> bool:
    """Claim the right to open an investigation for a slice (audit 4.5).

    Live intercept, CaseAgent link-or-open, and the fleet scan all funnel
    through ``open_or_link_investigation``, which claims
    ``inv:{pack}:{cluster}`` first: exactly one opener fleet-wide inserts;
    losers link to the existing row. Same Redis-NX / DB-PK-expiry mechanics
    as close claims.
    """
    key = (slice_key or "").strip()
    own = (owner or "").strip() or "unknown"
    if not key:
        return False
    r = _redis_client()
    if r is not None:
        try:
            return bool(r.set(_SLICE_PREFIX + key, own, nx=True, ex=max(1, int(ttl_s))))
        except Exception:
            pass
    now = utc_now()
    cutoff = now - timedelta(seconds=max(1, int(ttl_s)))
    with ops_con() as con:
        _ensure_slice_table(con)
        # Slice claims are transient (unlike terminal close claims): prune
        # long-expired rows so the table stays small.
        try:
            con.execute(
                "DELETE FROM slice_claims WHERE claimed_at < ?",
                [now - timedelta(seconds=max(1, int(ttl_s)) * 4)],
            )
        except Exception:
            pass
        try:
            con.execute(
                "INSERT INTO slice_claims (slice_key, owner, claimed_at)"
                " VALUES (?, ?, ?)",
                [key, own, now],
            )
            return True
        except Exception:
            pass
        try:
            row = con.execute(
                "SELECT owner, claimed_at FROM slice_claims WHERE slice_key = ?",
                [key],
            ).fetchone()
        except Exception:
            return False
        if not row:
            return False
        if row[0] == own:
            return True
        try:
            claimed_at = row[1].replace(tzinfo=None) if hasattr(row[1], "replace") else None
        except Exception:
            claimed_at = None
        if claimed_at is not None and claimed_at < cutoff.replace(tzinfo=None):
            try:
                con.execute(
                    "UPDATE slice_claims SET owner = ?, claimed_at = ?"
                    " WHERE slice_key = ? AND claimed_at = ?",
                    [own, now, key, row[1]],
                )
                check = con.execute(
                    "SELECT owner FROM slice_claims WHERE slice_key = ?",
                    [key],
                ).fetchone()
                return bool(check and check[0] == own)
            except Exception:
                return False
        return False


__all__ = [
    "backend_name",
    "register_worker",
    "list_workers",
    "heartbeat",
    "worker_count",
    "is_live_heartbeat",
    "prune_stale_workers",
    "acquire_close_claim",
    "acquire_close_claim_info",
    "close_claim_owner",
    "heartbeat_close_claim",
    "acquire_slice_claim",
    "WORKER_TTL_S",
    "CLOSE_CLAIM_TTL_S",
    "SLICE_CLAIM_TTL_S",
]
