"""Frontline v3 OS foundation: learning, experiments, governance."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.v3.experiments import (
    complete_experiment_report,
    create_experiment,
    record_trial,
    register_artifact,
)
from src.v3.governance import (
    activate_deployment,
    create_deployment,
    get_active_deployment,
    get_stamp,
    rollback_deployment,
    stamp_interaction,
)
from src.v3.learning import (
    generate_proposal_for_interaction,
    generate_proposals_from_failures,
    learning_trends,
    list_proposals,
    review_proposal,
)


def _seed_failure_interaction() -> str:
    iid = "int_" + new_ulid()
    now = datetime.now(timezone.utc)
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions (
                interaction_id, pack_id, pack_version, started_at, ended_at,
                channel, status, outcome, supervised, peak_frustration, last_frustration,
                entity_1, entity_2, entity_3, category
            ) VALUES (?, 'automotive_nhtsa', 'packv1', ?, ?, 'sim', 'abandoned', 'incomplete',
                      FALSE, 0.9, 0.85, '2019', 'Toyota', 'Camry', 'brakes')
            """,
            [iid, now, now],
        )
        con.execute(
            """
            INSERT INTO agent_actions
            (action_id, interaction_id, agent, action_type, input_summary, output_summary,
             evidence_ids, ok, error, duration_ms, ts)
            VALUES (?, ?, 'intake', 'slot_extracted', 'x', 'y', '[]', FALSE, 'timeout', 50, ?)
            """,
            ["act_" + new_ulid(), iid, now],
        )
    return iid


