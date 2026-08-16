"""C2: PII read routes require FRONTLINE_API_KEY when configured."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.domains.active_pack import clear_active_pack_override

KEY = "pilot-read-secret"
HDR = {"X-API-Key": KEY}


@pytest.fixture
def locked(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.setenv("FRONTLINE_API_KEY", KEY)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    clear_active_pack_override()
    with TestClient(app) as c:
        yield c
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


@pytest.fixture
def open_mode(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    clear_active_pack_override()
    with TestClient(app) as c:
        yield c


READ_PATHS = [
    "/api/interactions",
    "/api/frontline/cases",
    "/api/frontline/audits",
    "/api/frontline/digest",
    "/api/frontline/early-warning",
    "/api/frontline/investigations",
]


@pytest.mark.parametrize("path", READ_PATHS)
def test_read_routes_reject_without_key(locked, path):
    r = locked.get(path)
    assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


@pytest.mark.parametrize("path", READ_PATHS)
def test_read_routes_accept_with_key(locked, path):
    r = locked.get(path, headers=HDR)
    # 200 with body, or empty list — never 401 when key is valid
    assert r.status_code == 200, f"{path} expected 200, got {r.status_code}: {r.text[:200]}"


def test_get_interaction_detail_requires_key(locked):
    started = locked.post(
        "/api/interactions/start",
        params={"channel": "web_text"},
        headers=HDR,
    )
    assert started.status_code == 200
    iid = started.json()["interaction_id"]

    assert locked.get(f"/api/interactions/{iid}").status_code == 401
    # May 200 or 404 depending on audit helpers after hangup; not 401 with key
    r = locked.get(f"/api/interactions/{iid}", headers=HDR)
    assert r.status_code in (200, 404)


def test_digest_regenerate_requires_key(locked):
    r = locked.get("/api/frontline/digest", params={"regenerate": "true"})
    assert r.status_code == 401
    r2 = locked.get(
        "/api/frontline/digest",
        params={"regenerate": "true"},
        headers=HDR,
    )
    assert r2.status_code == 200


def test_open_mode_reads_without_key(open_mode):
    r = open_mode.get("/api/interactions")
    assert r.status_code == 200
