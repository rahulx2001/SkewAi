"""Tier-2/3 trust: drift, span claims, locker, elicitation, intercept, merkle, reproduce."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from src.data.timeutil import utc_now
from src.data.warehouse import apply_domain_schema, domain_con, ops_con
from src.enterprise.reproduce import reproduce_contact
from src.frontline.elicitation import (
    looks_like_confirmation,
    next_question,
    record_spoken_confirmation,
    register_question,
)
from src.frontline.live_intercept import intercept_contact, open_or_link_investigation
from src.ledger import AgentAction, record_action
from src.agents.base import InteractionContext
from src.agents.investigator import InvestigatorAgent
from src.agents.triage import score_severity
from src.ledger.merkle import collect_leaves, verify_completeness
from src.qubot.claims import BoundClaim, audit_bound_claims, load_bound_claims, store_bound_claims
from src.ml_runtime.anomalies import iso_week_label
from src.qubot.auditor import audit_interaction
from src.qubot.evidence_pin import detect_source_drift, pin_cited_records
from src.qubot.locker import (
    build_locker_bundle,
    sign_locker_bundle,
    verify_locker_bundle,
)


def test_source_drift_after_cited_row_edit(pack, reset_ops_db, seed_automotive_pack):
    rid = "NHTSA-100001"
    iid = "int_drift_1"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 'v', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, pack.id, utc_now()],
        )
    aid = record_action(
        AgentAction(
            interaction_id=iid,
            agent="investigator",
            action_type="similar_search",
            input_summary="cite",
            output_summary=f"similar {rid}",
            evidence_ids=[rid],
        )
    )
    assert detect_source_drift(aid) == []
    with domain_con(pack.id, read_only=False) as con:
        con.execute(
            "UPDATE records SET text = ? WHERE record_id = ?",
            ["MUTATED SOURCE TEXT", rid],
        )
    drifted = detect_source_drift(aid)
    assert drifted and drifted[0]["evidence_id"] == rid
    assert drifted[0]["reason"] == "source-drifted"

    # Unchanged second citation does not drift
    rid2 = "NHTSA-100002"
    aid2 = record_action(
        AgentAction(
            interaction_id=iid,
            agent="investigator",
            action_type="similar_search",
            evidence_ids=[rid2],
        )
    )
    assert detect_source_drift(aid2) == []


@pytest.mark.asyncio
async def test_auditor_marks_source_drifted(pack, reset_ops_db, seed_automotive_pack):
    rid = "NHTSA-200001"
    iid = "int_drift_audit"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
            """,
            [iid, pack.id, utc_now()],
        )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="investigator",
            action_type="similar_search",
            evidence_ids=[rid],
        )
    )
    with domain_con(pack.id, read_only=False) as con:
        con.execute("UPDATE records SET text = 'changed after pin' WHERE record_id = ?", [rid])
    result = await audit_interaction(iid, write_report=False)
    assert result.overall_verdict == "source-drifted"
    assert any(v.verdict == "source-drifted" for v in result.action_verdicts)


def test_span_claim_pass_and_planted_reject():
    text = "grinding noise when braking at low speed"
    snaps = [
        {
            "evidence_id": "NHTSA-100001",
            "body_json": json.dumps({"text": text, "record_id": "NHTSA-100001"}),
        }
    ]
    start = text.index("grinding noise")
    end = start + len("grinding noise")
    ok = audit_bound_claims(
        [BoundClaim("grinding noise", "NHTSA-100001", start, end)],
        snaps,
    )
    assert ok.ok is True
    assert ok.overall == "grounded"
    planted = audit_bound_claims(
        [BoundClaim("engine fire", "NHTSA-100001", start, end)],
        snaps,
    )
    assert planted.ok is False
    assert planted.overall == "mismatch"
    assert planted.rejected


