"""Net-new enterprise capabilities — drive shipped modules + APIs (no reimplementation)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data.warehouse import ops_con
from src.enterprise.copilot import answer_supervisor_query
from src.enterprise.decision_flow import build_decision_flow
from src.enterprise.graph import build_ops_graph
from src.enterprise.memory import entity_key, list_memories, lookup_memory, upsert_memory_from_interaction
from src.enterprise.risk import score_from_signals, score_interaction_risk
from src.enterprise.root_cause import analyze_root_cause
from src.enterprise.scenarios import create_scenario, get_scenario, list_scenarios, run_scenario
from src.enterprise.timeline import build_incident_timeline
from src.ids import new_ulid


def _seed_interaction(
    iid: str | None = None,
    *,
    status: str = "completed",
    outcome: str = "case_created",
    peak_fr: float = 0.4,
    abandoned: bool = False,
) -> str:
    iid = iid or ("int_" + new_ulid())
    now = datetime.now(timezone.utc)
    if abandoned:
        status, outcome = "abandoned", "incomplete"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions (
                interaction_id, pack_id, pack_version, started_at, ended_at,
                channel, status, outcome, supervised, peak_frustration, last_frustration,
                entity_1, entity_2, entity_3, category
            ) VALUES (?, ?, ?, ?, ?, 'simulated', ?, ?, FALSE, ?, ?, ?, ?, ?, ?)
            """,
            [
                iid,
                "automotive_nhtsa",
                "0.0.0-test",
                now,
                now,
                status,
                outcome,
                peak_fr,
                peak_fr,
                "2019",
                "Toyota",
                "Camry",
                "brakes",
            ],
        )
        con.execute(
            """
            INSERT INTO interaction_turns
            (turn_id, interaction_id, seq, speaker, text, ts, llm_used, frustration_score)
            VALUES (?, ?, 1, 'customer', 'my brakes feel soft', ?, FALSE, ?)
            """,
            ["trn_" + new_ulid(), iid, now, peak_fr],
        )
        con.execute(
            """
            INSERT INTO agent_actions
            (action_id, interaction_id, agent, action_type, input_summary, output_summary,
             evidence_ids, ok, duration_ms, ts)
            VALUES (?, ?, 'intake', 'slot_extracted', 'text', 'slots filled', '[]', TRUE, 12, ?)
            """,
            ["act_" + new_ulid(), iid, now],
        )
        con.execute(
            """
            INSERT INTO agent_actions
            (action_id, interaction_id, agent, action_type, input_summary, output_summary,
             evidence_ids, ok, duration_ms, ts)
            VALUES (?, ?, 'orchestrator', 'state_transition', 'COLLECTING', 'ENRICHING', '[]', TRUE, 1, ?)
            """,
            ["act_" + new_ulid(), iid, now],
        )
    return iid


