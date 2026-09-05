"""Safety and severity stay non-neural even when embeddings are on or broken."""

from __future__ import annotations

import pytest

from src.agents.case_agent import CaseAgent
from src.agents.base import InteractionContext
from src.data.warehouse import ops_con
from src.ids import new_ulid


@pytest.mark.asyncio
async def test_safety_floor_with_semantic_mode_and_no_model(
    reset_ops_db, pack, monkeypatch
):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "semantic")
    monkeypatch.setenv("FRONTLINE_EMBEDDING_TOY", "1")
    monkeypatch.setenv("FRONTLINE_ACTIVE_CLUSTER_BUILD_ID", "missing")
    iid = "int_safeml_" + new_ulid()[:8]
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
    ctx.severity = "Low"
    ctx.priority = 3
    ctx.safety_flags = {"escalation": True, "fire": True}
    ctx.severity_source = "rules"
    res = await CaseAgent(ctx).run()
    assert res["case_id"]
    assert ctx.severity == "Critical"
    assert ctx.priority == 1
    assert ctx.severity_source == "rules"


@pytest.mark.asyncio
async def test_kill_switch_ignores_embedding_failure(
    reset_ops_db, seed_automotive_pack, pack, monkeypatch
):
    monkeypatch.setenv("FRONTLINE_EMBEDDING_MODE", "semantic")
    monkeypatch.delenv("FRONTLINE_EMBEDDING_TOY", raising=False)
    monkeypatch.setenv("FRONTLINE_SEMANTIC_ARTIFACT_DIR", "/tmp/no-such-minilm")
    from src.agents.orchestrator import Orchestrator, OrchestratorHooks
    from datetime import datetime, timezone

    iid = "int_killml_" + new_ulid()[:8]
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
    await orch.handle_customer_turn("my car is on fire and I need help immediately", final=True)
    assert orch.ctx.severity == "Critical"
    assert orch.ctx.priority == 1
    assert orch.ctx.case_id is not None
