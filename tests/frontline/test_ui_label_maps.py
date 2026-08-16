"""Tests for shipped ops-console display label maps (QA audit fixes).

Drives dashboard/scripts/assert-qa-labels.mjs which imports the real labels.js
module and asserts retired defect strings are gone from source.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DASH = REPO / "dashboard"
ASSERT = DASH / "scripts" / "assert-qa-labels.mjs"


def test_assert_qa_labels_script_passes() -> None:
    assert ASSERT.is_file(), f"missing {ASSERT}"
    r = subprocess.run(
        ["node", str(ASSERT)],
        cwd=DASH,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, f"assert-qa-labels failed:\n{r.stdout}\n{r.stderr}"
    assert "assert-qa-labels: PASSED" in r.stdout
    assert "Pending follow-up" in r.stdout
    assert "Open" in r.stdout


def test_case_queue_wires_status_label() -> None:
    src = (DASH / "routes" / "CaseQueue.jsx").read_text(encoding="utf-8")
    assert "statusLabel" in src
    assert "statusLabel(s)" in src


def test_platform_os_wires_proposal_helpers() -> None:
    src = (DASH / "routes" / "PlatformOS.jsx").read_text(encoding="utf-8")
    assert "proposalTitle" in src
    assert "proposalDetailParts" in src
    assert "weaknessLabel" in src


def test_enterprise_no_dark_timeline_fallback() -> None:
    src = (DASH / "routes" / "EnterpriseOps.jsx").read_text(encoding="utf-8")
    assert "#1a1f2e" not in src
    assert "panel-2" not in src


def test_settings_and_shell_defect_strings_gone() -> None:
    settings = (DASH / "routes" / "Settings.jsx").read_text(encoding="utf-8")
    app = (DASH / "src" / "App.jsx").read_text(encoding="utf-8")
    cc = (DASH / "routes" / "CommandCenter.jsx").read_text(encoding="utf-8")
    assert 'placeholder="FRONTLINE_API_KEY"' not in settings
    assert "Paste pilot API key" in settings
    assert "hooks.example.com/frontline" not in settings
    assert "fill wallboard" not in app
    assert "Health re-checked" not in app
    assert "Could not load wallboard" not in cc