@pytest.mark.asyncio
async def test_auditor_rejects_planted_span_claim(pack, reset_ops_db, seed_automotive_pack):
    rid = "NHTSA-100001"
    iid = "int_span_audit"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
            """,
            [iid, pack.id, utc_now()],
        )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="investigator",
            action_type="brief_written",
            output_summary="engine fire cited",
            evidence_ids=[rid],
            claims=[
                {
                    "claim_text": "engine fire",
                    "evidence_id": rid,
                    "span_start": 0,
                    "span_end": 11,
                }
            ],
        )
    )
    result = await audit_interaction(iid, write_report=False)
    assert result.overall_verdict == "mismatch"
    assert any(
        "unsupported-claim" in (v.detail or "") for v in result.action_verdicts
    )


@pytest.mark.asyncio
async def test_investigator_emits_span_claims_planted_brief_goes_red(
    pack, reset_ops_db, seed_automotive_pack
):
    iid = "int_inv_claims"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 'v', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, pack.id, utc_now()],
        )
    ctx = InteractionContext(interaction_id=iid, pack=pack)
    ctx.slots.update(
        {
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "SERVICE BRAKES",
            "description": "grinding when braking",
        }
    )
    res = await InvestigatorAgent(ctx).run()
    assert not res.get("skipped")
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT action_id FROM agent_actions
            WHERE interaction_id = ? AND action_type = 'brief_written'
            """,
            [iid],
        ).fetchone()
    assert row, "investigator must write brief_written"
    claims = load_bound_claims(row[0])
    assert claims, "investigator must persist span-bound claims on the brief"
    store_bound_claims(
        row[0],
        [
            {
                "claim_text": "engine fire",
                "evidence_id": claims[0].evidence_id,
                "span_start": 0,
                "span_end": 11,
            }
        ],
    )
    result = await audit_interaction(iid, write_report=False)
    assert result.overall_verdict == "mismatch"
    assert any("unsupported-claim" in (v.detail or "") for v in result.action_verdicts)


@pytest.mark.asyncio
async def test_spoken_confirmation_does_not_red_audit(pack, reset_ops_db):
    iid = "int_confirm_audit"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
            """,
            [iid, pack.id, utc_now()],
        )
    record_spoken_confirmation(
        iid, "correct", confirmed=True, question_id="dq_not_a_warehouse_row"
    )
    result = await audit_interaction(iid, write_report=False)
    sc = [v for v in result.action_verdicts if v.action_type == "spoken_confirmation"]
    assert sc
    assert sc[0].verdict == "grounded", sc[0].detail
    assert result.overall_verdict != "mismatch"


def test_evidence_locker_sign_verify_and_tamper(pack, reset_ops_db):
    iid = "int_locker_1"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
            """,
            [iid, pack.id, utc_now()],
        )
    record_action(
        AgentAction(
            interaction_id=iid,
            agent="orchestrator",
            action_type="interaction_ended",
            output_summary="done",
        )
    )
    bundle = sign_locker_bundle(build_locker_bundle(iid))
    assert verify_locker_bundle(bundle)["ok"] is True
    bad = dict(bundle)
    bad["interaction_id"] = "int_TAMPER"
    assert verify_locker_bundle(bad)["ok"] is False
    bad_sig = dict(bundle)
    bad_sig["signature"] = "00" * 64
    assert verify_locker_bundle(bad_sig)["ok"] is False


