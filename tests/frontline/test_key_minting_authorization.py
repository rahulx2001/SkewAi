"""Tests for F-005: Scoped-key minting authorization, scope restriction, tenant binding, rate limiting, and audit logging."""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.rbac import issue_session
from src.data.warehouse import ops_con

TEST_ADMIN_KEY = "test-admin-secret-key-32-chars-auth!!"
TEST_SERVICE_KEY = "test-service-secret-key-32-chars-auth!"


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", TEST_SERVICE_KEY)
    monkeypatch.setenv("SESSION_SECRET", TEST_ADMIN_KEY)
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    monkeypatch.delenv("FRONTLINE_SERVICE_IS_ADMIN", raising=False)
    # Rate limit setting
    monkeypatch.setenv("FRONTLINE_KEY_MINT_RATE_LIMIT", "10")


def test_keys_route_requires_auth(auth_env, reset_ops_db):
    """1. Call POST /keys without any auth header -> 401 Unauthorized."""
    with TestClient(app) as client:
        resp = client.post("/api/frontline/keys", json={"scopes": ["kpi:read"], "tenant_id": "tenant-A"})
        assert resp.status_code == 401


def test_keys_route_rejects_unauthorized_minter(auth_env, reset_ops_db):
    """2. Auth with a principal that lacks admin:keys -> 403 Forbidden."""
    with TestClient(app) as client:
        # Service principal lacks admin:keys
        headers = {"X-API-Key": TEST_SERVICE_KEY}
        resp = client.post(
            "/api/frontline/keys",
            headers=headers,
            json={"scopes": ["kpi:read"], "tenant_id": "tenant-A"},
        )
        assert resp.status_code == 403


def test_keys_route_rejects_scope_escalation(auth_env, reset_ops_db):
    """3. Auth with a principal holding only kpi:read -> attempt to mint admin:* scopes -> 403 with scope_escalation_denied."""
    # Issue a session with specific limited scopes
    token = issue_session(
        "sub_user",
        "agent",
        issuer_role="admin",
        extra={"scopes": ["kpi:read"], "tenant_id": "tenant-A"},
    )["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": token}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/keys",
            headers=headers,
            json={"scopes": ["admin:*", "marketplace:install"], "tenant_id": "tenant-A"},
        )
        assert resp.status_code == 403
        assert "scope_escalation_denied" in resp.json().get("detail", "")


def test_keys_route_allows_subset_scopes(auth_env, reset_ops_db):
    """4. Auth with a principal holding kpi:read and queue:read -> mint key with only kpi:read -> 200."""
    token = issue_session(
        "sub_admin",
        "admin",
        issuer_role="admin",
        extra={"scopes": ["kpi:read", "queue:read"], "tenant_id": "default"},
    )["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": token}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/keys",
            headers=headers,
            json={"scopes": ["kpi:read"], "tenant_id": "default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scopes"] == ["kpi:read"]
        assert data["tenant_id"] == "default"


def test_keys_route_enforces_tenant_binding(auth_env, reset_ops_db):
    """5. Auth with tenant_id='tenant-A' -> attempt to mint for 'tenant-B' -> 403 with tenant_mismatch."""
    token = issue_session(
        "sub_admin_a",
        "admin",
        issuer_role="admin",
        extra={"tenant_id": "tenant-A", "scopes": ["kpi:read"]},
    )["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": token}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/keys",
            headers=headers,
            json={"scopes": ["kpi:read"], "tenant_id": "tenant-B"},
        )
        assert resp.status_code == 403
        detail = resp.json().get("detail", "")
        assert "tenant_mismatch" in detail or "single_tenant" in detail


def test_keys_route_rejects_cross_tenant_even_for_admin(auth_env, reset_ops_db):
    """Single-tenant: admin cannot mint a key for another tenant."""
    token = issue_session(
        "sub_superadmin",
        "admin",
        issuer_role="admin",
        extra={"tenant_id": "default", "scopes": ["kpi:read", "*"]},
    )["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": token}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/keys",
            headers=headers,
            json={"scopes": ["kpi:read"], "tenant_id": "tenant-B"},
        )
        assert resp.status_code == 403
        assert "single_tenant" in resp.json().get("detail", "")


def test_keys_route_rate_limited(auth_env, reset_ops_db, monkeypatch):
    """7. Exceed rate limit -> 429 with Retry-After header."""
    monkeypatch.setenv("FRONTLINE_KEY_MINT_RATE_LIMIT", "2")
    token = issue_session("sub_rate", "admin", issuer_role="admin")["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": token}

    with TestClient(app) as client:
        # Request 1: ok
        r1 = client.post("/api/frontline/keys", headers=headers, json={"scopes": ["kpi:read"], "tenant_id": "default"})
        assert r1.status_code == 200

        # Request 2: ok
        r2 = client.post("/api/frontline/keys", headers=headers, json={"scopes": ["kpi:read"], "tenant_id": "default"})
        assert r2.status_code == 200

        # Request 3: rate limited -> 429
        r3 = client.post("/api/frontline/keys", headers=headers, json={"scopes": ["kpi:read"], "tenant_id": "default"})
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers or "retry-after" in r3.headers


def test_keys_route_audits_every_mint(auth_env, reset_ops_db):
    """8. Mint a key -> assert an audit row exists with principal, scopes, tenant, timestamp."""
    token = issue_session("audited_admin", "admin", issuer_role="admin")["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": token}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/keys",
            headers=headers,
            json={"scopes": ["kpi:read", "billing:read"], "tenant_id": "default"},
        )
        assert resp.status_code == 200

    with ops_con(read_only=True) as con:
        rows = con.execute(
            "SELECT principal, requested_scopes, tenant_id, success FROM key_mint_audit WHERE principal = 'audited_admin'"
        ).fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "audited_admin"
        assert "kpi:read" in rows[0][1]
        assert rows[0][3] is True


def test_marketplace_install_requires_admin(auth_env, reset_ops_db):
    """9. Attempt marketplace install with a key lacking admin.* permission -> 403."""
    agent_token = issue_session("agent_user", "agent", issuer_role="admin")["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": agent_token}

    with TestClient(app) as client:
        resp = client.post("/api/frontline/marketplace/install/automotive_nhtsa", headers=headers)
        assert resp.status_code == 403


def test_governance_activation_requires_admin(auth_env, reset_ops_db):
    """10. Attempt governance activation with a key lacking admin.* permission -> 403."""
    agent_token = issue_session("agent_user", "agent", issuer_role="admin")["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": agent_token}

    with TestClient(app) as client:
        resp = client.post("/api/v3/governance/deployments/dep_123/activate", headers=headers, json={})
        assert resp.status_code == 403
