"""H1 crash cleanup + H2 exclusive attach / orphan reaper."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import interactions as ir
from src.data.warehouse import ops_con
from src.domains.active_pack import clear_active_pack_override


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    clear_active_pack_override()
    ir._active.clear()
    with TestClient(app) as c:
        yield c
    ir._active.clear()


def test_second_customer_ws_rejected(client):
    """H2: second WebSocket to same interaction_id does not silently hijack."""
    started = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert started.status_code == 200
    ws_path = started.json()["ws_url"]

    with client.websocket_connect(ws_path) as ws1:
        with client.websocket_connect(ws_path) as ws2:
            msg = ws2.receive_json()
            assert msg.get("type") == "error"
            detail = (msg.get("detail") or "").lower()
            assert "already" in detail or "active" in detail
        ws1.send_json({"type": "hangup"})


def test_orphan_reaper_clears_registry(client):
    """H2: start-without-WS entries past TTL are reaped."""
    started = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert started.status_code == 200
    iid = started.json()["interaction_id"]
    assert iid in ir._active
    assert ir._active[iid].ws_attached is False

    ir._active[iid].created_at = time.monotonic() - (ir._ORPHAN_TTL_S + 10)
    reaped = asyncio.run(ir.reap_orphans())
    assert iid in reaped
    assert iid not in ir._active

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status FROM interactions WHERE interaction_id = ?", [iid]
        ).fetchone()
    assert row is not None
    assert row[0] != "active"
    assert row[0] in ("failed", "abandoned", "completed")


def test_ws_turn_exception_not_left_active(client):
    """H1: exception during turn path finalizes out of permanent active."""
    started = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert started.status_code == 200
    body = started.json()
    iid = body["interaction_id"]
    ws_path = body["ws_url"]

    async def boom(*args, **kwargs):
        raise RuntimeError("forced_turn_failure")

    with patch(
        "src.agents.orchestrator.Orchestrator.handle_customer_turn",
        new=boom,
    ):
        with client.websocket_connect(ws_path) as ws:
            ws.send_json({"type": "user_turn", "text": "hello", "final": True})
            try:
                ws.receive_json()
            except Exception:
                pass

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status FROM interactions WHERE interaction_id = ?", [iid]
        ).fetchone()
    assert row is not None
    assert row[0] != "active", f"interaction left zombie-active: {row[0]}"
    assert row[0] in ("failed", "abandoned", "completed", "escalated")
