"""Voice agent WS reconnect: a dropped socket must stay resumable.

Regression for the console banner "active interaction not found: int_...".
The widget reconnects with backoff after any unexpected close, but the server
used to unregister the orchestrator in the WS `finally`, so every reconnect
404'd and the call was unrecoverable.
"""

from __future__ import annotations

import asyncio
import time

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


def _start(client) -> tuple[str, str]:
    r = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert r.status_code == 200
    body = r.json()
    return body["interaction_id"], body["ws_url"]


def test_dropped_ws_stays_registered_for_reconnect(client):
    """Close without hangup → entry survives, marked detached (not reaped)."""
    iid, ws_path = _start(client)
    with client.websocket_connect(ws_path):
        assert ir._active[iid].ws_attached is True

    assert iid in ir._active, "dropped socket must not tear down the contact"
    entry = ir._active[iid]
    assert entry.ws_attached is False
    assert entry.detached_at is not None


def test_reconnect_resumes_same_contact_with_transcript(client):
    """Re-attach returns a `resumed` frame with the server-side transcript + slots."""
    iid, ws_path = _start(client)
    with client.websocket_connect(ws_path) as ws:
        ws.send_json(
            {"type": "user_turn", "text": "My 2019 Honda CR-V grinds when I brake", "final": True}
        )

    with client.websocket_connect(ws_path) as ws2:
        resumed = ws2.receive_json()
        assert resumed["type"] == "resumed"
        assert resumed["interaction_id"] == iid
        assert len(resumed["turns"]) >= 2
        assert any(t["speaker"] == "customer" for t in resumed["turns"])

        slots = ws2.receive_json()
        assert slots["type"] == "slots_update"
        assert slots["slots"].get("entity_2") == "HONDA"

        ws2.send_json({"type": "hangup"})

    assert iid not in ir._active
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status FROM interactions WHERE interaction_id = ?", [iid]
        ).fetchone()
    assert row[0] != "active"


def test_explicit_hangup_still_unregisters(client):
    """A real hangup must not linger in the reconnect window."""
    iid, ws_path = _start(client)
    with client.websocket_connect(ws_path) as ws:
        ws.send_json({"type": "hangup"})
    assert iid not in ir._active


def test_second_concurrent_ws_still_rejected(client):
    """Reconnect support must not weaken the exclusive-attach guarantee."""
    iid, ws_path = _start(client)
    with client.websocket_connect(ws_path) as ws1:
        with client.websocket_connect(ws_path) as ws2:
            msg = ws2.receive_json()
            assert msg["type"] == "error"
            assert msg["code"] == "interaction_busy"
            assert msg["recoverable"] is False
        ws1.send_json({"type": "hangup"})


def test_detached_contact_reaped_after_grace(client):
    """A client that never comes back is finalized, not left status='active'."""
    iid, ws_path = _start(client)
    with client.websocket_connect(ws_path):
        pass
    assert iid in ir._active

    ir._active[iid].detached_at = time.monotonic() - (ir._reconnect_grace_s() + 10)
    reaped = asyncio.run(ir.reap_orphans())
    assert iid in reaped
    assert iid not in ir._active

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status FROM interactions WHERE interaction_id = ?", [iid]
        ).fetchone()
    assert row is not None
    assert row[0] != "active"


def test_reconnect_after_grace_is_flagged_unrecoverable(client):
    """Past the grace the error frame tells the widget to stop retrying."""
    iid, ws_path = _start(client)
    with client.websocket_connect(ws_path):
        pass
    ir._active[iid].detached_at = time.monotonic() - (ir._reconnect_grace_s() + 10)

    with client.websocket_connect(ws_path) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "interaction_not_resumable"
        assert msg["recoverable"] is False


def test_grace_is_env_configurable(monkeypatch):
    monkeypatch.setenv("FRONTLINE_WS_RECONNECT_GRACE_S", "5")
    assert ir._reconnect_grace_s() == 5.0
    monkeypatch.setenv("FRONTLINE_WS_RECONNECT_GRACE_S", "not-a-number")
    assert ir._reconnect_grace_s() == 120.0
    monkeypatch.delenv("FRONTLINE_WS_RECONNECT_GRACE_S")
    assert ir._reconnect_grace_s() == 120.0


def test_never_attached_entry_uses_orphan_ttl_not_grace(client):
    """start-without-WS keeps the longer 5-minute TTL (unchanged behaviour)."""
    iid, _ = _start(client)
    entry = ir._active[iid]
    assert entry.detached_at is None

    now = time.monotonic()
    grace = ir._reconnect_grace_s()
    entry.created_at = now - (grace + 10)
    assert ir._is_reapable(entry, now, grace) is False

    entry.created_at = now - (ir._ORPHAN_TTL_S + 10)
    assert ir._is_reapable(entry, now, grace) is True
