"""WebSocket contract tests (per blueprint §15.2).

Two layers:
  1. Route + hangup path via FastAPI TestClient (must not hang).
  2. Message schema contract via WebVoiceChannel against a mock socket
     (avoids Starlette TestClient deadlock when the server sends while
     the client is still blocked inside send_json).

Production browsers receive concurrently, so the deadlock is test-only.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.channels.web_voice import WebVoiceChannel
from scripts.seed_domains import build as build_auto


class _MockWS:
    """Async send_json sink used to assert outbound WS message shapes."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(dict(payload))


@pytest.fixture
def api_client(reset_ops_db):
    build_auto("automotive_nhtsa")
    from src.api.routes.interactions import _active
    _active.clear()
    with TestClient(app) as client:
        yield client
    _active.clear()


# ── Route registration + lifecycle (real WS, no multi-message drain) ────────


def test_start_returns_root_ws_url(api_client):
    """POST /api/interactions/start returns blueprint-shaped ws_url."""
    r = api_client.post("/api/interactions/start?channel=web_text")
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["interaction_id"].startswith("int_")
    assert body["ws_url"].startswith("/ws/interaction/")
    assert "/api/interactions/" not in body["ws_url"]
    assert body["greeting_text"]
    assert body["pack"]["id"] == "automotive_nhtsa"


def test_ws_route_accepts_connection_and_hangup(api_client):
    """Root /ws/interaction/{id} accepts a socket; hangup ends the contact."""
    r = api_client.post("/api/interactions/start?channel=web_text")
    iid = r.json()["interaction_id"]
    ws_path = r.json()["ws_url"]
    assert ws_path == f"/ws/interaction/{iid}"

    with api_client.websocket_connect(ws_path) as ws:
        # Hangup alone: server closes the loop without needing client receives
        # of server-pushed agent_turn frames (TestClient deadlock risk).
        ws.send_json({"type": "hangup"})

    r2 = api_client.get(f"/api/interactions/{iid}")
    assert r2.status_code == 200
    assert r2.json()["interaction"]["status"] in ("abandoned", "completed")


def test_ws_barge_in_then_hangup(api_client):
    """barge_in is accepted on the live socket; hangup closes cleanly."""
    r = api_client.post("/api/interactions/start?channel=web_text")
    ws_path = r.json()["ws_url"]
    with api_client.websocket_connect(ws_path) as ws:
        ws.send_json({"type": "barge_in"})
        ws.send_json({"type": "hangup"})


def test_ws_unknown_interaction_closes(api_client):
    """Connecting to a non-active interaction_id returns an error frame."""
    with api_client.websocket_connect("/ws/interaction/int_does_not_exist") as ws:
        msg = ws.receive_json()
        assert msg.get("type") == "error"


# ── Outbound message schema (shipped WebVoiceChannel contract) ─────────────


@pytest.mark.asyncio
async def test_channel_agent_turn_schema():
    mock = _MockWS()
    ch = WebVoiceChannel(mock, text_only=True)
    await ch.send_turn("Hello", speaker="agent", meta={"turn_id": "t1"})
    msg = mock.sent[-1]
    assert msg["type"] == "agent_turn"
    assert msg["text"] == "Hello"
    assert msg["speaker"] == "agent"
    assert msg["turn_id"] == "t1"
    assert msg["speak"] is False  # text_only


@pytest.mark.asyncio
async def test_channel_agent_activity_schema():
    mock = _MockWS()
    ch = WebVoiceChannel(mock)
    await ch.send_activity({
        "agent": "sentinel",
        "action_type": "advisory_check",
        "summary": "matched 19V-12345",
        "evidence_ids": ["19V-12345"],
        "ok": True,
    })
    msg = mock.sent[-1]
    assert msg == {
        "type": "agent_activity",
        "agent": "sentinel",
        "action_type": "advisory_check",
        "summary": "matched 19V-12345",
        "evidence_ids": ["19V-12345"],
        "ok": True,
    }


@pytest.mark.asyncio
async def test_channel_slots_update_schema():
    mock = _MockWS()
    ch = WebVoiceChannel(mock)
    await ch.send_slots_update({
        "entity_1": "2019",
        "entity_2": "HONDA",
        "__internal__": "x",
    })
    msg = mock.sent[-1]
    assert msg["type"] == "slots_update"
    assert msg["slots"] == {"entity_1": "2019", "entity_2": "HONDA"}
    assert "__internal__" not in msg["slots"]


@pytest.mark.asyncio
async def test_channel_handoff_and_ended_schema():
    mock = _MockWS()
    ch = WebVoiceChannel(mock)
    await ch.send_handoff_offer()
    assert mock.sent[-1] == {"type": "handoff_offer"}
    await ch.send_interaction_ended({
        "case_id": "case_1",
        "investigation_id": "inv_0001",
        "investigation_opened": True,
        "audit_pending": True,
    })
    ended = mock.sent[-1]
    assert ended["type"] == "interaction_ended"
    assert ended["case_id"] == "case_1"
    assert ended["investigation_id"] == "inv_0001"
    assert ended["investigation_opened"] is True
    assert ended["audit_pending"] is True
