"""Skew AI (skewai) FastAPI app.

Mounts the interactions, packs, and frontline routers. Adds CORS for the
dashboard dev server, slowapi rate-limiting on the start/simulate endpoints,
and a health check. Product brand is Skew AI; API path prefixes remain
``/api/frontline/*`` for compatibility.

Run with:
    uvicorn src.api.main:app --reload --port 8000
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.frontline_gate import frontline_enabled, is_frontline_surface_path
from src.api.limiter import limiter
from src.api.problems import install_openapi_problem, problem, register_exception_handlers
from src.api.routes import frontline, interactions, packs
from src.config import REPO_ROOT, settings
from src.domains.active_pack import resolve_active_pack_id

# Stable pilot API version (URL stays /api/...; bump only on breaking changes).
API_VERSION = "1"


class FrontlineEnabledASGI:
    """Pure ASGI gate for HTTP **and** WebSocket scopes.

    ``BaseHTTPMiddleware`` never runs for ``websocket`` scopes, so the path
    check for ``/ws/*`` must live here (or in each WS handler).
    When FRONTLINE_ENABLED=0: ``/api/*`` → 503, ``/ws/*`` → close without
    accept. ``/health`` and ``/ui`` stay up.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path") or ""
            if not frontline_enabled() and is_frontline_surface_path(path):
                if scope["type"] == "http":
                    response = JSONResponse(
                        status_code=503,
                        content=problem(
                            503,
                            "Skew AI is disabled (FRONTLINE_ENABLED=0).",
                            extra={"frontline_enabled": False},
                        ),
                    )
                    await response(scope, receive, send)
                    return
                # WebSocket: refuse before accept (policy violation / try later).
                await send({"type": "websocket.close", "code": 1013})
                return
        await self.app(scope, receive, send)


from contextlib import asynccontextmanager

from src.security.harden import is_production_like


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # SOC/production fail-closed: refuse open mode + weak secrets when hardened.
    from src.security.harden import validate_startup_security

    validate_startup_security()
    # Feature #51: SIGTERM begins call drain (reject new contacts, finish active).
    try:
        from src.ops.drain import install_sigterm_handler

        install_sigterm_handler()
    except Exception:
        pass
    # Startup: close stale active interaction rows not in the live registry.
    try:
        from src.api.routes.interactions import reap_orphans

        await reap_orphans()
    except Exception:
        pass
    try:
        from src.jobs.registry import register_worker

        register_worker(host="api")
    except Exception:
        pass
    yield


# Production-like: disable interactive docs / OpenAPI (anonymous attack surface).
# Local demos keep /docs. Override with FRONTLINE_OPENAPI_PUBLIC=1 if needed.
_docs_public = (
    os.getenv("FRONTLINE_OPENAPI_PUBLIC", "").strip().lower() in {"1", "true", "yes", "on"}
    or not is_production_like()
)

app = FastAPI(
    title="Skew AI — Voice-of-Customer Intelligence Platform",
    description=(
        "Skew AI (skewai): domain-agnostic voice-of-customer intelligence. "
        "Plug in a Domain Pack and get an AI voice agent, a swarm of triage/RCA "
        "agents, and the Qubot v2 auditor.\n\n"
        "## Auth\n"
        "When `FRONTLINE_API_KEY` is set, send `X-API-Key` or `Authorization: Bearer`.\n\n"
        "## Versioning\n"
        f"Current API version **{API_VERSION}** (header `API-Version`). "
        "Paths under `/api/...` are v1 without a URL prefix. Breaking changes will "
        "introduce `/api/v2/...`.\n\n"
        "## Errors\n"
        "Errors use RFC 7807-shaped JSON (`type`, `title`, `status`, `detail`) "
        "while keeping FastAPI's `detail` string for existing clients.\n\n"
        "## Pagination\n"
        "Collection endpoints accept `limit`, `offset`, and optional `cursor`, "
        "and return a `pagination` object (`has_more`, `next_offset`, `next_cursor`)."
    ),
    version="2.0.0",
    lifespan=_lifespan,
    docs_url="/docs" if _docs_public else None,
    redoc_url="/redoc" if _docs_public else None,
    openapi_url="/openapi.json" if _docs_public else None,
    openapi_tags=[
        {"name": "interactions", "description": "Live contacts and takeover"},
        {"name": "packs", "description": "Domain pack discovery and activation"},
        {"name": "frontline", "description": "Skew AI ops: cases, investigations, audits"},
        {"name": "enterprise", "description": "Enterprise ops explorers"},
        {"name": "v3-platform", "description": "v3 OS: learning, experiments, governance"},
        {"name": "platform56", "description": "56-feature surfaces"},
        {"name": "meta", "description": "Health and discovery"},
    ],
)

# Wire slowapi
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
register_exception_handlers(app)
install_openapi_problem(app)

# ── CORS (env-configurable; safe local defaults) ─────────────────────────────
_DEFAULT_CORS = [
    "http://127.0.0.1:8787",
    "http://localhost:8787",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]


def _cors_origins() -> list[str]:
    """Allowlist origins. Never accept ``*`` with credentials (M11)."""
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
    else:
        origins = list(_DEFAULT_CORS)
    cleaned: list[str] = []
    for o in origins:
        if o == "*":
            # Credentialed CORS + wildcard is unsafe; drop and keep defaults.
            continue
        cleaned.append(o)
    return cleaned or list(_DEFAULT_CORS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Frontline-Session", "X-Frontline-Role"],
)
# Pure ASGI (not BaseHTTPMiddleware) so /ws/* is gated too.
app.add_middleware(FrontlineEnabledASGI)  # type: ignore[arg-type]

# Security headers (CSP, frame deny, nosniff, HSTS) — SOC 2 CC6 baseline.
from src.security.headers import SecurityHeadersASGI

app.add_middleware(SecurityHeadersASGI)  # type: ignore[arg-type]


class ApiVersionASGI:
    """Attach stable API-Version header to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_version(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"api-version", API_VERSION.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_version)


app.add_middleware(ApiVersionASGI)  # type: ignore[arg-type]


# ── Routers ──────────────────────────────────────────────────────────────────
from src.api.routes import enterprise as enterprise_routes
from src.api.routes import pipeline as pipeline_routes
from src.api.routes import platform56 as platform56_routes
from src.api.routes import v3_platform as v3_routes

app.include_router(interactions.router)
app.include_router(packs.router)
app.include_router(frontline.router)
app.include_router(platform56_routes.router)
app.include_router(enterprise_routes.router)
app.include_router(v3_routes.router)
app.include_router(pipeline_routes.router)

# Blueprint §8.2: WebSocket endpoints live at the app root (not under /api/...).
app.add_api_websocket_route(
    "/ws/interaction/{interaction_id}",
    interactions.interaction_ws,
)
app.add_api_websocket_route("/ws/console", interactions.console_ws)


# ── Health + root (always public — no API key) ───────────────────────────────


@app.get("/", tags=["meta"])
async def root() -> dict:
    # Match real policy (production-like / AUTH_REQUIRED), not key presence alone.
    from src.api.auth import auth_required as auth_is_required

    auth = auth_is_required()
    docs_on = (
        os.getenv("FRONTLINE_OPENAPI_PUBLIC", "").strip().lower()
        in {"1", "true", "yes", "on"}
        or not is_production_like()
    )
    return {
        "name": "Skew AI",
        "brand": "skewai",
        "version": "2.0.0",
        "api_version": API_VERSION,
        "active_pack": resolve_active_pack_id(),
        "frontline_enabled": frontline_enabled(),
        "docs": "/docs" if docs_on else None,
        "openapi": "/openapi.json" if docs_on else None,
        "redoc": "/redoc" if docs_on else None,
        "auth_required": auth,
        "auth": {
            "type": "api_key",
            "headers": ["X-API-Key", "Authorization: Bearer"],
            "required": auth,
        },
        "links": {
            "health": "/health",
            "interactions": "/api/interactions",
            "cases": "/api/frontline/cases",
            "packs": "/api/packs",
            "enterprise": "/api/frontline/enterprise",
            "v3_learning": "/api/v3/learning/proposals",
            "v3_experiments": "/api/v3/experiments",
            "v3_governance": "/api/v3/governance/deployments",
        },
    }


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Deep-ish health: process up + ops DB reachability + active pack loadable."""
    from src.data.warehouse import ops_con
    from src.domains.loader import load_pack

    pack_id = resolve_active_pack_id()
    db_ok = False
    pack_ok = False
    detail: dict = {}
    try:
        with ops_con(read_only=True) as con:
            con.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as e:
        detail["db_error"] = f"{type(e).__name__}: {e}"
    try:
        load_pack(pack_id)
        pack_ok = True
    except Exception as e:
        detail["pack_error"] = f"{type(e).__name__}: {e}"

    from src.api.auth import auth_required as auth_is_required
    from src.jobs.registry import backend_name, worker_count
    from src.security.harden import is_production_like

    n_workers = worker_count()
    status = "ok" if (db_ok and pack_ok) else "degraded"
    body = {
        "status": status,
        "api_version": API_VERSION,
        "active_pack": pack_id,
        "frontline_enabled": frontline_enabled(),
        "db_ok": db_ok,
        "pack_ok": pack_ok,
        "single_worker": n_workers <= 1,
        "worker_count": n_workers,
        "orchestrator_registry": "in_process",
        "worker_registry": backend_name(),
        "security": {
            "auth_required": auth_is_required(),
            "production_like": is_production_like(),
            "audit_log": True,
            "soc2_engineering_baseline": True,
            "note": (
                "Engineering controls only — SOC 2 Type II requires policies, "
                "evidence over time, and a CPA attestation."
            ),
        },
        # Keys may be set in env but no provider is shipped — always false until src/ai exists.
        "llm_available": settings.llm_available,
        # Fail-closed when FRONTLINE_AUTH_REQUIRED=1 or a non-empty API key is set
        # (unless FRONTLINE_OPEN_MODE=1). Not SOC2 / multi-tenant identity.
        "auth_required": auth_is_required(),
        # Honesty: v3 registry stamps do not route models or change agent policy.
        "v3_runtime_routing": False,
        "ml_severity_shipped": False,
        "enterprise_readiness": (
            "single_tenant_hardened"
            if auth_is_required()
            else "single_tenant_pilot_open"
        ),
    }
    if detail:
        body["detail"] = detail
    return body


# Serve built dashboard (Docker / pilot one-box). Prefer SPA at /ui.
_DASH_DIST = REPO_ROOT / "dashboard" / "dist"
if _DASH_DIST.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_DASH_DIST), html=True), name="dashboard")
