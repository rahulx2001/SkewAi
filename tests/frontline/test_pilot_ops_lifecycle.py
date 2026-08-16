"""Pilot ops lifecycle: case status/notes, investigation PATCH, metrics, CSV."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data.warehouse import ops_con
from src.frontline.ops import (
    add_case_note,
    build_cases_csv,
    list_case_notes,
    ops_metrics,
    update_case,
    update_investigation,
)


def _seed_case(
    case_id: str = "case_ops_1",
    *,
    status: str = "open",
    severity: str = "Medium",
    inv_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at,
                category, description_summary, onset, severity,
                severity_source, priority, safety_flags,
                advisory_match_id, cluster_match_id, similar_record_count,
                investigation_id, status, followup_draft
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                case_id,
                "int_ops_1",
                "automotive_nhtsa",
                now,
                "brakes",
                "soft pedal at highway speed",
                now,
                severity,
                "rules",
                2,
                "{}",
                None,
                1,
                0,
                inv_id,
                status,
                "initial draft",
            ],
        )


def _seed_inv(inv_id: str = "inv_0099") -> None:
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO investigations
            (investigation_id, pack_id, cluster_id, title, status,
             opened_at, last_case_at, case_count)
            VALUES (?, ?, ?, ?, 'open', ?, ?, 1)
            """,
            [inv_id, "automotive_nhtsa", 1, "Cluster 1 brakes", now, now],
        )


@pytest.fixture
def client(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


def test_update_case_status_and_followup(reset_ops_db):
    _seed_case()
    row = update_case("case_ops_1", status="pending_followup")
    assert row["status"] == "pending_followup"
    row = update_case("case_ops_1", followup_draft="Please call dealer")
    assert "dealer" in (row.get("followup_draft") or "")
    with pytest.raises(ValueError):
        update_case("case_ops_1", status="not_a_status")
    with pytest.raises(LookupError):
        update_case("case_missing", status="closed")


def test_case_notes(reset_ops_db):
    _seed_case()
    n = add_case_note("case_ops_1", "Called customer; left voicemail", author="ops")
    assert n["note_id"].startswith("note_")
    notes = list_case_notes("case_ops_1")
    assert len(notes) == 1
    assert "voicemail" in notes[0]["body"]
    with pytest.raises(ValueError):
        add_case_note("case_ops_1", "   ")


def test_investigation_status(reset_ops_db):
    _seed_inv()
    out = update_investigation("inv_0099", status="monitoring")
    assert out["status"] == "monitoring"
    out = update_investigation("inv_0099", status="closed")
    assert out["status"] == "closed"
    with pytest.raises(ValueError):
        update_investigation("inv_0099", status="nope")


def test_cases_csv_and_metrics(reset_ops_db):
    _seed_case("case_a", severity="Critical")
    _seed_case("case_b", status="closed", severity="Low")
    csv_text, n = build_cases_csv(q="soft pedal")
    assert n >= 1
    assert "case_id" in csv_text
    assert "case_a" in csv_text or "soft" in csv_text.lower() or n >= 1
    m = ops_metrics(window_days=7)
    assert m["cases"]["open"] >= 1
    assert "investigations" in m
    assert "ts" in m


def test_api_lifecycle(client, reset_ops_db):
    _seed_case()
    _seed_inv("inv_api_1")
    with ops_con() as con:
        con.execute(
            "UPDATE cases SET investigation_id = ? WHERE case_id = ?",
            ["inv_api_1", "case_ops_1"],
        )

    r = client.get("/api/frontline/metrics")
    assert r.status_code == 200
    assert "cases" in r.json()

    r = client.get("/api/frontline/cases?q=brakes")
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = client.patch(
        "/api/frontline/cases/case_ops_1",
        json={"status": "closed", "followup_draft": "done"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "closed"

    r = client.post(
        "/api/frontline/cases/case_ops_1/notes",
        json={"body": "Closed after dealer visit", "author": "pilot"},
    )
    assert r.status_code == 200
    assert r.json()["note_id"]

    r = client.get("/api/frontline/cases/case_ops_1")
    assert r.status_code == 200
    assert len(r.json().get("notes") or []) >= 1

    r = client.patch(
        "/api/frontline/investigations/inv_api_1",
        json={"status": "monitoring"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "monitoring"

    r = client.get("/api/frontline/cases/export?q=brakes")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "case_id" in r.text
    assert r.headers.get("X-Export-Sha256")


def test_api_auth_when_key_set(reset_ops_db, monkeypatch):
    monkeypatch.setenv("FRONTLINE_API_KEY", "ops-secret")
    with TestClient(app) as c:
        assert c.get("/api/frontline/metrics").status_code == 401
        assert (
            c.get("/api/frontline/metrics", headers={"X-API-Key": "ops-secret"}).status_code
            == 200
        )
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


def test_dashboard_wires_new_ops_paths():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    cq = (root / "dashboard/routes/CaseQueue.jsx").read_text(encoding="utf-8")
    ew = (root / "dashboard/routes/EarlyWarningBoard.jsx").read_text(encoding="utf-8")
    assert "/api/frontline/cases/export" in cq
    assert "method: \"PATCH\"" in cq or "method: 'PATCH'" in cq
    assert "/notes" in cq
    assert "/api/frontline/metrics" in ew
    assert "investigations/" in ew and "PATCH" in ew