def _seed_case(iid: str, case_id: str | None = None) -> str:
    case_id = case_id or ("case_" + new_ulid())
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at, category,
                description_summary, onset, severity, severity_source, priority,
                safety_flags, cluster_match_id, similar_record_count, status, followup_draft
            ) VALUES (?, ?, 'automotive_nhtsa', ?, 'brakes', 'soft pedal', ?, 'Critical', 'rules', 1,
                      '{}', 1, 0, 'open', '')
            """,
            [case_id, iid, now, now],
        )
    return case_id


@pytest.fixture
def client(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


# ── Pure unit paths ──────────────────────────────────────────────────────────


def test_timeline_events(reset_ops_db):
    iid = _seed_interaction()
    tl = build_incident_timeline(iid)
    assert tl["interaction_id"] == iid
    assert tl["event_count"] >= 3
    kinds = {e["kind"] for e in tl["events"]}
    assert "turn" in kinds
    assert "agent_action" in kinds
    assert tl["events"][0]["step"] == 0
    assert "playback" in tl


def test_root_cause_failure(reset_ops_db):
    iid = _seed_interaction(abandoned=True, peak_fr=0.9)
    rc = analyze_root_cause(iid)
    assert rc["interaction_id"] == iid
    assert rc["is_failure"] is True
    assert rc["confidence"] > 0
    assert rc["suggested_fix"]
    assert rc["primary_cause"]


def test_risk_pure_and_db(reset_ops_db):
    s = score_from_signals(peak_frustration=0.9, safety_flag_count=1, turn_count=9)
    assert s["escalation_prob"] >= 0.5
    assert s["risk_level"] in ("high", "critical", "medium", "low")
    iid = _seed_interaction(status="active", outcome=None, peak_fr=0.8)
    # active may need null outcome — schema allows null outcome
    with ops_con() as con:
        con.execute(
            "UPDATE interactions SET status = 'active', ended_at = NULL, outcome = NULL WHERE interaction_id = ?",
            [iid],
        )
    r = score_interaction_risk(iid)
    assert r["interaction_id"] == iid
    assert 0 <= r["escalation_prob"] <= 1


def test_copilot_intents(reset_ops_db):
    _seed_interaction(peak_fr=0.95)
    a = answer_supervisor_query("Which customers are most frustrated?")
    assert a["intent"] == "most_frustrated"
    assert a["engine"] == "deterministic_intent_router"
    help_a = answer_supervisor_query("help")
    assert help_a["intent"] == "help"


def test_graph_and_decision_flow(reset_ops_db):
    iid = _seed_interaction()
    _seed_case(iid)
    g = build_ops_graph(pack_id="automotive_nhtsa")
    assert g["node_count"] >= 1
    assert g["edge_count"] >= 0
    flow = build_decision_flow(iid)
    assert flow["action_count"] >= 1
    assert "intake" in flow["agents_in_order"] or flow["action_count"] > 0


def test_memory_upsert_and_lookup(reset_ops_db):
    iid = _seed_interaction(peak_fr=0.3)
    _seed_case(iid)
    key = entity_key("2019", "Toyota", "Camry")
    assert key
    mem = upsert_memory_from_interaction(iid)
    assert mem is not None
    assert mem["entity_key"] == key
    assert mem["interaction_count"] == 1
    again = lookup_memory("automotive_nhtsa", entity_1="2019", entity_2="Toyota", entity_3="Camry")
    assert again and again["interaction_count"] >= 1
    assert list_memories(pack_id="automotive_nhtsa")

    # Second contact for same entity must UPDATE (not fail silently).
    iid2 = _seed_interaction(peak_fr=0.85)
    _seed_case(iid2)
    mem2 = upsert_memory_from_interaction(iid2)
    assert mem2 is not None, "second upsert must return a row"
    assert mem2["entity_key"] == key
    assert mem2["interaction_count"] >= 2
    assert mem2["last_interaction_id"] == iid2
    assert float(mem2.get("peak_frustration") or 0) >= 0.85
    # First memory_id retained (update, not insert-new-row)
    assert mem2["memory_id"] == mem["memory_id"]


def test_scenarios_crud(reset_ops_db):
    scn = create_scenario(
        pack_id="automotive_nhtsa",
        name="soft brake path",
        steps=[
            {"text": "My 2019 Toyota Camry has soft brakes"},
            {"text": "It happened yesterday on the highway"},
        ],
        description="test",
    )
    assert scn["scenario_id"].startswith("scn_")
    assert get_scenario(scn["scenario_id"])
    assert any(s["scenario_id"] == scn["scenario_id"] for s in list_scenarios())


@pytest.mark.asyncio
async def test_scenario_run_orchestrator(reset_ops_db, seed_automotive_pack):
    scn = create_scenario(
        pack_id="automotive_nhtsa",
        name="fire escalate",
        steps=[{"text": "My car caught fire on the highway!"}],
    )
    result = await run_scenario(scn["scenario_id"])
    assert result["interaction_id"].startswith("int_")
    assert result["state"] in ("DONE", "ABANDONED", "CLOSING") or result.get("ended") is not None


# ── HTTP surface ─────────────────────────────────────────────────────────────


def test_enterprise_apis(client, reset_ops_db):
    iid = _seed_interaction(abandoned=True, peak_fr=0.9)
    _seed_case(iid)

    r = client.get(f"/api/frontline/enterprise/timeline/{iid}")
    assert r.status_code == 200
    assert r.json()["event_count"] >= 1

    r = client.get(f"/api/frontline/enterprise/root-cause/{iid}")
    assert r.status_code == 200
    assert r.json()["primary_cause"]

    r = client.get("/api/frontline/enterprise/root-cause")
    assert r.status_code == 200
    assert "postmortems" in r.json()

    r = client.post("/api/frontline/enterprise/copilot", json={"query": "show open cases"})
    assert r.status_code == 200
    assert r.json()["intent"] == "open_cases"

    r = client.get(f"/api/frontline/enterprise/risk/{iid}")
    assert r.status_code == 200
    assert "escalation_prob" in r.json()

    r = client.get("/api/frontline/enterprise/graph")
    assert r.status_code == 200
    assert "nodes" in r.json()

    r = client.post(f"/api/frontline/enterprise/memory/upsert/{iid}")
    assert r.status_code == 200

    r = client.get("/api/frontline/enterprise/memory")
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = client.post(
        "/api/frontline/enterprise/scenarios",
        json={
            "pack_id": "automotive_nhtsa",
            "name": "api scn",
            "steps": [{"text": "hello issue"}],
        },
    )
    assert r.status_code == 200
    sid = r.json()["scenario_id"]

    r = client.get("/api/frontline/enterprise/scenarios")
    assert r.status_code == 200

    r = client.get(f"/api/frontline/enterprise/decision-flow/{iid}")
    assert r.status_code == 200
    assert r.json()["action_count"] >= 1

    # keep sid used
    assert sid.startswith("scn_")


def test_enterprise_auth_401(reset_ops_db, monkeypatch):
    monkeypatch.setenv("FRONTLINE_API_KEY", "ent-secret")
    with TestClient(app) as c:
        assert c.get("/api/frontline/enterprise/graph").status_code == 401
        assert (
            c.get(
                "/api/frontline/enterprise/graph",
                headers={"X-API-Key": "ent-secret"},
            ).status_code
            == 200
        )
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)


def test_dashboard_enterprise_page_wired():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    app = (root / "dashboard/src/App.jsx").read_text(encoding="utf-8")
    page = (root / "dashboard/routes/EnterpriseOps.jsx").read_text(encoding="utf-8")
    assert "EnterpriseOps" in app
    assert "enterprise" in app
    for path in (
        "/api/frontline/enterprise/timeline/",
        "/api/frontline/enterprise/root-cause",
        "/api/frontline/enterprise/copilot",
        "/api/frontline/enterprise/risk/active",
        "/api/frontline/enterprise/graph",
        "/api/frontline/enterprise/memory",
        "/api/frontline/enterprise/scenarios",
        "/api/frontline/enterprise/decision-flow/",
    ):
        assert path in page, f"missing {path} in EnterpriseOps.jsx"
