"""RBAC then SSO surface (feature #50).

Roles: agent / supervisor / auditor / service / admin. Pilot uses signed session tokens.
Bare ``X-Frontline-Role`` cannot elevate above agent (FIND-003). Elevated roles
require a signed session.

Session minting (FIND-002):
- Open mode: always issues ``agent`` only (short TTL).
- Hardened: never signs with the literal ``dev-only`` fallback.
- Elevated roles require an admin issuer session (or explicit bootstrap env).

Service principal (H1 reduce):
- Validated shared API key without a session is ``service`` (not full admin).
- Dangerous ops (pack disk edit, drain, jobs run-next, DSR delete) need admin.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Header, HTTPException

ROLES = frozenset({"agent", "supervisor", "auditor", "service", "admin"})
ELEVATED = frozenset({"supervisor", "auditor", "admin"})

# Permission matrix (pilot)
PERMS: dict[str, frozenset[str]] = {
    "agent": frozenset({"contact:write", "case:read"}),
    "service": frozenset(
        {
            "contact:write",
            "case:read",
            "case:write",
            "takeover",
            "approval:decide",
            "dsr:export",
            "audit:read",
            "ledger:read",
            "channel:ingest",
            "biometrics:match",
            "session:mint",
        }
    ),
    "supervisor": frozenset(
        {
            "contact:write",
            "case:read",
            "case:write",
            "takeover",
            "approval:decide",
            "dsr:export",
            "channel:ingest",
            "biometrics:match",
        }
    ),
    "auditor": frozenset({"case:read", "audit:read", "ledger:read", "dsr:export"}),
    "admin": frozenset(
        {
            "*",
            "dsr:export",
            "dsr:delete",
            "marketplace:install",
            "session:mint",
            "pack:edit",
            "pack:activate",
            "ops:drain",
            "jobs:run",
            "channel:ingest",
            "biometrics:match",
        }
    ),
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_open_mode() -> bool:
    from src.api.auth import is_open_mode

    return is_open_mode()


def _auth_required() -> bool:
    from src.api.auth import auth_required

    return auth_required()


def _secret() -> bytes:
    """HMAC material for session tokens.

    Hardened (auth required): never fall back to the public ``dev-only`` string.
    Open mode may still use a weak fallback so local demos work without secrets.
    """
    secret = (os.getenv("SESSION_SECRET") or os.getenv("FRONTLINE_API_KEY") or "").strip()
    if secret:
        return secret.encode()
    if _auth_required() or _env_bool("PILOT_HARDENED", False):
        raise HTTPException(
            status_code=503,
            detail=(
                "SESSION_SECRET or FRONTLINE_API_KEY must be configured for "
                "session tokens when auth is required (refusing dev-only fallback)."
            ),
        )
    return b"dev-only"


def issue_session(
    subject: str,
    role: str,
    *,
    issuer_role: str | None = None,
    ttl_s: int = 3600,
) -> dict[str, Any]:
    """Mint a signed session. Elevated roles need an admin issuer (or bootstrap)."""
    requested = (role or "agent").strip().lower()
    if requested not in ROLES or requested == "service":
        # service is a machine principal, not a mintable end-user session role
        if requested == "service":
            requested = "agent"
        elif requested not in ROLES:
            requested = "agent"

    if _is_open_mode():
        # FIND-002: open mode never elevates
        requested = "agent"
        ttl_s = min(int(ttl_s), 900)
    else:
        issuer = (issuer_role or "agent").strip().lower()
        if issuer not in ROLES:
            issuer = "agent"
        bootstrap = _env_bool("FRONTLINE_BOOTSTRAP_ADMIN", False)
        if requested in ELEVATED:
            allowed = issuer == "admin" or (
                requested == "admin" and bootstrap
            )
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"role {requested!r} requires an admin session issuer "
                        f"(or FRONTLINE_BOOTSTRAP_ADMIN=1 for one-time admin mint)"
                    ),
                )

    exp = int(time.time()) + max(60, int(ttl_s))
    body = {"sub": subject, "role": requested, "exp": exp}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    token = f"{raw}|{sig}"
    return {"token": token, "role": requested, "subject": subject, "exp": exp}


def verify_session(token: str) -> dict[str, Any]:
    if "|" not in token:
        raise HTTPException(status_code=401, detail="invalid session token")
    raw, sig = token.rsplit("|", 1)
    expect = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        raise HTTPException(status_code=401, detail="bad session signature")
    body = json.loads(raw)
    if int(body.get("exp") or 0) < time.time():
        raise HTTPException(status_code=401, detail="session expired")
    return body


def role_from_headers(
    x_frontline_role: str | None = None,
    x_frontline_session: str | None = None,
) -> str:
    """Resolve role.

    - Signed session: trust session role.
    - Auth required (shared API key validated by Depends): service principal
      (not full admin — H1). Opt-in full admin via FRONTLINE_SERVICE_IS_ADMIN=1.
    - Open mode / unauthenticated: agent only; bare ``X-Frontline-Role`` cannot elevate.
    """
    if x_frontline_session:
        return str(verify_session(x_frontline_session).get("role") or "agent")
    # FIND-003: bare header never elevates
    if x_frontline_role:
        role = x_frontline_role.strip().lower()
        if role not in ROLES:
            raise HTTPException(status_code=400, detail=f"unknown role: {role}")
        if role in ELEVATED or role == "service":
            role = "agent"
    else:
        role = "agent"
    # Shared API key → limited service principal (or legacy full admin opt-in)
    if not _is_open_mode() and _auth_required():
        if _env_bool("FRONTLINE_SERVICE_IS_ADMIN", False):
            return "admin"
        return "service"
    return role


def subject_from_headers(
    x_frontline_session: str | None = None,
    *,
    default: str = "service",
) -> str:
    """Identity for audit fields — never trust client body.author under harden."""
    if x_frontline_session:
        body = verify_session(x_frontline_session)
        return str(body.get("sub") or body.get("role") or default)[:80]
    if not _is_open_mode() and _auth_required():
        return default[:80]
    return "operator"


def require_perm(role: str, perm: str) -> None:
    grants = PERMS.get(role, frozenset())
    if "*" in grants or perm in grants:
        return
    raise HTTPException(status_code=403, detail=f"role {role} lacks {perm}")


def oidc_discovery() -> dict[str, Any]:
    issuer = os.getenv("OIDC_ISSUER", "").strip()
    if not issuer:
        return {
            "configured": False,
            "note": "Set OIDC_ISSUER for enterprise SSO; pilot uses session tokens + roles",
            "roles": sorted(ROLES),
        }
    return {
        "configured": True,
        "issuer": issuer,
        "authorization_endpoint": f"{issuer.rstrip('/')}/authorize",
        "token_endpoint": f"{issuer.rstrip('/')}/token",
        "jwks_uri": f"{issuer.rstrip('/')}/jwks",
        "roles": sorted(ROLES),
    }


async def get_role(
    x_frontline_role: str | None = Header(default=None),
    x_frontline_session: str | None = Header(default=None),
) -> str:
    return role_from_headers(x_frontline_role, x_frontline_session)


async def get_actor(
    x_frontline_session: str | None = Header(default=None),
) -> str:
    return subject_from_headers(x_frontline_session)
