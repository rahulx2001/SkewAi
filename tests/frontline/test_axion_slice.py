"""Axion roadmap slice: multi-source ingest, cross-source briefs, fleet scans.

Covers the "call resolves the issue, data feeds the fleet loop" journey:
second/third sources landing in canonical records, cross-source entity
links on the investigator brief, cadence-driven fleet scans opening
investigations with no contact, and engineer comments on investigations.
"""

from __future__ import annotations

import pytest

WARRANTY_CSV = """CLAIM_ID,CLAIM_DATE,REPAIR_DATE,MODEL_YR,MAKETXT,MODELTXT,COMPNAME,FAIL_CODE,TECH_NOTES,CLAIM_SEVERITY,STATE
100001,2024-03-01,2024-02-20,2019,HONDA,CR-V,SERVICE BRAKES,PAD-WEAR,front pads worn to backing plate grinding,Medium,CA
100002,2024-03-05,2024-02-28,2019,HONDA,CR-V,SERVICE BRAKES,PAD-WEAR,grinding noise front brakes pad replacement,Medium,TX
100003,2024-03-06,2024-03-01,2018,TOYOTA,CAMRY,AIR BAGS,,airbag light on dash,,WA
,,2024-03-01,2019,HONDA,CR-V,SERVICE BRAKES,,,
"""

SERVICE_CSV = """RO_NUMBER,VISIT_DATE,MODEL_YR,MAKE,MODEL,SYSTEM,OP_CODE,TECH_NOTES,STATE
RO-77,2024-03-02,2019,HONDA,CR-V,SERVICE BRAKES,INSP,customer reports grinding when braking at low speed,CA
RO-78,2024-03-03,2019,HONDA,CR-V,SERVICE BRAKES,BRK-RPL,front brake pads and rotors replaced grinding resolved,CA
"""


def _write_csv(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ── Source connectors ────────────────────────────────────────────────────────


def test_ingest_warranty_and_service_sources(tmp_path, monkeypatch):
    from src.config import REPO_ROOT
    from src.data.warehouse import domain_con
    from src.domains.source_ingest import ingest_source, namespace_id

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    auto_data = REPO_ROOT / "domains" / "automotive_nhtsa" / "data"
    assert namespace_id("warranty", "100001") == "WARRANTY-100001"
    assert namespace_id("warranty", "WARRANTY-100001") == "WARRANTY-100001"

    wcsv = _write_csv(tmp_path, "warranty.csv", WARRANTY_CSV)
    rep = ingest_source(
        "axion_src_pack", "warranty", wcsv,
        mapping_path=auto_data / "mapping.warranty.yaml",
    )
    assert rep["source"] == "WARRANTY"
    assert rep["mapped"] == 3, "row with no CLAIM_ID/text must not map"
    assert rep["upserted"] == 3

    scsv = _write_csv(tmp_path, "service.csv", SERVICE_CSV)
    rep2 = ingest_source(
        "axion_src_pack", "service", scsv,
        mapping_path=auto_data / "mapping.service.yaml",
    )
    assert rep2["source"] == "SERVICE"
    assert rep2["upserted"] == 2

    with domain_con("axion_src_pack") as con:
        rows = con.execute(
            "SELECT record_id, source, entity_2, category FROM records"
        ).fetchall()
    by_id = {r[0]: (r[1], r[2], r[3]) for r in rows}
    assert by_id["WARRANTY-100001"] == ("WARRANTY", "HONDA", "SERVICE BRAKES")
    assert by_id["SERVICE-RO-77"][0] == "SERVICE"
    sources = {r[1] for r in rows}
    assert sources == {"WARRANTY", "SERVICE"}
    # Re-ingest is an upsert, not a duplicate.
    rep3 = ingest_source(
        "axion_src_pack", "warranty", wcsv,
        mapping_path=auto_data / "mapping.warranty.yaml",
    )
    assert rep3["upserted"] == 3
    with domain_con("axion_src_pack") as con:
        n = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    assert n == 5


def test_ingest_source_missing_inputs(tmp_path, monkeypatch):
    from src.domains.source_ingest import ingest_source

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        ingest_source("p", "warranty", tmp_path / "nope.csv")
    with pytest.raises(ValueError):
        ingest_source("p", "", tmp_path / "nope.csv")


# ── Cross-source investigator brief ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_brief_carries_source_mix_and_links(
    orchestrator_factory, tmp_path, monkeypatch
):
    """HONDA brake evidence across NHTSA + WARRANTY + SERVICE links up."""
    from src.agents.base import InteractionContext
    from src.agents.investigator import InvestigatorAgent
    from src.config import REPO_ROOT
    from src.domains.source_ingest import ingest_source

    orch, _ = orchestrator_factory()
    pack = orch.ctx.pack
    auto_data = REPO_ROOT / "domains" / "automotive_nhtsa" / "data"
    wcsv = _write_csv(tmp_path, "w.csv", WARRANTY_CSV)
    scsv = _write_csv(tmp_path, "s.csv", SERVICE_CSV)
    ingest_source(
        pack.id, "warranty", wcsv,
        mapping_path=auto_data / "mapping.warranty.yaml",
    )
    ingest_source(
        pack.id, "service", scsv,
        mapping_path=auto_data / "mapping.service.yaml",
    )

    ctx = InteractionContext(
        interaction_id="int_xsrc", pack=pack, channel="web_text"
    )
    ctx.slots.update({
        "category": "SERVICE BRAKES", "entity_2": "HONDA", "entity_3": "CR-V",
        "description": "front brake grinding noise when stopping",
    })
    res = await InvestigatorAgent(ctx).run()
    brief = ctx.investigation_brief
    assert brief, "investigator must produce a brief"
    # Cited top-5 mix is labeled as such…
    assert isinstance(brief.get("sources"), dict)
    # …while the pool mix shows every origin corroborating the match.
    pool_mix = brief.get("candidate_sources") or {}
    assert set(pool_mix) >= {"NHTSA", "WARRANTY", "SERVICE"}, f"pool mix: {pool_mix}"
    assert brief.get("candidate_count", 0) >= sum(pool_mix.values()) - 0
    links = brief.get("cross_source_links") or []
    assert links, "expected a cross-source entity link"
    observed = [lk for lk in links if lk.get("basis") == "observed"]
    assert observed, f"expected observed (entity_key) links: {links}"
    assert any("WARRANTY" in lk["sources"] for lk in observed)
    assert any("SERVICE" in lk["sources"] for lk in observed)