@pytest.fixture
def client(reset_ops_db, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c


# ── Learning ─────────────────────────────────────────────────────────────────


def test_learning_proposal_generate_review(reset_ops_db):
    iid = _seed_failure_interaction()
    prop = generate_proposal_for_interaction(iid)
    assert prop is not None
    assert prop["status"] == "proposed"
    assert prop["interaction_id"] == iid
    assert prop["weakness_class"]
    assert prop["suggested_change"]

    # idempotent — no second open proposal
    assert generate_proposal_for_interaction(iid) is None

    approved = review_proposal(prop["proposal_id"], status="approved", reviewed_by="qa")
    assert approved["status"] == "approved"
    deployed = review_proposal(prop["proposal_id"], status="deployed")
    assert deployed["status"] == "deployed"

    batch = generate_proposals_from_failures(limit=10)
    assert "created" in batch
    trends = learning_trends(window_days=30)
    assert trends["total"] >= 1
    assert "by_status" in trends


# ── Experiments ──────────────────────────────────────────────────────────────


def test_experiment_compare_report(reset_ops_db):
    c = register_artifact(
        kind="prompt", name="greet", version="1.0.0", body={"text": "Hello"}
    )
    k = register_artifact(
        kind="prompt", name="greet", version="1.1.0", body={"text": "Hi there"}
    )
    exp = create_experiment(
        name="greet-ab",
        control_artifact_id=c["artifact_id"],
        candidate_artifact_id=k["artifact_id"],
        mode="ab",
    )
    record_trial(
        exp["experiment_id"],
        arm="control",
        resolution_ok=True,
        escalated=True,
        latency_ms=150,
        groundedness_ok=True,
        hallucination_flag=False,
        cost_units=1.0,
    )
    record_trial(
        exp["experiment_id"],
        arm="candidate",
        resolution_ok=True,
        escalated=False,
        latency_ms=80,
        groundedness_ok=True,
        hallucination_flag=False,
        cost_units=0.5,
    )
    report = complete_experiment_report(exp["experiment_id"])
    assert report["status"] == "completed"
    m = report["metrics"]
    assert m["control"]["n"] == 1
    assert m["candidate"]["n"] == 1
    assert m["winner"] in ("control", "candidate", "tie")
    assert "recommendation" in m


# ── Governance ───────────────────────────────────────────────────────────────


def test_governance_activate_rollback_stamp(reset_ops_db):
    d1 = create_deployment(label="v1-config", artifact_versions={"prompt/greet": "1.0.0"})
    d2 = create_deployment(label="v2-config", artifact_versions={"prompt/greet": "1.1.0"})
    activate_deployment(d1["deployment_id"])
    assert get_active_deployment()["deployment_id"] == d1["deployment_id"]
    activate_deployment(d2["deployment_id"])
    assert get_active_deployment()["deployment_id"] == d2["deployment_id"]
    # Explicit target still works
    rolled = rollback_deployment(to_deployment_id=d1["deployment_id"])
    assert rolled["deployment_id"] == d1["deployment_id"]
    assert get_active_deployment()["status"] == "active"

    iid = _seed_failure_interaction()
    stamp = stamp_interaction(iid)
    assert stamp is not None
    assert stamp["pack_id"] == "automotive_nhtsa"
    assert stamp["pack_version"] == "packv1"
    assert stamp["deployment_id"] == d1["deployment_id"]
    assert stamp["model_policy"] == "deterministic"
    assert get_stamp(iid)["interaction_id"] == iid


def test_governance_default_rollback_restores_prior_inactive(reset_ops_db):
    """UI/API empty-body rollback must not re-activate the just-rolled deployment."""
    d1 = create_deployment(label="base-config", artifact_versions={"prompt/x": "1"})
    d2 = create_deployment(label="next-config", artifact_versions={"prompt/x": "2"})
    activate_deployment(d1["deployment_id"])
    activate_deployment(d2["deployment_id"])
    # d1 is inactive, d2 is active — default rollback (no to_deployment_id)
    restored = rollback_deployment()
    assert restored["deployment_id"] == d1["deployment_id"]
    active = get_active_deployment()
    assert active is not None
    assert active["deployment_id"] == d1["deployment_id"]
    assert active["status"] == "active"
    # d2 must stay rolled_back, not active
    from src.v3.governance import get_deployment

    d2_after = get_deployment(d2["deployment_id"])
    assert d2_after["status"] == "rolled_back"


# ── HTTP ─────────────────────────────────────────────────────────────────────


def test_v3_apis(client, reset_ops_db):
    iid = _seed_failure_interaction()

    r = client.post("/api/v3/learning/run?limit=10")
    assert r.status_code == 200
    assert r.json()["created"] >= 1

    r = client.get("/api/v3/learning/proposals")
    assert r.status_code == 200
    props = r.json()["proposals"]
    assert len(props) >= 1
    pid = props[0]["proposal_id"]

    r = client.post(
        f"/api/v3/learning/proposals/{pid}/review",
        json={"status": "approved"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    r = client.get("/api/v3/learning/trends")
    assert r.status_code == 200
    assert "by_status" in r.json()

    # experiments
    a1 = client.post(
        "/api/v3/artifacts",
        json={"kind": "routing", "name": "default", "version": "a", "body": {"policy": "cheap"}},
    ).json()
    a2 = client.post(
        "/api/v3/artifacts",
        json={"kind": "routing", "name": "default", "version": "b", "body": {"policy": "quality"}},
    ).json()
    exp = client.post(
        "/api/v3/experiments",
        json={
            "name": "routing-ab",
            "control_artifact_id": a1["artifact_id"],
            "candidate_artifact_id": a2["artifact_id"],
            "mode": "shadow",
        },
    ).json()
    client.post(
        f"/api/v3/experiments/{exp['experiment_id']}/trials",
        json={"arm": "control", "resolution_ok": True, "escalated": False, "latency_ms": 100},
    )
    client.post(
        f"/api/v3/experiments/{exp['experiment_id']}/trials",
        json={"arm": "candidate", "resolution_ok": True, "escalated": False, "latency_ms": 50},
    )
    r = client.post(f"/api/v3/experiments/{exp['experiment_id']}/complete")
    assert r.status_code == 200
    assert r.json()["metrics"]["winner"]

    # governance
    dep = client.post(
        "/api/v3/governance/deployments",
        json={"label": "pilot-1", "artifact_versions": {"routing/default": "a"}},
    ).json()
    r = client.post(f"/api/v3/governance/deployments/{dep['deployment_id']}/activate", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    r = client.post(f"/api/v3/governance/stamps/{iid}", json={})
    assert r.status_code == 200
    assert r.json()["pack_version"] == "packv1"

    r = client.get("/api/v3/governance/deployments")
    assert r.status_code == 200
    assert r.json()["active"]["deployment_id"] == dep["deployment_id"]

    # Second deploy then default rollback (PlatformOS empty body)
    dep2 = client.post(
        "/api/v3/governance/deployments",
        json={"label": "pilot-2", "artifact_versions": {"routing/default": "b"}},
    ).json()
    assert (
        client.post(
            f"/api/v3/governance/deployments/{dep2['deployment_id']}/activate",
            json={},
        ).status_code
        == 200
    )
    r = client.post("/api/v3/governance/rollback", json={})
    assert r.status_code == 200
    assert r.json()["deployment_id"] == dep["deployment_id"]
    assert r.json()["status"] == "active"


def test_dashboard_platform_os_wired():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    app = (root / "dashboard/src/App.jsx").read_text(encoding="utf-8")
    page = (root / "dashboard/routes/PlatformOS.jsx").read_text(encoding="utf-8")
    assert "PlatformOS" in app
    assert "platform" in app
    for path in (
        "/api/v3/learning/run",
        "/api/v3/learning/proposals",
        "/api/v3/experiments",
        "/api/v3/governance/deployments",
        "/api/v3/governance/rollback",
    ):
        assert path in page, f"missing {path}"