@pytest.mark.asyncio
async def test_elicitation_confirm_and_live_intercept(
    orchestrator_factory, pack, reset_ops_db, seed_automotive_pack, tmp_path, monkeypatch
):
    register_question(
        pack.id,
        "It only happens when the brakes are cold — correct?",
        category="SERVICE BRAKES",
        entity_2="HONDA",
    )
    q = next_question(pack.id, {"category": "SERVICE BRAKES", "entity_2": "HONDA"})
    assert q is not None
    assert "cold" in q["prompt"]

    orch, hooks = orchestrator_factory()
    await orch.start()
    orch.ctx.slots.update(
        {
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "SERVICE BRAKES",
            "description": "grinding when braking",
        }
    )
    # This test is the diagnostic-elicitation path, not spoken safety.
    n_safety = len(orch.ctx.pack.manifest.safety.safety_questions or [])
    orch.ctx.slots["__safety_questions_asked__"] = ",".join(
        str(i) for i in range(n_safety)
    )
    await orch.handle_customer_turn("still grinding this morning")
    asked = [t["text"] for t in hooks.turns if "cold" in t["text"]]
    assert asked, "diagnostic question must be asked on the turn path"
    await orch.handle_customer_turn("correct")
    with ops_con(read_only=True) as con:
        conf = con.execute(
            """
            SELECT action_type, row_hash, prev_hash FROM agent_actions
            WHERE interaction_id = ? AND action_type = 'spoken_confirmation'
            """,
            [orch.ctx.interaction_id],
        ).fetchall()
    assert conf, "spoken confirmation must be ledgered"
    assert conf[0][1]  # row_hash
    assert conf[0][2]  # prev_hash chained

    # Linked path: spike records → intercept opens investigation before we close.
    with domain_con(pack.id, read_only=False) as con:
        apply_domain_schema(con)
        for w in (17, 18, 19):
            con.execute(
                """
                INSERT OR REPLACE INTO records
                (record_id, received_at, entity_2, entity_3, category, text, source)
                VALUES (?, ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')
                """,
                [f"QWK-{w}", datetime.fromisocalendar(2024, w, 1), f"quiet {w}"],
            )
        week = datetime.fromisocalendar(2024, 20, 1)
        for i in range(25):
            con.execute(
                """
                INSERT OR REPLACE INTO records
                (record_id, received_at, entity_2, entity_3, category, text, source)
                VALUES (?, ?, 'HONDA', 'CR-V', 'SERVICE BRAKES', ?, 'NHTSA')
                """,
                [f"SPIKE-{i}", week, f"spike grind {i}"],
            )
    hit = intercept_contact(orch.ctx)
    assert hit["anomalous"] is True
    assert hit["investigation_id"]
    with ops_con(read_only=True) as con:
        inv = con.execute(
            "SELECT investigation_id FROM investigations WHERE investigation_id = ?",
            [hit["investigation_id"]],
        ).fetchone()
    assert inv is not None


def test_merkle_omission_fails_and_complete_verifies(pack, reset_ops_db):
    for iid, n in (("int_merkle_a", 2), ("int_merkle_b", 1)):
        with ops_con() as con:
            con.execute(
                """
                INSERT INTO interactions
                (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
                VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0)
                """,
                [iid, pack.id, utc_now()],
            )
        for i in range(n):
            record_action(
                AgentAction(
                    interaction_id=iid,
                    agent="orchestrator",
                    action_type="state_transition",
                    output_summary=f"step {i}",
                )
            )
    stored = collect_leaves(interaction_ids=["int_merkle_a", "int_merkle_b"])
    assert len(stored) >= 3
    full = verify_completeness(interaction_ids=["int_merkle_a", "int_merkle_b"])
    assert full["ok"] is True
    omitted = verify_completeness(
        interaction_ids=["int_merkle_a", "int_merkle_b"],
        omit_interaction="int_merkle_b",
    )
    assert omitted["ok"] is False
    assert omitted["leaf_count"] < omitted["expected_count"]
    assert omitted["root"] != omitted["full_root"]


def test_reproduce_same_severity(pack, reset_ops_db):
    iid = "int_repro_1"
    # VISIBILITY is not a pack-rule Medium category; "window rattle" hits the
    # JSON overlay (TriageAgent model path) and must stay Medium on REPRODUCE.
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status,
             supervised, llm_calls, entity_1, entity_2, entity_3, category, description)
            VALUES (?, ?, 'v', ?, 'web_text', 'completed', FALSE, 0,
                    '2019', 'HONDA', 'CR-V', 'VISIBILITY', 'window rattle')
            """,
            [iid, pack.id, utc_now()],
        )
    ctx = InteractionContext(interaction_id=iid, pack=pack)
    ctx.slots.update(
        {
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "VISIBILITY",
            "description": "window rattle",
        }
    )
    expected, source, _reason = score_severity(ctx)
    assert expected == "Medium"
    assert source == "model"
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO cases
            (case_id, interaction_id, pack_id, created_at, category,
             description_summary, onset, severity, severity_source, priority,
             safety_flags, similar_record_count, status)
            VALUES ('case_repro', ?, ?, ?, 'VISIBILITY', 'window rattle', ?,
                    ?, ?, 3, '{}', 0, 'open')
            """,
            [iid, pack.id, utc_now(), utc_now(), expected, source],
        )
    out = reproduce_contact(iid)
    assert out["severity"] == expected
    assert out["severity"] == out["original_severity"]
    assert out["severity_matches_original"] is True
    assert "investigation_should_open" in out
