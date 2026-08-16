"""Phase-2 residual: agent depth, ingest, alert rules, cluster, DSR, wallboard."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid


@pytest.fixture
def client(reset_ops_db, seed_automotive_pack, monkeypatch):
    monkeypatch.delenv("FRONTLINE_API_KEY", raising=False)
    monkeypatch.delenv("FRONTLINE_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("FRONTLINE_ENABLED", "1")
    with TestClient(app) as c:
        yield c


def test_case_status_lookup(reset_ops_db):
    from src.agents.case_status import (
        format_case_status_reply,
        get_case_status,
        try_case_status_from_utterance,
    )

    cid = "case_status_demo_1"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at,
                category, description_summary, onset, severity,
                severity_source, priority, safety_flags,
                advisory_match_id, cluster_match_id, similar_record_count,
                investigation_id, status, followup_draft
            ) VALUES (?, ?, 'automotive_nhtsa', ?, 'SERVICE BRAKES', 'grinds', ?,
                      'Medium', 'rules', 2, '{}', NULL, 14, 3, NULL, 'open', 'draft')
            """,
            [cid, "int_case_status", utc_now(), utc_now()],
        )
    case = get_case_status(cid)
    assert case is not None
    assert case["status"] == "open"
    reply = format_case_status_reply(case)
    assert cid in reply
    hit = try_case_status_from_utterance(f"What's the status of {cid}?")
    assert hit and hit["found"] is True


