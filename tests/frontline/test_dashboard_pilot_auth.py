"""Dashboard pilot-auth wiring — CallWidget + LiveConsole must send the key.

When FRONTLINE_API_KEY is set, REST write routes require X-API-Key and WS
routes require ?api_key=. Settings stores the secret in localStorage as
``frontline_api_key``. These tests pin the shipped JSX to the shared helper
so pilot compose mode does not 401 start/takeover or close WS with 1008.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "dashboard"
AUTH_JS = DASH / "src" / "apiAuth.js"
CALL_WIDGET = DASH / "routes" / "CallWidget.jsx"
LIVE_CONSOLE = DASH / "routes" / "LiveContactConsole.jsx"


def test_api_auth_helper_exports_expected_symbols():
    src = AUTH_JS.read_text(encoding="utf-8")
    assert "frontline_api_key" in src
    assert "export function apiHeaders" in src
    assert "export function withApiKeyQuery" in src
    assert "export function sendWsAuth" in src
    assert "X-API-Key" in src
    assert "SESSION_STORAGE" not in src
    assert "X-Frontline-Session" not in src
    assert "export async function signIn" not in src
    assert "export async function signOut" in src
    assert "export async function completeGoogleHandoff" in src
    assert "/api/frontline/auth/oidc/complete" in src
    assert "/api/frontline/auth/me" in src
    assert "server leaked session token" in src
    # WS auth frame uses api_key field (not URL query leakage)
    assert '"auth"' in src or "type: \"auth\"" in src or "type: 'auth'" in src


def test_sidebar_account_uses_shared_web_signin() -> None:
    app = (DASH / "src" / "App.jsx").read_text(encoding="utf-8")
    acc = (DASH / "src" / "ui" / "AccountSignIn.jsx").read_text(encoding="utf-8")
    assert "AccountSignIn" in app
    assert "SignIn" in app
    assert "signin" in acc
    assert "Sign in" in acc
    page = (DASH / "routes" / "SignIn.jsx").read_text(encoding="utf-8")
    assert "Continue with Google" in page
    assert "/api/frontline/auth/oidc/start" in page
    assert "saveGoogleProvider" in page
    auth = AUTH_JS.read_text(encoding="utf-8")
    assert "export async function saveGoogleProvider" in auth
    assert "/api/frontline/auth/oidc/config" in auth


def test_callwidget_wires_api_key_on_start_end_and_ws():
    src = CALL_WIDGET.read_text(encoding="utf-8")
    assert 'from "../src/apiAuth.js"' in src or "from '../src/apiAuth.js'" in src
    assert "apiHeaders" in src
    assert "withApiKeyQuery" in src
    # start POST must pass headers
    assert "interactions/start" in src
    assert "headers: apiHeaders()" in src
    # end POST must pass headers
    assert "/end" in src
    # WS: no query-string secret; sendWsAuth after open
    assert "withApiKeyQuery(" in src or "sendWsAuth" in src
    assert "sendWsAuth" in src
    assert "ws_url" in src


def test_live_console_wires_api_key_on_takeover_release_and_console_ws():
    src = LIVE_CONSOLE.read_text(encoding="utf-8")
    assert 'from "../src/apiAuth.js"' in src or "from '../src/apiAuth.js'" in src
    assert "apiHeaders" in src
    assert "withApiKeyQuery" in src
    assert "/takeover" in src
    assert "/release" in src
    assert "headers: apiHeaders()" in src
    assert "/ws/console" in src
    assert "sendWsAuth" in src
    # Active-list poll is protected (GET /api/interactions) — must send key
    assert "/api/interactions?status=active" in src or "status=active" in src
    # Ensure the poll fetch is not a bare fetch without headers nearby
    assert src.count("apiHeaders()") >= 3  # poll + takeover + release at minimum


def test_case_queue_early_warning_audits_send_api_headers():
    """H-NEW-1: protected dashboard pages must use apiHeaders on fetches."""
    case_q = (DASH / "routes" / "CaseQueue.jsx").read_text(encoding="utf-8")
    ew = (DASH / "routes" / "EarlyWarningBoard.jsx").read_text(encoding="utf-8")
    audits = (DASH / "routes" / "AuditReports.jsx").read_text(encoding="utf-8")
    for name, src in [("CaseQueue", case_q), ("EarlyWarning", ew), ("Audits", audits)]:
        assert "apiHeaders" in src, f"{name} missing apiHeaders"
        assert "apiHeaders()" in src, f"{name} never calls apiHeaders()"
    assert "/api/frontline/cases" in case_q
    assert "headers: apiHeaders()" in case_q or "headers: apiHeaders()" in case_q.replace("\n", " ")
    assert "early-warning" in ew
    assert "apiHeaders()" in ew
    assert "/api/frontline/audits" in audits
    # list + detail + export all need headers
    assert audits.count("apiHeaders()") >= 3


def test_built_dist_ships_api_headers_on_protected_fetches():
    """Pilot SPA under /ui is dist — must not be a stale build without X-API-Key."""
    dist = DASH / "dist"
    assert dist.is_dir(), "dashboard/dist missing — run npm run build"
    js_files = list((dist / "assets").glob("index-*.js")) if (dist / "assets").is_dir() else []
    assert js_files, "no dist/assets/index-*.js — rebuild dashboard"
    # Bundle minifies identifiers; still contains the header name and API paths.
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in js_files)
    assert "X-API-Key" in blob or "x-api-key" in blob.lower(), (
        "built dist has no X-API-Key — rebuild after apiAuth wiring"
    )
    for path in (
        "/api/frontline/cases",
        "/api/frontline/early-warning",
        "/api/frontline/audits",
        "/api/interactions",
    ):
        assert path in blob, f"dist missing path {path}"


def test_ws_auth_frame_and_backend_still_accept_key(monkeypatch):
    """Dashboard sendWsAuth + backend check_api_key / first-message path."""
    from src.api.auth import check_api_key
    from fastapi import HTTPException

    secret = "pilot-secret-xyz"
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    monkeypatch.delenv("FRONTLINE_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("FRONTLINE_API_KEY", secret)
    check_api_key(api_key=secret)  # no raise
    with pytest.raises(HTTPException) as ei:
        check_api_key(api_key="")
    assert ei.value.status_code == 401

    # Structural: CallWidget sends auth frame
    assert "sendWsAuth" in CALL_WIDGET.read_text(encoding="utf-8")
