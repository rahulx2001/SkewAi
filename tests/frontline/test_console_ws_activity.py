"""C1: Live console agent_activity frames are JSON-safe (datetime → isoformat)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.interactions import (
    activity_frame_from_row,
    fetch_agent_actions_since,
    _json_safe,
)
from src.data.warehouse import ops_con
from src.domains.active_pack import clear_active_pack_override
from src.ledger.writer import AgentAction, record_action


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    clear_active_pack_override()
    with TestClient(app) as c:
        yield c


def test_json_safe_datetime_is_isoformat():
    ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    # Wire form is ISO-8601 UTC with trailing Z (audit C-2).
    assert _json_safe(ts) == "2026-01-02T03:04:05Z"
    json.dumps({"ts": _json_safe(ts), "type": "agent_activity"})


def test_activity_frame_from_duckdb_row_is_json_serializable(client):
    """Drive the same fetch + frame path the console WS uses after a real ledger write."""
    started = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert started.status_code == 200
    iid = started.json()["interaction_id"]

    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="state_transition",
            input_summary="console traffic test",
            output_summary="hello console tick",
            evidence_ids=["ev_1"],
            ok=True,
        )
    )

    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT action_id, interaction_id, agent, action_type,
                   output_summary, evidence_ids, ts
            FROM agent_actions
            WHERE interaction_id = ? AND output_summary = 'hello console tick'
            ORDER BY ts DESC LIMIT 1
            """,
            [iid],
        ).fetchone()
        cols = [d[0] for d in con.description]
    assert row is not None
    raw = dict(zip(cols, row))
    assert isinstance(raw["ts"], datetime), "DuckDB must return datetime (the bug source)"

    frame = activity_frame_from_row(raw)
    assert frame["type"] == "agent_activity"
    assert frame["interaction_id"] == iid
    assert frame["action_type"] == "state_transition"
    assert isinstance(frame["ts"], str)
    # The exact call that used to raise TypeError and kill the console socket
    json.dumps(frame)

    # Also via shipped fetch helper (console loop path)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = fetch_agent_actions_since(since, limit=50)
    match = [r for r in rows if r.get("output_summary") == "hello console tick"]
    assert match
    assert isinstance(match[0]["ts"], datetime)
    json.dumps(activity_frame_from_row(match[0]))


def test_console_ws_delivers_activity_frame(client):
    """Connect real /ws/console after ledger activity; receive one agent_activity."""
    started = client.post("/api/interactions/start", params={"channel": "web_text"})
    assert started.status_code == 200
    iid = started.json()["interaction_id"]
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="state_transition",
            output_summary="live frame console ws",
            ok=True,
        )
    )

    with client.websocket_connect("/ws/console") as ws:
        # Server polls and send_json's activity first (lookback 1h), then waits.
        # Bound receives so a missing frame cannot hang the suite forever.
        frames: list[dict] = []
        for _ in range(8):
            try:
                frames.append(ws.receive_json(mode="text", timeout=2.0))
            except TypeError:
                # Starlette TestClient: timeout via receive with deadline
                try:
                    frames.append(ws.receive_json())
                except Exception:
                    break
            except Exception:
                break
            if any(f.get("output_summary") == "live frame console ws" for f in frames):
                break

    activity = next((f for f in frames if f.get("type") == "agent_activity"), None)
    assert activity is not None, f"no agent_activity in {frames!r}"
    assert isinstance(activity.get("ts"), str)
    # live frame present if lookback worked
    live = [f for f in frames if f.get("output_summary") == "live frame console ws"]
    assert live, f"expected live frame console ws, got {frames!r}"
    assert live[0]["interaction_id"] == iid
