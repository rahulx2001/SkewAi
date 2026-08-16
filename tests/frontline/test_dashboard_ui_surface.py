"""Structural checks: dashboard product UI (not JSON dumps) + voice surface."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DASH = REPO / "dashboard"
ROUTES = DASH / "routes"
SRC = DASH / "src"


def _route_files() -> list[Path]:
    return sorted(ROUTES.glob("*.jsx"))


def test_no_primary_json_stringify_dumps_in_routes():
    """Primary views must not use JSON.stringify(..., null, 2) as display UI."""
    offenders = []
    for p in _route_files():
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "JSON.stringify" not in line:
                continue
            # Allow request bodies, WS frames, and download/export blobs.
            if any(
                tok in line
                for tok in (
                    "body:",
                    "body =",
                    "Blob(",
                    "ws.send",
                    "JSON.stringify(obj)",
                    "JSON.stringify(body",
                    "JSON.stringify(patch",
                    "JSON.stringify({",
                )
            ) and "null, 2" not in line.replace(" ", ""):
                continue
            if re.search(r"JSON\.stringify\([^)]*,\s*null\s*,\s*2\s*\)", line):
                # Export download is OK
                if "Blob" in line or "download" in text[max(0, text.find(line) - 200) : text.find(line) + 80]:
                    continue
                # Detail object stringification for nested summary in table cell is limited
                if "slice(0," in line and "detail" in line:
                    continue
                offenders.append(f"{p.name}:{i}: {line.strip()}")
    assert not offenders, "Primary JSON dumps remain:\n" + "\n".join(offenders)


def test_voice_agent_surface_has_required_affordances():
    """CallWidget ships start/end, transcript, text fallback, slots panel."""
    cw = (ROUTES / "CallWidget.jsx").read_text(encoding="utf-8")
    assert "Start voice call" in cw or "startCall" in cw
    assert "End call" in cw or "endCall" in cw
    assert "transcript" in cw
    assert "submitTextFallback" in cw or "textFallback" in cw
    assert "slots" in cw
    assert "call-stage" in cw or "mic-btn" in cw
    assert "speechRecognition" in cw or "SpeechRecognition" in cw or "getSpeechRecognition" in cw


def test_shell_has_nav_groups_and_no_emoji_nav():
    app = (SRC / "App.jsx").read_text(encoding="utf-8")
    assert "Command center" in app or "command" in app
    assert "Voice agent" in app or "call" in app
    assert "Feature studio" in app or "studio" in app
    # Nav should use Icon components, not emoji labels in NAV
    assert "IconMic" in app or "icons.jsx" in app
    assert "📞" not in app


def test_styles_use_design_tokens_not_google_fonts():
    css = (SRC / "styles.css").read_text(encoding="utf-8")
    assert "--accent" in css
    assert "system-ui" in css
    assert "fonts.googleapis" not in css
    assert "Inter" not in css
    assert "JetBrains" not in css
    # Content visible by default (no global opacity-0 body trap)
    assert not re.search(r"body\s*\{[^}]*opacity:\s*0", css)


def test_feature_studio_has_empty_states_and_tables():
    fs = (ROUTES / "FeatureStudio.jsx").read_text(encoding="utf-8")
    assert "empty-state" in fs or "Empty" in fs
    assert "<table>" in fs
    assert "JSON.stringify(data.forecast" not in fs
    assert "stat-card" in fs or "stat-grid" in fs


def test_built_dist_exists_after_build_or_skip_if_missing():
    """If dist was built in this workspace, index.html must reference hashed assets."""
    dist = DASH / "dist" / "index.html"
    if not dist.is_file():
        pytest.skip("dashboard/dist not built yet")
    html = dist.read_text(encoding="utf-8")
    assert "assets/" in html
    assert "index-" in html
