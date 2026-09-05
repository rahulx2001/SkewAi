"""Idempotency-Key support for state-changing endpoints (item 45).

Clients send ``Idempotency-Key: <unique-per-operation>`` on POST
/simulate, POST /ingest, and POST /cases/{id}/notes. The first request
executes and its (endpoint, key, request-hash, response) tuple is stored;
a retry with the same key returns the STORED response without re-executing
side effects. A reused key with a DIFFERENT request hash is rejected (422)
so key collisions across distinct operations fail loudly.

- TTL: 24h default (``IDEMPOTENCY_TTL_S``); expired rows are swept on write.
- Cross-worker safe: PK on (endpoint, key); concurrent first-requests race
  on INSERT and exactly one wins — the loser reads the winner's row (or, if
  the winner has not finished, gets 409 to retry).
- In-flight marker: rows start as ``status='processing'`` so a concurrent
  duplicate observes processing instead of double-executing.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con

DEFAULT_TTL_S = 24 * 3600


def _ttl_s() -> int:
    import os

    try:
        return max(60, int(os.getenv("IDEMPOTENCY_TTL_S") or str(DEFAULT_TTL_S)))
    except ValueError:
        return DEFAULT_TTL_S


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            endpoint VARCHAR NOT NULL,
            idem_key VARCHAR NOT NULL,
            request_hash VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            response_json TEXT,
            status_code INTEGER NOT NULL DEFAULT 200,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            PRIMARY KEY (endpoint, idem_key)
        )
        """
    )


def _sweep(con, *, now) -> None:
    try:
        con.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", [now])
    except Exception:
        pass


def request_fingerprint(material: str) -> str:
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def check_idempotency(
    request: Any, endpoint: str, material: str
) -> dict[str, Any] | JSONResponse | None:
    """Pre-execution gate. Returns:

    - ``None`` → no key supplied (or key claimed for THIS request): execute.
    - ``dict`` → completed stored response: return it (no side effects).
    - raises 409 → another worker is processing this key: retry shortly.
    - raises 422 → key reused with a different request body.
    """
    key = ""
    try:
        key = (request.headers.get("idempotency-key") or "").strip()
    except Exception:
        key = ""
    if not key or len(key) > 256:
        if len(key) > 256:
            raise HTTPException(status_code=422, detail="Idempotency-Key too long")
        return None
    fingerprint = request_fingerprint(f"{endpoint}\n{material}")
    now = utc_now()
    expires = now + timedelta(seconds=_ttl_s())
    with ops_con() as con:
        _ensure(con)
        _sweep(con, now=now)
        try:
            row = con.execute(
                "SELECT request_hash, status, response_json, status_code FROM idempotency_keys WHERE endpoint = ? AND idem_key = ?",
                [endpoint, key],
            ).fetchone()
        except Exception:
            return None
        if row:
            if row[0] != fingerprint:
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key already used with a different request",
                )
            if row[1] == "completed":
                try:
                    return json.loads(row[2] or "{}")
                except (json.JSONDecodeError, TypeError):
                    return {}
            # Processing by a concurrent worker — do not double-execute.
            raise HTTPException(
                status_code=409,
                detail="duplicate request in progress; retry shortly",
            )
        try:
            con.execute(
                """
                INSERT INTO idempotency_keys
                (endpoint, idem_key, request_hash, status, created_at, expires_at)
                VALUES (?, ?, ?, 'processing', ?, ?)
                """,
                [endpoint, key, fingerprint, now, expires],
            )
        except Exception:
            # Lost the insert race: re-read the winner's row.
            try:
                row = con.execute(
                    "SELECT request_hash, status, response_json, status_code FROM idempotency_keys WHERE endpoint = ? AND idem_key = ?",
                    [endpoint, key],
                ).fetchone()
            except Exception:
                row = None
            if row and row[0] == fingerprint and row[1] == "completed":
                try:
                    return json.loads(row[2] or "{}")
                except (json.JSONDecodeError, TypeError):
                    return {}
            raise HTTPException(
                status_code=409,
                detail="duplicate request in progress; retry shortly",
            )
    # Attach claim context for store_idempotent_result.
    try:
        request.state.idem_claim = (endpoint, key)
    except Exception:
        pass
    return None


def store_idempotent_result(
    request: Any,
    endpoint: str,
    result: dict[str, Any],
    *,
    status_code: int = 200,
) -> None:
    """Persist the response for a claimed key (post-execution). Best-effort."""
    key = ""
    try:
        key = (request.headers.get("idempotency-key") or "").strip()
    except Exception:
        return
    if not key:
        return
    now = utc_now()
    with ops_con() as con:
        try:
            _ensure(con)
            con.execute(
                """
                UPDATE idempotency_keys
                SET status = 'completed', response_json = ?, status_code = ?
                WHERE endpoint = ? AND idem_key = ?
                """,
                [json.dumps(result, default=str), int(status_code), endpoint, key],
            )
        except Exception:
            pass


__all__ = [
    "check_idempotency",
    "store_idempotent_result",
    "request_fingerprint",
    "DEFAULT_TTL_S",
]
