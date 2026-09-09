"""Deep health, CORS env, report rotation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, _cors_origins
from src.qubot.report_rotation import rotate_reports


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    with TestClient(app) as c:
        yield c


def test_early_warning_defaults_exclude_simulated(client):
    r = client.get("/api/frontline/early-warning")
    assert r.status_code == 200
    funnel = r.json()["funnel"]
    assert funnel.get("include_simulated") is False


def test_include_simulated_funnel_and_cases_contract(client):
    off = client.get("/api/frontline/early-warning?include_simulated=false")
    on = client.get("/api/frontline/early-warning?include_simulated=true")
    assert off.status_code == 200
    assert on.status_code == 200
    assert off.json()["funnel"]["include_simulated"] is False
    assert on.json()["funnel"]["include_simulated"] is True
    cases_off = client.get("/api/frontline/cases?limit=5")
    cases_on = client.get("/api/frontline/cases?limit=5&include_simulated=true")
    assert cases_off.status_code == 200
    assert cases_on.status_code == 200
    assert "pagination" in cases_off.json()


def test_wallboard_field_contract(client):
    r = client.get("/api/frontline/wallboard")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "active_contacts",
        "open_cases",
        "p1_open",
        "critical_open",
        "top_risk_clusters",
        "live_contacts",
    ):
        assert key in body, key
    assert isinstance(body["live_contacts"], list)
    assert isinstance(body["top_risk_clusters"], list)


def test_ui_index_serves_html_body(client):
    r = client.get("/ui/")
    assert r.status_code == 200
    assert len(r.content) > 200
    assert b"root" in r.content


def test_health_reports_db_and_pack(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "db_ok" in body
    assert "pack_ok" in body
    assert body["db_ok"] is True
    assert body["pack_ok"] is True
    assert body["active_pack"]


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.example,https://b.example")
    origins = _cors_origins()
    assert origins == ["https://a.example", "https://b.example"]
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    defaults = _cors_origins()
    assert any("127.0.0.1" in o or "localhost" in o for o in defaults)


def test_report_rotation_deletes_excess(tmp_path):
    reports = tmp_path / "contacts"
    digests = tmp_path / "digests"
    reports.mkdir()
    digests.mkdir()
    for i in range(10):
        p = reports / f"int_{i}.md"
        p.write_text("x", encoding="utf-8")
        # stagger mtimes slightly via write order
    out = rotate_reports(
        reports_dir=reports,
        digests_dir=digests,
        max_files=3,
        max_age_days=3650,
    )
    assert out["deleted"] >= 7
    left = list(reports.glob("*.md"))
    assert len(left) <= 3