def test_memory_slot_skip(reset_ops_db, seed_automotive_pack, pack):
    from src.agents.base import InteractionContext
    from src.agents.intake import IntakeAgent
    from src.enterprise.memory import entity_key
    from src.data.timeutil import utc_now

    key = entity_key("2019", "HONDA", "CR-V")
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO contact_memory (
                memory_id, pack_id, entity_key, entity_1, entity_2, entity_3,
                last_category, interaction_count, open_case_count,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, '2019', 'HONDA', 'CR-V', 'SERVICE BRAKES', 2, 1, ?, ?)
            """,
            ["mem_1", pack.id, key, utc_now(), utc_now()],
        )
    ctx = InteractionContext(
        interaction_id="int_mem_skip",
        pack=pack,
        channel="sim",
    )
    ctx.slots = {"entity_2": "HONDA", "entity_3": "CR-V", "entity_1": "2019"}
    agent = IntakeAgent(ctx)
    agent._prefill_from_memory()
    assert ctx.slots.get("category") == "SERVICE BRAKES"


@pytest.mark.asyncio
async def test_confidence_escalate(reset_ops_db, seed_automotive_pack, pack):
    from src.agents.base import InteractionContext
    from src.agents.intake import IntakeAgent

    ctx = InteractionContext(interaction_id="int_conf", pack=pack, channel="sim")
    # All required except description filled; description re-asks exhausted
    ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        # leave description empty; attempts already exhausted
    }
    ctx._safety_asked = set(range(20))  # type: ignore[attr-defined]
    slot = next(s for s in pack.manifest.slot_frame if s.name == "description")
    ctx.slot_attempts["description"] = (slot.max_re_asks or 1) + 5
    agent = IntakeAgent(ctx)
    # No customer text → free-text does not fill; re-ask count triggers escalate
    res = await agent.run(customer_turn="")
    assert res.get("escalate_low_confidence") is True
    assert "specialist" in (res.get("question") or "").lower()


def test_self_critique_hard_fail_missing_slots(reset_ops_db, seed_automotive_pack, pack):
    from src.agents.base import InteractionContext
    from src.agents.self_critique import run_self_critique

    ctx = InteractionContext(interaction_id="int_crit", pack=pack, channel="sim")
    ctx.slots = {}
    out = run_self_critique(ctx, strict=True)
    assert out["ok"] is False
    assert out["hard_fails"]


def test_self_critique_safety_requires_p1(reset_ops_db, seed_automotive_pack, pack):
    from src.agents.base import InteractionContext
    from src.agents.self_critique import run_self_critique

    ctx = InteractionContext(interaction_id="int_crit2", pack=pack, channel="sim")
    ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        "description": "fire",
    }
    ctx.safety_flags = {"escalation": True}
    ctx.severity = "Low"
    ctx.priority = 3
    out = run_self_critique(ctx)
    assert "safety_not_p1_or_critical" in out["hard_fails"]


@pytest.mark.asyncio
async def test_ingest_complaint_pipeline(reset_ops_db, seed_automotive_pack):
    from src.frontline.ingest import ingest_complaint

    out = await ingest_complaint(
        {
            "pack_id": "automotive_nhtsa",
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "SERVICE BRAKES",
            "description": "grinding when braking. Nobody is hurt. I am safe.",
        }
    )
    assert out["interaction_id"]
    assert out["state"] in ("DONE", "ABANDONED", "CLOSING", "ENRICHING", "COLLECTING")
    # Prefer case created when slots complete
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM interactions WHERE interaction_id = ?",
            [out["interaction_id"]],
        ).fetchone()[0]
    assert n == 1


@pytest.mark.asyncio
async def test_alert_rule_evaluate_and_apply(reset_ops_db):
    from src.frontline.alert_rules import (
        apply_triggered_rule,
        create_rule,
        evaluate_cluster_rule,
    )

    rule = create_rule(
        name="cluster-volume",
        pack_id="automotive_nhtsa",
        min_cases=3,
        min_severity="Medium",
        action="investigation",
    )
    ev = evaluate_cluster_rule(
        rule,
        pack_id="automotive_nhtsa",
        cluster_id=14,
        case_count=5,
        max_severity="Medium",
    )
    assert ev["triggered"] is True
    applied = await apply_triggered_rule(ev, title="test inv")
    assert applied.get("investigation_id")
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM investigations WHERE investigation_id = ?",
            [applied["investigation_id"]],
        ).fetchone()[0]
    assert n == 1


def test_cluster_rebuild(seed_automotive_pack):
    from src.ml_runtime.clustering import rebuild_clusters

    out = rebuild_clusters("automotive_nhtsa", k=3)
    assert out["clusters"] >= 1
    assert out["assignments"] >= 1


def test_prompt_registry_hash():
    from src.ai.prompts import load_prompt

    p = load_prompt("investigator_brief")
    assert p["prompt_hash"]
    assert p["version"]
    assert "RCA" in p["body"] or "brief" in p["body"].lower()


def test_dsr_export_delete(reset_ops_db):
    from src.frontline.dsr import delete_interaction, export_interaction
    from src.ledger import AgentAction, record_action

    iid = "int_dsr_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'completed')
            """,
            [iid, utc_now()],
        )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="state_transition",
            output_summary="dsr test",
        )
    )
    exp = export_interaction(iid)
    assert exp.get("interaction")
    assert exp.get("actions")
    deleted = delete_interaction(iid)
    assert deleted["ok"] is True
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM interactions WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
    assert n == 0


def test_audit_archive(reset_ops_db, tmp_path):
    from src.frontline.archive import build_audit_archive
    from src.ledger import AgentAction, record_action

    iid = "int_arch_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', '1', ?, 'web', 'completed')
            """,
            [iid, utc_now()],
        )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="greeting_emitted",
            output_summary="hi",
        )
    )
    man = build_audit_archive(iid, out_dir=tmp_path)
    assert man["bundle_sha256"]
    assert (tmp_path / Path(man["bundle_path"]).name).exists() or Path(
        man["bundle_path"]
    ).exists()
    assert man["ledger_chain_ok"] is True


def test_wallboard_and_digest_api(client, reset_ops_db):
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES ('int_wb_1', 'automotive_nhtsa', '1', ?, 'web', 'active')
            """,
            [utc_now()],
        )
        con.execute(
            """
            INSERT INTO cases (
                case_id, interaction_id, pack_id, created_at,
                category, description_summary, onset, severity,
                severity_source, priority, safety_flags,
                advisory_match_id, cluster_match_id, similar_record_count,
                investigation_id, status, followup_draft
            ) VALUES ('case_wb_1', 'int_wb_1', 'automotive_nhtsa', ?, 'SERVICE BRAKES',
                      'x', ?, 'Critical', 'rules', 1, '{}', NULL, 14, 2, NULL, 'open', '')
            """,
            [utc_now(), utc_now()],
        )
    r = client.get("/api/frontline/wallboard")
    assert r.status_code == 200
    body = r.json()
    assert "active_contacts" in body
    assert body["active_contacts"] >= 1
    assert body["p1_open"] >= 1
    assert "top_risk_clusters" in body

    d = client.post("/api/frontline/digest/run")
    assert d.status_code == 200
    assert d.json().get("ok") is True