# ── Scheduled fleet scan ─────────────────────────────────────────────────────


def _spike_pack(tmp_path, monkeypatch, pack_id="fleet_pack"):
    from datetime import datetime, timedelta

    from src.data.warehouse import apply_domain_schema, domain_con

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    now = datetime(2024, 5, 15)
    with domain_con(pack_id, read_only=False) as con:
        apply_domain_schema(con)
        n = 0
        for w in range(4):
            day = now - timedelta(weeks=5 - w)
            for i in range(2):
                n += 1
                con.execute(
                    """INSERT INTO records (record_id, occurred_at, received_at,
                       entity_2, entity_3, category, text, source)
                       VALUES (?, ?, ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')""",
                    [f"Q-{w}-{i}", day, day, f"quiet brake note {w} {i}"],
                )
        for i in range(20):
            n += 1
            con.execute(
                """INSERT INTO records (record_id, occurred_at, received_at,
                   entity_2, entity_3, category, text, source)
                   VALUES (?, ?, ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')""",
                [f"S-{i}", now, now, f"spike grinding brakes {i}"],
            )
        con.execute(
            """INSERT INTO clusters (cluster_id, pack_id, top_terms, category,
               record_count, first_seen, last_seen)
               VALUES (1000, ?, '["grinding","brakes"]', 'SERVICE BRAKES', 28, ?, ?)""",
            [pack_id, now - timedelta(days=40), now],
        )
        for i in range(20):
            con.execute(
                "INSERT INTO cluster_assignments (record_id, cluster_id, distance)"
                " VALUES (?, 1000, 0.2)",
                [f"S-{i}"],
            )
    return pack_id


