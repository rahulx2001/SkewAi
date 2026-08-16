"""Single-tenant API-key gate tests (pilot kit).

Drives the real FastAPI app via TestClient — not a re-implemented gate.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.setenv("FRONTLINE_API_KEY", "pilot-secret-test")
    with TestClient(app) as c:
        yield c
    # ensure open mode for other tests
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


@pytest.fixture
def open_client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


def test_start_rejects_without_key(client):
    r = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r.status_code == 401
    assert "API key" in r.json()["detail"]


def test_start_accepts_x_api_key(client):
    r = client.post(
        "/api/interactions/start",
        params={"channel": "web_text"},
        headers={"X-API-Key": "pilot-secret-test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["interaction_id"].startswith("int_")
    assert body["ws_url"].startswith("/ws/interaction/")


def test_start_accepts_bearer(client):
    r = client.post(
        "/api/interactions/start",
        params={"channel": "web_text"},
        headers={"Authorization": "Bearer pilot-secret-test"},
    )
    assert r.status_code == 200


def test_start_rejects_wrong_key(client):
    r = client.post(
        "/api/interactions/start",
        params={"channel": "web_text"},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 401


def test_simulate_requires_key(client):
    r = client.post("/api/frontline/simulate", params={"count": 1})
    assert r.status_code == 401
    r2 = client.post(
        "/api/frontline/simulate",
        params={"count": 1},
        headers={"X-API-Key": "pilot-secret-test"},
    )
    assert r2.status_code == 200


def test_takeover_requires_key(client):
    started = client.post(
        "/api/interactions/start",
        params={"channel": "web_text"},
        headers={"X-API-Key": "pilot-secret-test"},
    ).json()
    iid = started["interaction_id"]
    r = client.post(f"/api/interactions/{iid}/takeover")
    assert r.status_code == 401
    r2 = client.post(
        f"/api/interactions/{iid}/takeover",
        headers={"X-API-Key": "pilot-secret-test"},
    )
    assert r2.status_code == 200
    assert r2.json()["supervised"] is True


def test_health_public_even_with_key(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json().get("auth_required") is True


def test_open_mode_without_env(open_client):
    """When FRONTLINE_API_KEY is unset, write routes stay open for local/dev."""
    r = open_client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r.status_code == 200
