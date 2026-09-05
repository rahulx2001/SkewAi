"""Public Google / OIDC routes (no API-key gate — the browser starts here)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.api.auth import require_api_key
from src.api.rbac import require_perm_dep
from src.frontline.oidc import (
    begin_login,
    consume_handoff,
    finish_callback,
    provider_status,
    safe_post_login,
    save_local_provider,
)

router = APIRouter(prefix="/api/frontline", tags=["auth-oidc"])


def _session_cookie(resp: JSONResponse | RedirectResponse, token: str) -> None:
    """Set the session cookie with production-compatible attributes (item 19).

    - ``__Host-`` prefix + Secure + HttpOnly + SameSite=Lax + Path=/ when
      production-like (browsers enforce the prefix constraints);
    - unprefixed name over local http dev (Secure cookies would not store).
    Login always mints and sets a FRESH token, rotating any pre-existing
    session (fixation defense); logout clears both names.
    """
    if not token:
        return
    from src.api.rbac import session_cookie_name

    try:
        from src.security.harden import is_production_like

        _secure = is_production_like()
    except Exception:
        _secure = False
    resp.set_cookie(
        key=session_cookie_name(),
        value=token,
        httponly=True,
        secure=_secure,
        samesite="lax",
        path="/",
        max_age=3600,
    )


@router.get("/auth/oidc/status")
async def oidc_status() -> dict[str, Any]:
    st = provider_status()
    return {
        "configured": st["configured"],
        "provider": st["provider"],
        "issuer": st["issuer"],
        "client_id": st["client_id"],
        "start_path": st["start_path"],
        "scopes": st["scopes"],
        "authorization_endpoint": st["authorization_endpoint"],
        "redirect_uri": st["redirect_uri"],
        "source": st.get("source"),
    }


@router.put(
    "/auth/oidc/config",
    dependencies=[Depends(require_api_key)],
)
async def oidc_config_put(
    body: dict[str, Any],
    _role: str = Depends(require_perm_dep("pack:edit", open_mode_ok=True)),
) -> dict[str, Any]:
    """Save Google OAuth client for this machine.

    Authentication (API key) AND authorization (admin ``pack:edit``) are both
    required (item 12): an ordinary API key resolves to the ``service``
    principal, which must not rewrite the IdP configuration. Open local demos
    keep working via ``open_mode_ok``; production-like deploys refuse local
    provider writes entirely (see ``save_local_provider``).
    """
    try:
        st = save_local_provider(
            client_id=str(body.get("client_id") or ""),
            client_secret=str(body.get("client_secret") or ""),
            redirect_uri=str(body.get("redirect_uri") or ""),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "configured": st["configured"],
        "provider": st["provider"],
        "client_id": st["client_id"],
        "redirect_uri": st["redirect_uri"],
        "source": st.get("source"),
        "start_path": st["start_path"],
    }


@router.get("/auth/oidc/start")
async def oidc_start(next: str | None = Query(default=None)) -> RedirectResponse:
    try:
        begun = begin_login(next_url=next)
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        ) from None
    return RedirectResponse(begun["authorize_url"], status_code=302)


@router.get("/auth/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    dest_err = safe_post_login(None, page="signin")
    dest_ok = safe_post_login(None, page="command")
    if error:
        return RedirectResponse(f"{dest_err}?error={quote(str(error))}", status_code=302)
    if not code or not state:
        return RedirectResponse(f"{dest_err}?error=missing_code", status_code=302)
    try:
        done = finish_callback(code=code, state=state)
    except ValueError as exc:
        return RedirectResponse(f"{dest_err}?error={quote(str(exc))}", status_code=302)
    nxt = done.get("next_url") or dest_ok
    if nxt.endswith("#signin"):
        nxt = nxt[: -len("signin")] + "command"
    loc = nxt
    if "?" not in nxt.split("#", 1)[-1]:
        loc = f"{nxt}?handoff={done['handoff']}"
    elif "handoff=" not in nxt:
        loc = f"{nxt}&handoff={done['handoff']}"
    resp = RedirectResponse(loc, status_code=302)
    _session_cookie(resp, str(done.get("token") or ""))
    return resp


@router.post("/auth/logout")
async def auth_logout() -> JSONResponse:
    resp = JSONResponse({"signed_in": False})
    # Invalidate both cookie names (rotation pair); the client keeps no token.
    from src.api.rbac import SESSION_COOKIE_HOST, SESSION_COOKIE_LEGACY

    for name in (SESSION_COOKIE_HOST, SESSION_COOKIE_LEGACY):
        resp.delete_cookie(name, path="/")
    return resp


@router.post("/auth/oidc/complete")
async def oidc_complete(body: dict[str, Any]) -> JSONResponse:
    try:
        out = consume_handoff(str(body.get("handoff") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = out.pop("token", "")
    resp = JSONResponse(out)
    _session_cookie(resp, token)
    return resp
