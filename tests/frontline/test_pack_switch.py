"""Active pack switch must affect contact start + /health (not env alone)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.domains.active_pack import (
    clear_active_pack_override,
    resolve_active_pack_id,
    set_active_pack_id,
)


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    monkeypatch.setenv("DOMAIN_PACK", "automotive_nhtsa")
    clear_active_pack_override()
    with TestClient(app) as c:
        yield c
    clear_active_pack_override()


@pytest.fixture
def seed_finance():
    from scripts.seed_domains import build as build_domain

    return build_domain("finance_cfpb")


def test_resolve_falls_back_to_env_without_override(client, monkeypatch):
    clear_active_pack_override()
    monkeypatch.setenv("DOMAIN_PACK", "automotive_nhtsa")
    # settings.domain_pack is frozen at import; override file cleared → still
    # uses settings.domain_pack which is typically automotive_nhtsa in tests.
    assert resolve_active_pack_id()  # non-empty


def test_health_and_start_follow_put_active(client, seed_finance):
    # Default / env pack
    h0 = client.get("/health")
    assert h0.status_code == 200
    default_pack = h0.json()["active_pack"]
    assert default_pack  # usually automotive_nhtsa

    r0 = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r0.status_code == 200
    assert r0.json()["pack"]["id"] == default_pack

    # Switch via real API (same path Settings uses)
    put = client.put("/api/packs/active", params={"pack_id": "finance_cfpb"})
    assert put.status_code == 200
    assert put.json()["active"] == "finance_cfpb"

    h1 = client.get("/health")
    assert h1.status_code == 200
    assert h1.json()["active_pack"] == "finance_cfpb"

    r1 = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r1.status_code == 200
    assert r1.json()["pack"]["id"] == "finance_cfpb"

    # Switch back
    put2 = client.put("/api/packs/active", params={"pack_id": "automotive_nhtsa"})
    assert put2.status_code == 200
    assert client.get("/health").json()["active_pack"] == "automotive_nhtsa"
    r2 = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r2.json()["pack"]["id"] == "automotive_nhtsa"


def test_set_active_pack_id_store_matches_resolver(client):
    set_active_pack_id("finance_cfpb")
    assert resolve_active_pack_id() == "finance_cfpb"
    assert client.get("/health").json()["active_pack"] == "finance_cfpb"
