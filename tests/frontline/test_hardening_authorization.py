"""Tests for F-006: Hardening routes authentication, per-endpoint RBAC, and open-mode safety."""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.rbac import issue_session

TEST_ADMIN_KEY = "test-admin-secret-key-32-chars-auth!!"
TEST_SERVICE_KEY = "test-service-secret-key-32-chars-auth!"


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("FRONTLINE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("FRONTLINE_API_KEY", TEST_SERVICE_KEY)
    monkeypatch.setenv("SESSION_SECRET", TEST_ADMIN_KEY)
    monkeypatch.delenv("FRONTLINE_OPEN_MODE", raising=False)
    monkeypatch.delenv("FRONTLINE_SERVICE_IS_ADMIN", raising=False)


def test_hardening_routes_require_auth(auth_env, reset_ops_db):
    """1. With FRONTLINE_AUTH_REQUIRED=1, calling hardening endpoints without auth returns 401."""
    with TestClient(app) as client:
        endpoints = [
            ("GET", "/api/frontline/hardening/slos", None),
            ("GET", "/api/frontline/hardening/retention", None),
            ("POST", "/api/frontline/hardening/fairness", {"cases": []}),
            ("POST", "/api/frontline/hardening/cost", {"llm_usd": 0.0}),
        ]
        for method, path, payload in endpoints:
            if method == "GET":
                resp = client.get(path)
            else:
                resp = client.post(path, json=payload)
            assert resp.status_code == 401, f"Expected 401 on {path}, got {resp.status_code}"


def test_hardening_get_requires_ops_read(auth_env, reset_ops_db):
    """2. Auth with a principal lacking ops:read (e.g. agent) -> 403."""
    agent_token = issue_session("agent_usr", "agent", issuer_role="admin")["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": agent_token}

    with TestClient(app) as client:
        resp = client.get("/api/frontline/hardening/slos", headers=headers)
        assert resp.status_code == 403
        assert "ops:read" in resp.json().get("detail", "")


def test_hardening_get_allows_ops_read(auth_env, reset_ops_db):
    """3. Auth with ops:read (service principal or admin) -> 200."""
    headers = {"X-API-Key": TEST_SERVICE_KEY}

    with TestClient(app) as client:
        resp = client.get("/api/frontline/hardening/slos", headers=headers)
        assert resp.status_code == 200
        assert "stages" in resp.json()


def test_hardening_post_requires_ops_write(auth_env, reset_ops_db):
    """4. Auth with a principal lacking ops:write (e.g. service principal) -> 403."""
    # Service principal has ops:read, but not ops:write
    headers = {"X-API-Key": TEST_SERVICE_KEY}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/hardening/fairness",
            headers=headers,
            json={"cases": []},
        )
        assert resp.status_code == 403
        assert "ops:write" in resp.json().get("detail", "")


def test_hardening_post_allows_ops_write(auth_env, reset_ops_db):
    """5. Auth with ops:write (admin principal) -> 200."""
    admin_token = issue_session("admin_usr", "admin", issuer_role="admin")["token"]
    headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": admin_token}

    with TestClient(app) as client:
        resp = client.post(
            "/api/frontline/hardening/fairness",
            headers=headers,
            json={"cases": []},
        )
        assert resp.status_code == 200


def test_open_mode_disabled_when_auth_required(auth_env, reset_ops_db, monkeypatch):
    """6. When FRONTLINE_AUTH_REQUIRED=1, open_mode_ok must be forced to False (never 200 without auth or permission)."""
    # Even if FRONTLINE_OPEN_MODE=1 is set, auth_required must override it
    monkeypatch.setenv("FRONTLINE_OPEN_MODE", "1")

    with TestClient(app) as client:
        # Unauthenticated request must not pass
        resp = client.get("/api/frontline/hardening/slos")
        assert resp.status_code in {401, 403}

        # Request from agent without ops:read must not pass
        agent_token = issue_session("agent_usr", "agent", issuer_role="admin")["token"]
        headers = {"X-API-Key": TEST_SERVICE_KEY, "X-Frontline-Session": agent_token}
        resp2 = client.get("/api/frontline/hardening/slos", headers=headers)
        assert resp2.status_code == 403
