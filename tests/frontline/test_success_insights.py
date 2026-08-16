"""Frontline success gaps: CSAT, product-gap, remedy, multi-issue, explainability."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


@pytest.fixture
def client(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.delenv("FRONTLINE_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    with TestClient(app) as c:
        yield c


def _seed_ix(iid: str, *, frust: float, outcome: str, category: str, days_ago: int = 0):
    ts = utc_now() - timedelta(days=days_ago)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status,
             outcome, peak_frustration, category, entity_2)
            VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'completed', ?, ?, ?, 'HONDA')
            """,
            [iid, ts, outcome, frust, category],
        )


def _seed_case(
    case_id: str,
    iid: str,
    *,
    severity: str,
    category: str,
    cluster: int | None,
    days_ago: int = 0,
):
    ts = utc_now() - timedelta(days=days_ago)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at,
                category, description_summary, onset, severity,
                severity_source, priority, safety_flags,
                advisory_match_id, cluster_match_id, similar_record_count,
                investigation_id, status, followup_draft
            ) VALUES (?, ?, 'automotive_nhtsa', ?, ?, 'sum', ?, ?, 'rules',
                      ?, '{}', NULL, ?, 1, NULL, 'open', '')
            """,
            [
                case_id,
                iid,
                ts,
                category,
                ts,
                severity,
                1 if severity == "Critical" else 2,
                cluster,
            ],
        )


def test_csat_themes_from_seeded_rows(reset_ops_db):
    from src.frontline.insights import build_csat_themes

    _seed_ix("int_csat_1", frust=0.9, outcome="case_created", category="SERVICE BRAKES")
    _seed_ix("int_csat_2", frust=0.2, outcome="incomplete", category="ENGINE")
    _seed_case("case_csat_1", "int_csat_1", severity="Critical", category="SERVICE BRAKES", cluster=14)
    _seed_case("case_csat_2", "int_csat_2", severity="Low", category="ENGINE", cluster=None)

    out = build_csat_themes(window_days=7)
    assert out["contact_count"] == 2
    assert out["label"] == "friction_proxy_not_survey_nps"
    assert 0 <= out["satisfaction_proxy"] <= 1
    assert out["angry_contacts"] >= 1
    assert "case_created" in out["outcome_mix"]
    themes = {t["theme"]: t["volume"] for t in out["top_themes"]}
    assert themes.get("SERVICE BRAKES", 0) >= 1

    # Changing data changes metrics
    _seed_ix("int_csat_3", frust=0.95, outcome="escalated_safety", category="AIR BAGS")
    out2 = build_csat_themes(window_days=7)
    assert out2["contact_count"] == 3
    assert out2["angry_contacts"] >= out["angry_contacts"]


def test_product_gap_critical_ranks_and_drift(reset_ops_db):
    from src.frontline.insights import build_product_gap_board

    # Cluster 10: Critical heavy recent
    for i in range(4):
        iid = f"int_gap_c_{i}"
        _seed_ix(iid, frust=0.5, outcome="case_created", category="SERVICE BRAKES", days_ago=1)
        _seed_case(
            f"case_gap_c_{i}",
            iid,
            severity="Critical",
            category="SERVICE BRAKES",
            cluster=10,
            days_ago=1,
        )
    # Cluster 11: Low only, same volume
    for i in range(4):
        iid = f"int_gap_l_{i}"
        _seed_ix(iid, frust=0.1, outcome="case_created", category="STRUCTURE", days_ago=1)
        _seed_case(
            f"case_gap_l_{i}",
            iid,
            severity="Low",
            category="STRUCTURE",
            cluster=11,
            days_ago=1,
        )
    # Cluster 12: severity worsening (prior Low, recent Critical)
    for i in range(2):
        iid = f"int_gap_p_{i}"
        _seed_ix(iid, frust=0.3, outcome="case_created", category="ENGINE", days_ago=10)
        _seed_case(
            f"case_gap_p_{i}",
            iid,
            severity="Low",
            category="ENGINE",
            cluster=12,
            days_ago=10,
        )
    for i in range(2):
        iid = f"int_gap_r_{i}"
        _seed_ix(iid, frust=0.8, outcome="case_created", category="ENGINE", days_ago=1)
        _seed_case(
            f"case_gap_r_{i}",
            iid,
            severity="Critical",
            category="ENGINE",
            cluster=12,
            days_ago=1,
        )

    board = build_product_gap_board(window_days=14, limit=10)
    assert board["top_issues"]
    # Critical-heavy cluster 10 should rank above Low-only cluster 11 at same volume
    keys = [i["cluster_id"] for i in board["top_issues"]]
    if 10 in keys and 11 in keys:
        assert keys.index(10) < keys.index(11)
    rising = [i for i in board["rising_issues"] if i.get("cluster_id") == 12]
    assert rising, board["rising_issues"]
    assert rising[0]["getting_worse"] is True


def test_remedy_offer_grounded_and_ledgered(reset_ops_db):
    from src.frontline.remedy import offer_and_ledger
    from src.ledger.writer import list_actions

    iid = "int_rem_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'active')
            """,
            [iid, utc_now()],
        )
    offer = offer_and_ledger(
        iid,
        advisory_match={
            "advisory_id": "19V-12345",
            "summary": "Front brake pad wear",
            "remedy": "Dealer replaces pads free of charge",
            "url": "https://example.com/r",
        },
        case_id="case_rem_1",
    )
    assert offer is not None
    assert "19V-12345" in offer["customer_text"]
    assert "pads" in offer["customer_text"].lower()
    acts = list_actions(iid)
    assert any("remedy" in (a.get("input_summary") or "") for a in acts)


