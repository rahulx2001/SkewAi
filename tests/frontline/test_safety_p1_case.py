"""C-OPEN-1: kill-switch / safety flags → Critical severity + P1 on case."""

from __future__ import annotations

import pytest

from src.agents.case_agent import CaseAgent
from src.agents.base import InteractionContext
from src.data.warehouse import ops_con
from src.domains.loader import load_pack
from src.ids import new_ulid


@pytest.mark.asyncio
async def test_case_agent_safety_flags_force_critical_p1(reset_ops_db, pack):
    """CaseAgent enforces Critical/P1 when any safety flag is set (even Low defaults)."""
    iid = "int_safety_" + new_ulid()[:8]
    with ops_con() as con:
        from datetime import datetime, timezone

        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 't', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, pack.id, datetime.now(timezone.utc)],
        )
    ctx = InteractionContext(interaction_id=iid, pack=pack)
    ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        "description": "vehicle caught fire",
    }
    # Defaults that would wrongly ship without the floor:
    ctx.severity = "Low"
    ctx.priority = 3
    ctx.safety_flags = {"escalation": True, "fire": True}

    res = await CaseAgent(ctx).run()
    assert res["case_id"]
    assert ctx.severity == "Critical"
    assert ctx.priority == 1

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT severity, priority FROM cases WHERE case_id = ?",
            [res["case_id"]],
        ).fetchone()
    assert row is not None
    assert row[0] == "Critical"
    assert int(row[1]) == 1


@pytest.mark.asyncio
async def test_kill_switch_orchestrator_sets_critical_before_case(
    reset_ops_db, seed_automotive_pack, pack
):
    """Real kill-switch path through orchestrator → case is Critical/P1."""
    from src.agents.orchestrator import Orchestrator, OrchestratorHooks
    from src.data.warehouse import ops_con
    from datetime import datetime, timezone

    iid = "int_kill_" + new_ulid()[:8]
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 't', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, pack.id, datetime.now(timezone.utc)],
        )

    orch = Orchestrator(iid, pack, channel="web_text", hooks=OrchestratorHooks())
    await orch.start()
    # Fire kill-switch term from automotive pack escalation lexicon
    await orch.handle_customer_turn(
        "my car is on fire and I need help immediately", final=True
    )

    assert orch.ctx.safety_flags.get("escalation") or any(orch.ctx.safety_flags.values())
    assert orch.ctx.severity == "Critical"
    assert orch.ctx.priority == 1
    assert orch.ctx.case_id is not None

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT severity, priority FROM cases WHERE case_id = ?",
            [orch.ctx.case_id],
        ).fetchone()
    assert row[0] == "Critical"
    assert int(row[1]) == 1