def test_fleet_scan_opens_investigation_without_contact(
    reset_ops_db, tmp_path, monkeypatch
):
    from src.data.warehouse import ops_con
    from src.frontline.fleet_scan import run_fleet_scan

    pack = _spike_pack(tmp_path, monkeypatch)
    report = run_fleet_scan(pack, rebuild_clusters=False, alert=False)
    assert report["anomaly_slices"] >= 1
    assert len(report["investigations_opened"]) >= 1
    opened = report["investigations_opened"][0]
    assert opened["cluster_id"] == 1000
    assert opened["investigation_id"].startswith("inv_")
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT status FROM investigations WHERE investigation_id = ?",
            [opened["investigation_id"]],
        ).fetchone()
    assert row and row[0] == "open"
    # Second scan links instead of opening a duplicate.
    again = run_fleet_scan(pack, rebuild_clusters=False, alert=False)
    assert again["investigations_opened"] == []
    assert len(again["investigations_linked"]) >= 1


def test_scheduled_scan_job_type(reset_ops_db, tmp_path, monkeypatch):
    from src.jobs.queue import enqueue, run_next

    pack = _spike_pack(tmp_path, monkeypatch, pack_id="fleet_job_pack")
    job = enqueue("scheduled_scan", {"pack_id": pack})
    assert job["status"] == "pending"
    done = run_next(worker_id="scanner-1")
    assert done is not None and done["status"] == "done"
    assert done["result"]["anomaly_slices"] >= 1


def test_ingest_source_job_type(reset_ops_db, tmp_path, monkeypatch):
    from src.config import REPO_ROOT
    from src.jobs.queue import enqueue, run_next

    monkeypatch.setenv("DOMAIN_DB_PATH", str(tmp_path))
    wcsv = _write_csv(tmp_path, "w.csv", WARRANTY_CSV)
    job = enqueue(
        "ingest_source",
        {
            "pack_id": "job_src_pack",
            "source": "warranty",
            "csv_path": str(wcsv),
            "mapping_path": str(
                REPO_ROOT / "domains" / "automotive_nhtsa" / "data"
                / "mapping.warranty.yaml"
            ),
        },
    )
    done = run_next(worker_id="ingestor-1")
    assert done is not None and done["status"] == "done"
    assert done["result"]["upserted"] == 3
    assert done["result"]["source"] == "WARRANTY"


# ── Investigation comments ───────────────────────────────────────────────────


def test_investigation_comments_workspace(reset_ops_db):
    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con
    from src.enterprise.investigation_workspace import (
        add_comment,
        get_investigation,
        list_comments,
    )

    with ops_con() as con:
        con.execute(
            """INSERT INTO investigations (investigation_id, pack_id, cluster_id,
               title, status, opened_at, last_case_at, case_count)
               VALUES ('inv_comment_1', 'automotive_nhtsa', 14, 't', 'open', ?, ?, 1)""",
            [utc_now(), utc_now()],
        )
    inv = add_comment("inv_comment_1", "Confirmed with dealer stock.", author="Priya")
    assert any(c["author"] == "Priya" for c in inv["comments"])
    assert [c["body"] for c in list_comments("inv_comment_1")] == [
        "Confirmed with dealer stock."
    ]
    with pytest.raises(ValueError, match="body required"):
        add_comment("inv_comment_1", "   ")
    with pytest.raises(LookupError):
        add_comment("inv_missing", "hello")


def test_investigation_comments_api(reset_ops_db, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.data.timeutil import utc_now
    from src.data.warehouse import ops_con

    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with ops_con() as con:
        con.execute(
            """INSERT INTO investigations (investigation_id, pack_id, cluster_id,
               title, status, opened_at, last_case_at, case_count)
               VALUES ('inv_api_1', 'automotive_nhtsa', 14, 't', 'open', ?, ?, 1)""",
            [utc_now(), utc_now()],
        )
    with TestClient(app) as c:
        r1 = c.post(
            "/api/frontline/investigations/inv_api_1/comments",
            json={"body": "first note"},
            headers={"Idempotency-Key": "icm-key-1"},
        )
        assert r1.status_code == 200
        r2 = c.post(
            "/api/frontline/investigations/inv_api_1/comments",
            json={"body": "first note"},
            headers={"Idempotency-Key": "icm-key-1"},
        )
        assert r2.status_code == 200 and r2.json() == r1.json()
        assert c.get("/api/frontline/investigations/inv_api_1/comments").json()["count"] == 1
        assert c.post(
            "/api/frontline/investigations/inv_missing/comments",
            json={"body": "x"},
        ).status_code == 404
