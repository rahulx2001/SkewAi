"""Audit export API tests — drive real build_audit_export + HTTP route."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.export import build_audit_export
from src.api.main import app
from src.data.warehouse import ops_con
from src.ledger import AgentAction, record_action


def _seed_interaction(iid: str = "int_export_test_1") -> str:
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, ended_at, channel,
             status, outcome, supervised, peak_frustration)
            VALUES (?, 'automotive_nhtsa', 'testver', ?, ?, 'web_text',
                    'completed', 'case_created', FALSE, 0.1)
            """,
            [iid, now, now],
        )
    record_action(AgentAction(
        interaction_id=iid,
        agent="orchestrator",
        action_type="interaction_started",
        input_summary="seed",
        output_summary="started",
        evidence_ids=["19V-12345"],
    ))
    return iid


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


@pytest.mark.asyncio
async def test_build_audit_export_includes_actions_and_verdict(reset_ops_db, seed_automotive_pack):
    iid = _seed_interaction()
    payload = await build_audit_export(interaction_ids=[iid], run_auditor=True)
    assert payload["count"] == 1
    row = payload["interactions"][0]
    assert row["interaction_id"] == iid
    assert isinstance(row["actions"], list)
    assert len(row["actions"]) >= 1
    assert "action_type" in row["actions"][0]
    assert "audit" in row
    assert row["audit"]["overall_verdict"] in (
        "grounded", "mismatch", "error", "unverifiable"
    )
    assert "total_actions" in row["audit"]


def test_export_http_endpoint(client, reset_ops_db, seed_automotive_pack):
    iid = _seed_interaction("int_export_http_1")
    r = client.get(
        "/api/frontline/audits/export",
        params={"interaction_ids": iid, "limit": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    found = [x for x in body["interactions"] if x["interaction_id"] == iid]
    assert found
    assert found[0]["actions"]
    assert "overall_verdict" in found[0]["audit"]


def test_export_requires_key_when_configured(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.setenv("FRONTLINE_API_KEY", "export-secret")
    iid = _seed_interaction("int_export_auth_1")
    with TestClient(app) as client:
        denied = client.get(
            "/api/frontline/audits/export",
            params={"interaction_ids": iid},
        )
        assert denied.status_code == 401
        ok = client.get(
            "/api/frontline/audits/export",
            params={"interaction_ids": iid},
            headers={"X-API-Key": "export-secret"},
        )
        assert ok.status_code == 200
        assert ok.json()["count"] >= 1
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_csv_export_and_manifest(reset_ops_db, seed_automotive_pack):
    """CSV body is parseable; manifest count + SHA256 match the CSV bytes."""
    import csv
    import hashlib
    import io

    from src.api.export import build_audit_export_csv, build_manifest

    iid = _seed_interaction("int_export_csv_1")
    payload = await build_audit_export_csv(interaction_ids=[iid], run_auditor=True)
    assert payload["format"] == "csv"
    assert payload["count"] >= 1
    csv_body = payload["csv"]
    assert "interaction_id" in csv_body.splitlines()[0]
    reader = csv.DictReader(io.StringIO(csv_body))
    rows = list(reader)
    assert any(r["interaction_id"] == iid for r in rows)

    man = payload["manifest"]
    assert man["count"] == payload["count"]
    assert man["sha256"] == hashlib.sha256(csv_body.encode("utf-8")).hexdigest()
    assert man["byte_length"] == len(csv_body.encode("utf-8"))
    # build_manifest agrees with payload
    assert build_manifest(csv_body, count=payload["count"])["sha256"] == man["sha256"]


def test_csv_export_http_endpoint(client, reset_ops_db, seed_automotive_pack):
    import csv
    import hashlib
    import io

    iid = _seed_interaction("int_export_csv_http")
    r = client.get(
        "/api/frontline/audits/export",
        params={"interaction_ids": iid, "format": "csv", "limit": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "csv"
    assert body["count"] >= 1
    assert "interaction_id" in body["csv"]
    rows = list(csv.DictReader(io.StringIO(body["csv"])))
    assert any(row["interaction_id"] == iid for row in rows)
    assert body["manifest"]["sha256"] == hashlib.sha256(
        body["csv"].encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_json_export_includes_manifest(reset_ops_db, seed_automotive_pack):
    iid = _seed_interaction("int_export_json_manifest")
    payload = await build_audit_export(interaction_ids=[iid], run_auditor=False)
    assert "manifest" in payload
    assert payload["manifest"]["count"] == payload["count"]
    assert len(payload["manifest"]["sha256"]) == 64
