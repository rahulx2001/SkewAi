"""Public scoped API keys (not the global FRONTLINE_API_KEY)."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid

SCOPES = frozenset(
    {
        "kpi:read",
        "queue:read",
        "ingest:write",
        "billing:read",
        "nl:query",
        "webhook:manage",
    }
)


def _ensure(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS scoped_api_keys (
            key_id VARCHAR PRIMARY KEY,
            token_hash VARCHAR NOT NULL,
            prefix VARCHAR NOT NULL,
            scopes VARCHAR NOT NULL,
            tenant_id VARCHAR NOT NULL,
            revoked BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL
        )
        """
    )


def _hash(token: str) -> str:
    salt = (os.getenv("SCOPED_KEY_SALT") or "skew-scoped-v1").encode("utf-8")
    return hmac.new(salt, token.encode("utf-8"), hashlib.sha256).hexdigest()


def create_scoped_key(
    scopes: list[str],
    *,
    tenant_id: str = "default",
) -> dict[str, Any]:
    bad = [s for s in scopes if s not in SCOPES]
    if bad:
        raise ValueError(f"unknown scopes: {bad}")
    token = "sk_live_" + secrets.token_urlsafe(24)
    kid = "key_" + new_ulid()
    prefix = token[:12]
    with ops_con() as con:
        _ensure(con)
        con.execute(
            """
            INSERT INTO scoped_api_keys
            (key_id, token_hash, prefix, scopes, tenant_id, revoked, created_at)
            VALUES (?, ?, ?, ?, ?, FALSE, ?)
            """,
            [kid, _hash(token), prefix, ",".join(scopes), tenant_id, utc_now()],
        )
    return {
        "key_id": kid,
        "token": token,
        "prefix": prefix,
        "scopes": scopes,
        "tenant_id": tenant_id,
    }


def authenticate_scoped(token: str, needed: str) -> dict[str, Any]:
    if not token:
        return {"ok": False, "reason": "missing_token"}
    digest = _hash(token)
    with ops_con(read_only=True) as con:
        try:
            row = con.execute(
                """
                SELECT key_id, scopes, tenant_id, revoked
                FROM scoped_api_keys WHERE token_hash = ?
                """,
                [digest],
            ).fetchone()
        except Exception:
            return {"ok": False, "reason": "no_store"}
    if not row:
        return {"ok": False, "reason": "unknown_key"}
    if row[3]:
        return {"ok": False, "reason": "revoked"}
    scopes = [s for s in str(row[1]).split(",") if s]
    if needed not in scopes and "*" not in scopes:
        return {"ok": False, "reason": "scope_denied", "scopes": scopes}
    return {"ok": True, "key_id": row[0], "scopes": scopes, "tenant_id": row[2]}


__all__ = ["SCOPES", "create_scoped_key", "authenticate_scoped"]
