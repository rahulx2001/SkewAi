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

from fastapi import Depends, Header, HTTPException, Request

ROLES = frozenset({"agent", "supervisor", "auditor", "service", "admin"})
ELEVATED = frozenset({"supervisor", "auditor", "admin"})

#: Session cookie names. ``__Host-`` prefix (item 19) is required where
#: compatible: production-like deploys set Secure, so the prefixed name is
#: enforced by browsers (no Domain, Path=/, Secure). Local http dev keeps
#: the unprefixed name (Secure cookies would never be stored over http).
#: Readers accept both so rotation never locks operators out.
SESSION_COOKIE_HOST = "__Host-frontline_session"
SESSION_COOKIE_LEGACY = "frontline_session"


def session_cookie_name() -> str:
    """Cookie name to SET for new sessions (env-dependent)."""
    try:
        from src.security.harden import is_production_like

        if is_production_like():
            return SESSION_COOKIE_HOST
    except Exception:
        pass
    return SESSION_COOKIE_LEGACY


def session_token_from_cookies(cookies: Any) -> str:
    """Extract the session token, accepting both cookie names.

    The ``__Host-`` variant wins when both are present (it is the only one
    a production-like server sets).
    """
    try:
        get = cookies.get if hasattr(cookies, "get") else (lambda k: None)
        return (
            (get(SESSION_COOKIE_HOST) or "").strip()
            or (get(SESSION_COOKIE_LEGACY) or "").strip()
        )
    except Exception:
        return ""

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
            "routing:control",
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
            "routing:control",
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


def issue_idp_session(subject: str, *, ttl_s: int = 3600) -> dict[str, Any]:
    """Mint an agent session after IdP verification. Never elevates. No issuer role."""
    name = (subject or "").strip() or "idp-user"
    exp = int(time.time()) + max(60, int(ttl_s))
    body = {"sub": name, "role": "agent", "exp": exp, "idp": "oidc"}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    token = f"{raw}|{sig}"
    return {"token": token, "role": "agent", "subject": name, "exp": exp}


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
    if isinstance(x_frontline_session, str) and x_frontline_session:
        body = verify_session(x_frontline_session)
        return str(body.get("sub") or body.get("role") or default)[:80]
    if not _is_open_mode() and _auth_required():
        return default[:80]
    return "operator"


def require_perm(role: str, perm: str, *, open_mode_ok: bool = False) -> None:
    """Raise 403 when *role* is not granted *perm*.

    ``open_mode_ok=True`` skips the check in local open mode (unsigned demo
    operator is always ``agent``). Takeover is never skipped — seizing a live
    customer call is gated even on a laptop.
    """
    if open_mode_ok and _is_open_mode():
        return
    grants = PERMS.get(role, frozenset())
    if "*" in grants or perm in grants:
        return
    raise HTTPException(status_code=403, detail=f"role {role} lacks {perm}")


def require_perm_dep(perm: str, *, open_mode_ok: bool = False):
    """FastAPI dependency that resolves the role and enforces *perm*."""

    async def _dep(role: str = Depends(get_role)) -> str:
        require_perm(role, perm, open_mode_ok=open_mode_ok)
        return role

    _dep.__name__ = f"require_{perm.replace(':', '_')}"
    return _dep


def role_from_websocket(websocket: Any) -> str:
    """Resolve RBAC role from a WebSocket (session cookie / header)."""
    session = ""
    try:
        session = (websocket.headers.get("x-frontline-session") or "").strip()
    except Exception:
        session = ""
    if not session:
        try:
            session = session_token_from_cookies(websocket.cookies)
        except Exception:
            session = ""
    role_hdr = None
    try:
        role_hdr = websocket.headers.get("x-frontline-role")
    except Exception:
        role_hdr = None
    return role_from_headers(role_hdr, session or None)


def oidc_discovery() -> dict[str, Any]:
    from src.frontline.oidc import provider_status

    st = provider_status()
    if not st["configured"] and not os.getenv("OIDC_ISSUER", "").strip():
        return {
            "configured": False,
            "provider": "google",
            "note": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET for Google sign-in",
            "start_path": "/api/frontline/auth/oidc/start",
            "roles": sorted(ROLES),
        }
    return {
        "configured": st["configured"],
        "provider": st["provider"],
        "issuer": st["issuer"],
        "authorization_endpoint": st["authorization_endpoint"],
        "token_endpoint": st["token_endpoint"],
        "jwks_uri": st["jwks_uri"],
        "start_path": st["start_path"],
        "roles": sorted(ROLES),
    }


async def get_role(
    request: Request,
    x_frontline_role: str | None = Header(default=None),
    x_frontline_session: str | None = Header(default=None),
) -> str:
    return role_from_headers(
        x_frontline_role,
        x_frontline_session or session_token_from_cookies(request.cookies),
    )


async def get_actor(
    request: Request,
    x_frontline_session: str | None = Header(default=None),
) -> str:
    return subject_from_headers(
        x_frontline_session or session_token_from_cookies(request.cookies) or None
    )
