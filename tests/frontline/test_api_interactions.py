"""REST API smoke tests (per blueprint §15.2).

Covers the four required endpoints using FastAPI's TestClient (httpx-backed):
  - POST /api/interactions/start
  - GET  /api/interactions
  - GET  /api/frontline/audits
  - GET  /api/packs

These tests exercise the API layer end-to-end (in-process, no uvicorn).
The ops warehouse is reset between tests so each test sees a clean slate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack):
    """A TestClient bound to the FastAPI app. The warehouse is reset before each
    test so the interactions table starts empty."""
    with TestClient(app) as c:
        yield c


# ── POST /api/interactions/start ─────────────────────────────────────────────


def test_start_interaction_returns_greeting_and_ws_url(client):
    resp = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert resp.status_code == 200
    body = resp.json()
    assert "interaction_id" in body
    assert body["interaction_id"].startswith("int_")
    assert body["ws_url"].startswith("/ws/interaction/")
    assert body["greeting_text"]  # non-empty
    assert body["pack"]["id"] == "automotive_nhtsa"
    assert body["pack"]["pack_version"]  # 12-char hex


def test_start_interaction_persists_to_warehouse(client):
    resp = client.post("/api/interactions/start", params={"channel": "web_text"})
    iid = resp.json()["interaction_id"]
    # The interaction row exists in the ops warehouse.
    from src.data.warehouse import ops_con

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status, channel FROM interactions WHERE interaction_id = ?",
            [iid],
        ).fetchone()
    assert row is not None
    assert row[0] == "active"
    assert row[1] == "web_text"


# ── GET /api/interactions ────────────────────────────────────────────────────


def test_list_interactions_empty(client):
    """With a freshly reset warehouse, the list is empty."""
    resp = client.get("/api/interactions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["interactions"] == []


def test_list_interactions_after_start(client):
    """After starting an interaction, it appears in the list."""
    client.post("/api/interactions/start", params={"channel": "web_text"})
    resp = client.get("/api/interactions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["interactions"][0]["status"] == "active"


def test_list_interactions_filter_by_status(client):
    """The status filter works."""
    client.post("/api/interactions/start", params={"channel": "web_text"})
    resp = client.get("/api/interactions", params={"status": "completed"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0  # the started interaction is 'active', not 'completed'


# ── GET /api/frontline/audits ─────────────────────────────────────────────────


def test_list_audits_returns_list(client):
    """GET /api/frontline/audits returns a list (possibly empty).

    Other tests in the suite may have written audit reports to disk, so we
    don't assert count == 0 — we just verify the endpoint returns 200 and the
    right shape.
    """
    resp = client.get("/api/frontline/audits")
    assert resp.status_code == 200
    body = resp.json()
    assert "audits" in body
    assert "count" in body
    assert isinstance(body["audits"], list)
    assert body["count"] == len(body["audits"])


# ── GET /api/packs ────────────────────────────────────────────────────────────


def test_list_packs_includes_automotive(client):
    resp = client.get("/api/packs")
    assert resp.status_code == 200
    body = resp.json()
    pack_ids = [p["id"] for p in body["packs"]]
    assert "automotive_nhtsa" in pack_ids
    # automotive pack must lint clean.
    auto = next(p for p in body["packs"] if p["id"] == "automotive_nhtsa")
    assert auto["lint_errors"] == []
    assert auto["pack_version"]
    assert "entity_1" in auto["entity_labels"]


def test_get_single_pack(client):
    resp = client.get("/api/packs/automotive_nhtsa")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "automotive_nhtsa"
    assert "manifest" in body
    assert "slot_frame" in body["manifest"]


def test_get_pack_unknown_returns_404(client):
    resp = client.get("/api/packs/does_not_exist")
    assert resp.status_code == 404


# ── Health check ─────────────────────────────────────────────────────────────


def test_health(client):
    from src.domains.active_pack import clear_active_pack_override, resolve_active_pack_id

    clear_active_pack_override()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["active_pack"] == resolve_active_pack_id()
    assert body["llm_available"] is False
    assert "frontline_enabled" in body
