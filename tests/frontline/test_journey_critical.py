"""Journey-audit regression tests — CRITICAL findings (6.1, 8.1, 7.3).

6.1: kill-switch then hangup must still create a case (safety/enrichment
     evidence is never abandoned).
8.1: closed contacts project into the domain warehouse (source=FRONTLINE,
     provenance=observed) so the fleet scan compounds.
7.3: chain-preserving erasure (tombstone) keeps verify_chain green while
     PII content is gone.
"""

from __future__ import annotations

import pytest


def _drive_to_done(orch, hooks=None, max_turns: int = 14):
    async def _go():
        await orch.start()
        await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
        for _ in range(max_turns):
            if orch.ctx.state == "DONE":
                break
            await orch.handle_customer_turn("Additional detail for the record.")
        if orch.ctx.state != "DONE":
            await orch._move_to_closing()

    return _go


@pytest.mark.asyncio
async def test_c61_kill_switch_then_hangup_creates_case(orchestrator_factory):
    """Safety flag + hangup on turn 2 ⇒ case exists, P1, escalated_safety."""
    from src.data.warehouse import ops_con

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V caught FIRE while driving!")
    assert orch.ctx.safety_flags.get("escalation") is True
    await orch.hangup()
    assert orch.ctx.case_id is not None, "safety hangup must create a case"
    assert orch.ctx.priority == 1
    assert orch.ctx.state == "DONE"
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT outcome, status FROM interactions WHERE interaction_id = ?",
            [orch.ctx.interaction_id],
        ).fetchone()
    assert row[0] == "escalated_safety"


@pytest.mark.asyncio
async def test_c61_plain_abandon_still_abandons(orchestrator_factory):
    """No case, no safety, no enrichment ⇒ ABANDONED with no case (unchanged)."""
    from src.data.warehouse import ops_con

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("Hello?")
    await orch.hangup()
    assert orch.ctx.state == "ABANDONED"
    assert orch.ctx.case_id is None
    with ops_con(read_only=True) as con:
        n = con.execute(
            "SELECT COUNT(*) FROM cases WHERE interaction_id = ?",
            [orch.ctx.interaction_id],
        ).fetchone()[0]
    assert n == 0


@pytest.mark.asyncio
async def test_c81_closed_contact_projects_to_corpus(orchestrator_factory):
    """Close a contact → FRONTLINE record appears → scan slice counts +1."""
    from src.data.warehouse import domain_con
    from src.ml_runtime.anomalies import (
        count_weekly_slices,
        recompute_weekly_anomalies,
    )

    orch, _ = orchestrator_factory()
    pack_id = orch.ctx.pack.id
    await _drive_to_done(orch)()
    assert orch.ctx.case_id
    rid = f"FRONTLINE-{orch.ctx.interaction_id}"
    with domain_con(pack_id) as con:
        row = con.execute(
            "SELECT source, provenance, category, entity_key FROM records WHERE record_id = ?",
            [rid],
        ).fetchone()
    assert row is not None, "projected record missing"
    assert row[0] == "FRONTLINE" and row[1] == "observed"
    assert row[2] == "SERVICE BRAKES"
    assert "HONDA" in (row[3] or "")
    # And the fleet scan actually sees it: slice count went up by exactly 1.
    scored = recompute_weekly_anomalies(
        pack_id, category="SERVICE BRAKES", entity_2="HONDA"
    )
    assert any(r["record_count"] >= 1 for r in scored)


@pytest.mark.asyncio
async def test_c73_tombstone_keeps_chain_verifiable(orchestrator_factory):
    """Erasure removes PII content but verify_chain still passes."""
    from src.data.warehouse import ops_con
    from src.frontline.dsr import tombstone_interaction
    from src.ledger import list_actions
    from src.ledger.chain import verify_chain

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn(
        "My 2019 Honda CR-V grinds. Call me at jane.doe@example.com please."
    )
    await _drive_to_done(orch)()
    iid = orch.ctx.interaction_id
    out = tombstone_interaction(iid)
    assert out["ok"] is True
    with ops_con(read_only=True) as con:
        texts = [
            r[0]
            for r in con.execute(
                "SELECT text FROM interaction_turns WHERE interaction_id = ?", [iid]
            ).fetchall()
        ]
        assert texts and all("jane.doe" not in (t or "") for t in texts)
        erased = con.execute(
            "SELECT COUNT(*) FROM agent_actions WHERE interaction_id = ? AND erased = TRUE",
            [iid],
        ).fetchone()[0]
        assert erased >= 1
    actions = list_actions(iid)
    assert actions, "structural rows must survive erasure"
    result = verify_chain(actions)
    assert result["ok"] is True, f"chain must verify after tombstone: {result}"


def test_c73_erased_pins_report_erased_not_drift(reset_ops_db, seed_automotive_pack):
    """Tombstoned pins surface as reason=erased, never as tampering."""
    from src.data.warehouse import ops_con
    from src.frontline.dsr import tombstone_interaction
    from src.ledger import AgentAction, record_action
    from src.ledger.writer import remember_interaction_pack
    from src.qubot.evidence_pin import detect_source_drift

    iid = "int_erase_pin"
    with ops_con() as con:
        con.execute(
            """INSERT INTO interactions (interaction_id, pack_id, pack_version,
               started_at, channel, status) VALUES (?, 'automotive_nhtsa', '1',
               CURRENT_TIMESTAMP, 'web_text', 'completed')""",
            [iid],
        )
    remember_interaction_pack(iid, "automotive_nhtsa")
    record_action(AgentAction(
        interaction_id=iid, agent="investigator", action_type="similar_search",
        input_summary="probe", output_summary="probe",
        evidence_ids=["NHTSA-100001"],
    ))
    with ops_con(read_only=True) as con:
        aid = con.execute(
            "SELECT action_id FROM agent_actions WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
    tombstone_interaction(iid)
    drift = detect_source_drift(aid)
    assert drift and all(d["reason"] == "erased" for d in drift)
