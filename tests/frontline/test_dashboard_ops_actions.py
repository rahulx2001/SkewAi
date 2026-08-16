"""Structural tests for ops deep-links + greeting path + palette power moves."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DASH = REPO / "dashboard"


def test_ops_actions_module_exports():
    src = (DASH / "src" / "ui" / "opsActions.js").read_text(encoding="utf-8")
    assert "export async function simulateTraffic" in src
    assert "export function openCases" in src
    assert "export function openConsole" in src
    assert "frontline:case_filter_sev" in src


def test_app_palette_has_ops_power_moves():
    app = (DASH / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "act-simulate-15" in app
    assert "act-p1-queue" in app
    assert "simulateTraffic" in app
    assert "openCases" in app


def test_command_center_deep_links():
    cc = (DASH / "routes" / "CommandCenter.jsx").read_text(encoding="utf-8")
    assert "openConsole" in cc
    assert "openCases" in cc
    assert "simulateTraffic" in cc
    assert "live-row-btn" in cc
    assert "fetchOpenP1Cases" in cc


def test_case_queue_consumes_session_filters():
    cq = (DASH / "routes" / "CaseQueue.jsx").read_text(encoding="utf-8")
    assert "consumeSession" in cq
    assert "SS.caseSev" in cq
    assert "SS.caseSelect" in cq


def test_console_consumes_preselect():
    lc = (DASH / "routes" / "LiveContactConsole.jsx").read_text(encoding="utf-8")
    assert "SS.consoleSelect" in lc
    assert "consumeSession" in lc


def test_voice_greeting_phase_no_barge():
    cw = (DASH / "routes" / "CallWidget.jsx").read_text(encoding="utf-8")
    assert 'phase: "greeting"' in cw
    assert "greetingSpeakText" in cw
    h = (DASH / "src" / "voiceHelpers.js").read_text(encoding="utf-8")
    assert "shouldAllowBargeIn" in h
    assert 'phase === "greeting"' in h
