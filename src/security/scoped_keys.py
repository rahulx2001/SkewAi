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

from collections import defaultdict
import threading
import time

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

_rate_limit_lock = threading.Lock()
_mint_history: dict[str, list[float]] = defaultdict(list)


def check_key_mint_rate_limit(
    principal: str,
    limit: int | None = None,
    window_s: float = 60.0,
) -> tuple[bool, int]:
    """Sliding-window rate limiter for scoped-key minting per principal."""
    if limit is None:
        try:
            limit = int(os.getenv("FRONTLINE_KEY_MINT_RATE_LIMIT", "10"))
        except Exception:
            limit = 10
    now = time.time()
    cutoff = now - window_s
    with _rate_limit_lock:
        history = [ts for ts in _mint_history[principal] if ts > cutoff]
        if len(history) >= limit:
            oldest = min(history) if history else now
            retry_after = max(1, int(window_s - (now - oldest)))
            _mint_history[principal] = history
            return False, retry_after
        history.append(now)
        _mint_history[principal] = history
        return True, 0


def reset_key_mint_rate_limits() -> None:
    """Reset rate limit history (testing)."""
    with _rate_limit_lock:
        _mint_history.clear()


def _ensure_audit_table(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS key_mint_audit (
            audit_id VARCHAR PRIMARY KEY,
            principal VARCHAR NOT NULL,
            requested_scopes VARCHAR NOT NULL,
            granted_scopes VARCHAR NOT NULL,
            tenant_id VARCHAR NOT NULL,
            ip VARCHAR,
            success BOOLEAN NOT NULL,
            error VARCHAR,
            created_at TIMESTAMP NOT NULL
        )
        """
    )


def log_key_mint_audit(
    *,
    principal: str,
    requested_scopes: list[str],
    granted_scopes: list[str],
    tenant_id: str,
    ip: str | None = None,
    success: bool,
    error: str | None = None,
) -> None:
    """Log an audit entry for key minting."""
    aid = "audit_" + new_ulid()
    now = utc_now()
    req_str = ",".join(requested_scopes) if isinstance(requested_scopes, (list, set, tuple)) else str(requested_scopes)
    grant_str = ",".join(granted_scopes) if isinstance(granted_scopes, (list, set, tuple)) else str(granted_scopes)
    try:
        with ops_con() as con:
            _ensure_audit_table(con)
            con.execute(
                """
                INSERT INTO key_mint_audit
                (audit_id, principal, requested_scopes, granted_scopes, tenant_id, ip, success, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [aid, str(principal), req_str, grant_str, str(tenant_id), ip, bool(success), error, now],
            )
    except Exception:
        pass


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
    salt_raw = (os.getenv("SCOPED_KEY_SALT") or "").strip()
    if not salt_raw:
        from src.security.harden import is_production_like

        if is_production_like():
            raise RuntimeError("SCOPED_KEY_SALT required in production-like mode")
        salt_raw = "skew-scoped-v1"
    salt = salt_raw.encode("utf-8")
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


__all__ = [
    "SCOPES",
    "create_scoped_key",
    "authenticate_scoped",
    "check_key_mint_rate_limit",
    "reset_key_mint_rate_limits",
    "log_key_mint_audit",
]
