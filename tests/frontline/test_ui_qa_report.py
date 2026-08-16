"""Gate: full UI QA audit report exists and covers every primary nav route.

Drives the shipped markdown report in docs/ (not a reimplementation of the UI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "docs" / "ui_qa_audit_2026-07-31.md"

REQUIRED_ROUTES = (
    "command",
    "call",
    "console",
    "cases",
    "insights",
    "warning",
    "studio",
    "enterprise",
    "audits",
    "platform",
    "settings",
)


def test_ui_qa_report_exists() -> None:
    assert REPORT.is_file(), f"missing QA report: {REPORT}"


def test_ui_qa_report_covers_all_nav_routes() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "Severity summary" in text
    assert "light" in text.lower() and "dark" in text.lower()
    for route in REQUIRED_ROUTES:
        # Each route appears as #route anchor and in coverage table
        assert f"#{route}" in text or f"`#{route}`" in text, f"route #{route} not documented"
        assert route in text, f"route id {route} missing from report"


def test_ui_qa_report_has_defects_with_severity_and_fix() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "Fix recommendation" in text
    assert "**Major**" in text or "| Major" in text
    # At least the known high-signal issues from the audit
    assert "pending_followup" in text
    assert "Platform OS" in text or "platform" in text
    assert "FRONTLINE_API_KEY" in text or "API key" in text
    assert "panel-2" in text or "#1a1f2e" in text


def test_app_nav_ids_match_report_scope() -> None:
    """Report scope must match the real App.jsx nav ids (shipped entry)."""
    app = (REPO / "dashboard" / "src" / "App.jsx").read_text(encoding="utf-8")
    for route in REQUIRED_ROUTES:
        assert f'id: "{route}"' in app, f"App.jsx missing nav id {route}"
