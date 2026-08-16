"""Pilot-ops polish: dead-letter UI wiring, WS reconnect, single-worker health."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "dashboard"
SETTINGS = DASH / "routes" / "Settings.jsx"
LIVE = DASH / "routes" / "LiveContactConsole.jsx"
CALL = DASH / "routes" / "CallWidget.jsx"


def test_settings_dead_letter_ui_wires_real_api():
    src = SETTINGS.read_text(encoding="utf-8")
    assert "/api/frontline/alerts/dead-letter" in src
    assert "replay" in src
    assert "apiHeaders" in src or "X-API-Key" in src
    assert "dead-letter" in src
    # Must hit list and replay endpoints
    assert "status=pending" in src or "dead-letter?status" in src
    assert "/replay" in src


def test_live_console_reconnect_on_close():
    src = LIVE.read_text(encoding="utf-8")
    assert "reconnecting" in src
    assert "setTimeout" in src or "retryTimer" in src
    assert "onclose" in src
    assert "connect()" in src or "function connect" in src
    # backoff / attempt limit present
    assert "attempt" in src or "maxAttempts" in src


def test_callwidget_reconnect_on_unexpected_close():
    src = CALL.read_text(encoding="utf-8")
    assert "reconnecting" in src
    assert "intentionalClose" in src or "intentionalCloseRef" in src
    assert "reconnect" in src.lower()
    assert "wsStatus" in src
    # Unmount must arm intentional close + clear reconnect timer (no ghost reconnects)
    assert "intentionalCloseRef.current = true" in src
    assert "clearTimeout(reconnectTimerRef" in src or "clearTimeout(reconnectTimerRef.current)" in src
    # Unmount cleanup sets intentional close before ws.close
    unmount_idx = src.find("Cleanup on unmount")
    assert unmount_idx > 0
    unmount_block = src[unmount_idx : unmount_idx + 600]
    # Either inline flags or markCallTerminal() which sets them
    assert (
        "intentionalCloseRef.current = true" in unmount_block
        or "markCallTerminal()" in unmount_block
    )
    assert (
        "activeWsUrlRef.current = null" in unmount_block
        or "markCallTerminal()" in unmount_block
    )
    assert "clearTimeout" in unmount_block or "markCallTerminal()" in unmount_block
    # Normal interaction_ended must not reconnect / wipe case summary
    ended_idx = src.find('case "interaction_ended"')
    assert ended_idx > 0
    ended_block = src[ended_idx : ended_idx + 500]
    assert "markCallTerminal()" in ended_block
    assert "mapInteractionEnded" in ended_block


def test_health_reports_single_worker(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("single_worker") is True
    assert body.get("orchestrator_registry") == "in_process"