def test_multi_issue_creates_linked_cases(reset_ops_db):
    from src.frontline.multi_issue import (
        attach_multi_issues_from_description,
        split_issues_from_text,
    )

    parts = split_issues_from_text(
        "My brakes grind when stopping also the airbag light is on"
    )
    assert len(parts) >= 2

    iid = "int_multi_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'active')
            """,
            [iid, utc_now()],
        )
    created = attach_multi_issues_from_description(
        iid,
        pack_id="automotive_nhtsa",
        description="My brakes grind when stopping also the airbag light is on",
        primary_case_id="case_primary_multi",
        category="SERVICE BRAKES",
    )
    assert len(created) >= 2
    assert len({c["issue_id"] for c in created}) == len(created)
    with ops_con(read_only=True) as con:
        n_iss = con.execute(
            "SELECT COUNT(*) FROM contact_issues WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
        n_cases = con.execute(
            "SELECT COUNT(*) FROM cases WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
    assert n_iss >= 2
    assert n_cases >= 1  # secondary cases for seq>0


def test_multi_issue_ids_unique_under_burst(reset_ops_db):
    """Same-ms ULID truncation used to collide; stress attach path ≥25 times."""
    from src.frontline.multi_issue import attach_multi_issues_from_description

    desc = "My brakes grind when stopping also the airbag light is on"
    for i in range(25):
        iid = f"int_burst_{new_ulid()}_{i}"
        with ops_con() as con:
            con.execute(
                """
                INSERT INTO interactions
                (interaction_id, pack_id, pack_version, started_at, channel, status)
                VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'active')
                """,
                [iid, utc_now()],
            )
        created = attach_multi_issues_from_description(
            iid,
            pack_id="automotive_nhtsa",
            description=desc,
            primary_case_id=f"case_primary_{i}",
            category="SERVICE BRAKES",
        )
        assert len(created) >= 2, f"iter {i}: {created!r}"
        ids = [c["issue_id"] for c in created]
        assert len(ids) == len(set(ids)), f"iter {i} duplicate issue_ids: {ids}"
        case_ids = [c["case_id"] for c in created if c.get("case_id")]
        assert len(case_ids) == len(set(case_ids)), f"iter {i} dup cases: {case_ids}"


@pytest.mark.asyncio
async def test_case_agent_remedy_and_multi_issue_close_loop(
    reset_ops_db, seed_automotive_pack, pack
):
    """Real CaseAgent path: advisory remedy + multi-issue attach (not silent)."""
    from src.agents.base import InteractionContext
    from src.agents.case_agent import CaseAgent
    from src.ledger.writer import list_actions

    iid = "int_close_" + new_ulid()
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, ?, ?, ?, 'sim', 'active')
            """,
            [iid, pack.id, pack.pack_version, utc_now()],
        )
    ctx = InteractionContext(interaction_id=iid, pack=pack, channel="sim")
    ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        "description": (
            "My brakes grind when stopping also the airbag light is on"
        ),
    }
    ctx.severity = "Medium"
    ctx.severity_source = "rules"
    ctx.priority = 2
    ctx.advisory_match = {
        "advisory_id": "19V-12345",
        "summary": "Front brake pad wear",
        "remedy": "Dealer replaces pads free of charge",
        "url": "https://www.nhtsa.gov/recalls/19V-12345",
    }
    cres = await CaseAgent(ctx).run()
    assert cres.get("case_id")
    assert cres.get("remedy_offer")
    assert "19V-12345" in cres["remedy_offer"]["customer_text"]
    linked = cres.get("linked_issues") or getattr(ctx, "linked_issues", None) or []
    assert len(linked) >= 2, f"multi-issue silent no-op: {cres!r}"
    with ops_con(read_only=True) as con:
        n_iss = con.execute(
            "SELECT COUNT(*) FROM contact_issues WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
    assert n_iss >= 2
    acts = list_actions(iid)
    assert any("remedy" in (a.get("input_summary") or "") for a in acts)
    assert not any(
        a.get("input_summary") == "multi_issue_attach_failed" for a in acts
    )


def test_explainability_surfaces_evidence(reset_ops_db):
    from src.frontline.explainability import explain_interaction
    from src.ledger import AgentAction, record_action

    iid = "int_exp_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status,
             entity_1, entity_2, entity_3, category, description)
            VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'completed',
                    '2019', 'HONDA', 'CR-V', 'SERVICE BRAKES', 'grinds')
            """,
            [iid, utc_now()],
        )
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at,
                category, description_summary, onset, severity,
                severity_source, priority, safety_flags,
                advisory_match_id, cluster_match_id, similar_record_count,
                investigation_id, status, followup_draft
            ) VALUES (?, ?, 'automotive_nhtsa', ?, 'SERVICE BRAKES', 'grinds', ?,
                      'Medium', 'rules', 2, '{}', '19V-12345', 14, 3, NULL, 'open', '')
            """,
            ["case_exp_1", iid, utc_now(), utc_now()],
        )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="investigator",
            action_type="similar_search",
            output_summary="found 3",
            evidence_ids=["NHTSA-100001", "NHTSA-100002"],
        )
    )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="investigator",
            action_type="brief_written",
            output_summary="lead_time_weeks=11, matched_advisory=19V-12345",
            evidence_ids=["19V-12345"],
        )
    )
    exp = explain_interaction(iid)
    assert exp["found"] is True
    assert exp["slots"]["entity_2"] == "HONDA"
    assert exp["severity_source"] == "rules"
    assert exp["advisory"]["advisory_id"] == "19V-12345"
    assert "NHTSA-100001" in exp["similar_records"] or "NHTSA-100001" in exp["evidence_ids"]
    assert exp["lead_time_weeks"] == 11
    assert exp["summary_bullets"]


def test_insights_api(client, reset_ops_db):
    _seed_ix("int_api_1", frust=0.7, outcome="case_created", category="SERVICE BRAKES")
    _seed_case(
        "case_api_1",
        "int_api_1",
        severity="Medium",
        category="SERVICE BRAKES",
        cluster=14,
    )
    r = client.get("/api/frontline/insights/csat?window_days=7")
    assert r.status_code == 200
    assert r.json()["contact_count"] >= 1
    r2 = client.get("/api/frontline/insights/product-gap?window_days=14")
    assert r2.status_code == 200
    assert "top_issues" in r2.json()
    r3 = client.get("/api/frontline/explain/int_api_1")
    assert r3.status_code == 200
    assert r3.json()["found"] is True


def test_demo_script_honesty():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    demo = (root / "docs" / "demo_script.md").read_text(encoding="utf-8")
    assert "data + analysis" in demo.lower() or "data and analysis" in demo.lower() or "not another voice bot" in demo.lower()
    assert "friction proxy" in demo.lower() or "not survey nps" in demo.lower()
    assert "stub" in demo.lower() or "not** Twilio" in demo or "not Twilio" in demo
    assert "bag-of-hash" in demo.lower() or "ILIKE" in demo
    assert "Insights" in demo
