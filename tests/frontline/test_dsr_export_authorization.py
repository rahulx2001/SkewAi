"""Tests for F-022: DSR export authorization, dedicated dsr_officer role, credential separation, audit logging, and rate limiting."""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.rbac import PERMS, ROLES
from src.data.warehouse import ops_con

TEST_SERVICE_KEY = "test-service-secret-key-32-chars-auth!"
TEST_DSR_KEY = "test-dsr-officer-secret-key-32-chars-auth!"
TEST_ADMIN_KEY = "test-admin-secret-key-32-chars-auth!!"


@pytest.fixture
def dsr_auth_env(monkeypatch):
    from src.frontline.dsr import reset_dsr_export_rate_limits

    reset_dsr_export_rate_limits()
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", TEST_SERVICE_KEY)
    monkeypatch.setenv("FRONTLINE_DSR_API_KEY", TEST_DSR_KEY)
    monkeypatch.setenv("SESSION_SECRET", TEST_ADMIN_KEY)
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    monkeypatch.delenv("FRONTLINE_SERVICE_IS_ADMIN", raising=False)
    monkeypatch.setenv("FRONTLINE_DSR_EXPORT_RATE_LIMIT", "5")


def test_service_role_cannot_dsr_export(dsr_auth_env, reset_ops_db):
    """1. Shared service key maps to service principal -> 403 on dsr:export."""
    headers = {"X-API-Key": TEST_SERVICE_KEY}
    with TestClient(app) as client:
        resp = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert resp.status_code == 403
        assert "dsr:export" in resp.json().get("detail", "")


def test_dsr_officer_role_can_export(dsr_auth_env, reset_ops_db):
    """2. Dedicated DSR credential maps to dsr_officer -> 200 on dsr:export."""
    headers = {"X-API-Key": TEST_DSR_KEY}
    with TestClient(app) as client:
        resp = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert resp.status_code == 200


def test_dsr_export_audited(dsr_auth_env, reset_ops_db):
    """3. Performing a DSR export writes an audit row to dsr_export_audit."""
    headers = {"X-API-Key": TEST_DSR_KEY}
    with TestClient(app) as client:
        resp = client.get("/api/frontline/cases/export?scrub_pii=false&status=active", headers=headers)
        assert resp.status_code == 200

    with ops_con(read_only=True) as con:
        rows = con.execute(
            "SELECT principal, scope, record_count, created_at FROM dsr_export_audit"
        ).fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "dsr_officer"
        assert "cases_export" in rows[0][1]


def test_dsr_export_rate_limited(dsr_auth_env, reset_ops_db, monkeypatch):
    """4. Exceeding DSR export rate limit returns 429."""
    monkeypatch.setenv("FRONTLINE_DSR_EXPORT_RATE_LIMIT", "2")
    headers = {"X-API-Key": TEST_DSR_KEY}

    with TestClient(app) as client:
        r1 = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert r1.status_code == 200
        r2 = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert r2.status_code == 200
        r3 = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers or "retry-after" in r3.headers


def test_dsr_export_requires_explicit_credential(dsr_auth_env, reset_ops_db):
    """5. Attempting dsr:export without auth returns 401."""
    with TestClient(app) as client:
        resp = client.get("/api/frontline/cases/export?scrub_pii=false")
        assert resp.status_code == 401


def test_dsr_export_with_regular_frontline_key_fails(dsr_auth_env, reset_ops_db):
    """6. Auth with regular frontline API key (service role) fails with 403."""
    headers = {"X-API-Key": TEST_SERVICE_KEY}
    with TestClient(app) as client:
        resp = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert resp.status_code == 403


def test_dsr_export_redaction_default(dsr_auth_env, reset_ops_db):
    """7. Ordinary roles get redacted data by default; cannot opt-out with scrub_pii=false."""
    headers = {"X-API-Key": TEST_SERVICE_KEY}
    with TestClient(app) as client:
        # Default (scrub_pii=True) succeeds for service principal
        resp = client.get("/api/frontline/cases/export", headers=headers)
        assert resp.status_code == 200

        # Attempt to bypass redaction fails with 403
        resp_unredacted = client.get("/api/frontline/cases/export?scrub_pii=false", headers=headers)
        assert resp_unredacted.status_code == 403


def test_service_role_permissions_are_minimal():
    """8. Service role does not include dsr:export, pack:edit, routing:control, approval:decide, or case:write."""
    forbidden = {"dsr:export", "pack:edit", "routing:control", "approval:decide", "case:write"}
    service_perms = PERMS.get("service", frozenset())
    overlap = forbidden & service_perms
    assert not overlap, f"Service role has unexpected permissions: {overlap}"
    assert "dsr_officer" in ROLES
    assert "dsr:export" in PERMS["dsr_officer"]
    assert "case:read" in PERMS["dsr_officer"]