def test_ingest_api(client, reset_ops_db, seed_automotive_pack):
    r = client.post(
        "/api/interactions/ingest",
        json={
            "pack_id": "automotive_nhtsa",
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "SERVICE BRAKES",
            "description": "soft pedal. Nobody hurt. Safe location.",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["interaction_id"]


def test_wallboard_max_severity_is_rank_not_lexical(reset_ops_db):
    """Critical+Low must report max_severity=Critical (not lexical MAX → Low)."""
    from src.frontline.wallboard import build_wallboard

    with ops_con() as con:
        for i, sev in enumerate(("Critical", "Low")):
            con.execute(
                """
                INSERT INTO cases (
                    case_id, interaction_id, pack_id, created_at,
                    category, description_summary, onset, severity,
                    severity_source, priority, safety_flags,
                    advisory_match_id, cluster_match_id, similar_record_count,
                    investigation_id, status, followup_draft
                ) VALUES (?, ?, 'automotive_nhtsa', ?, 'SERVICE BRAKES', 'x', ?,
                          ?, 'rules', 1, '{}', NULL, 99, 1, NULL, 'open', '')
                """,
                [f"case_sev_{i}", f"int_sev_{i}", utc_now(), utc_now(), sev],
            )
    wb = build_wallboard()
    hit = [c for c in wb["top_risk_clusters"] if c["cluster_id"] == 99]
    assert hit, wb["top_risk_clusters"]
    assert hit[0]["max_severity"] == "Critical", hit[0]


@pytest.mark.asyncio
async def test_confidence_escalate_sets_handoff_flag(
    reset_ops_db, seed_automotive_pack, pack, orchestrator_factory
):
    """escalate_low_confidence must set handoff_offered and emit handoff (not text-only)."""
    orch, hooks = orchestrator_factory()
    await orch.start()
    # Exhaust description re-asks via intake path through orchestrator
    orch.ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
    }
    orch.ctx._safety_asked = set(range(20))  # type: ignore[attr-defined]
    slot = next(s for s in pack.manifest.slot_frame if s.name == "description")
    orch.ctx.slot_attempts["description"] = (slot.max_re_asks or 1) + 5
    await orch.handle_customer_turn("")
    assert orch.ctx.handoff_offered is True
    assert hooks.handoff_offers >= 1


def test_stamp_prompt_use_inserts_and_survives_finalize(reset_ops_db):
    """Mid-call stamp must INSERT when no stamp row; finalize must not wipe hashes."""
    from src.ai.prompts import stamp_prompt_use
    from src.v3.governance import get_stamp, stamp_interaction

    iid = "int_stamp_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status)
            VALUES (?, 'automotive_nhtsa', 'packv1', ?, 'web', 'active')
            """,
            [iid, utc_now()],
        )
    # No stamp row yet
    assert get_stamp(iid) is None
    p = stamp_prompt_use(iid, prompt_name="intake_phrasing", used_llm=False)
    st = get_stamp(iid)
    assert st is not None, "stamp_prompt_use must INSERT a row"
    assert p["prompt_hash"] in (st.get("model_policy") or "")
    # Finalize stamp_interaction must preserve prompt hash
    stamp_interaction(iid)
    st2 = get_stamp(iid)
    assert st2 is not None
    assert p["prompt_hash"] in (st2.get("model_policy") or ""), st2.get("model_policy")


