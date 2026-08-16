"""FRONTLINE_ENABLED must gate the API surface (not be a no-op).

Covers HTTP ``/api/*`` and WebSocket ``/ws/*`` — BaseHTTPMiddleware alone
cannot gate WebSockets; the pure ASGI middleware + handler checks must.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.main import app
from src.domains.active_pack import clear_active_pack_override


@pytest.fixture
def enabled_client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    clear_active_pack_override()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def disabled_client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.setenv("FRONTLINE_ENABLED", "0")
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    clear_active_pack_override()
    with TestClient(app) as c:
        yield c


def test_disabled_rejects_api_but_health_stays_up(disabled_client):
    h = disabled_client.get("/health")
    assert h.status_code == 200
    body = h.json()
    assert body["status"] == "ok"
    assert body["frontline_enabled"] is False

    r = disabled_client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()

    packs = disabled_client.get("/api/packs")
    assert packs.status_code == 503


def test_disabled_refuses_console_websocket(disabled_client):
    """FRONTLINE_ENABLED=0 must refuse /ws/console before accept."""
    opened = False
    with pytest.raises((WebSocketDisconnect, RuntimeError)) as ei:
        with disabled_client.websocket_connect("/ws/console") as ws:
            opened = True
            ws.receive_json()
    assert opened is False  # never entered the live connection body
    assert ei.type in (WebSocketDisconnect, RuntimeError)


def test_disabled_refuses_interaction_websocket(disabled_client):
    """FRONTLINE_ENABLED=0 must refuse /ws/interaction/{id} before accept."""
    opened = False
    with pytest.raises((WebSocketDisconnect, RuntimeError)):
        with disabled_client.websocket_connect("/ws/interaction/int_fake_disabled") as ws:
            opened = True
            ws.send_json({"type": "hangup"})
    assert opened is False


def test_enabled_allows_console_websocket_accept(enabled_client):
    """When enabled, console WS accepts (then we hang up)."""
    with enabled_client.websocket_connect("/ws/console") as ws:
        # Connection established — send nothing critical; close cleanly.
        assert ws is not None


def test_enabled_allows_start(enabled_client):
    h = enabled_client.get("/health")
    assert h.status_code == 200
    assert h.json()["frontline_enabled"] is True
    r = enabled_client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r.status_code == 200
