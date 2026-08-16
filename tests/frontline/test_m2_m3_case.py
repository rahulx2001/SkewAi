"""M2 investigation race + M3 case/ledger atomicity."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agents.base import InteractionContext
from src.agents.case_agent import CaseAgent
from src.data.warehouse import ops_con
from src.ids import new_ulid


def _seed_interaction(iid: str, pack_id: str = "automotive_nhtsa") -> None:
    with ops_con() as con:
        con.execute(
            """
            INSERT INTO interactions
            (interaction_id, pack_id, pack_version, started_at, channel, status, supervised, llm_calls)
            VALUES (?, ?, 't', ?, 'web_text', 'active', FALSE, 0)
            """,
            [iid, pack_id, datetime.now(timezone.utc)],
        )


def _ctx(pack, iid: str, cluster_id: int = 14) -> InteractionContext:
    ctx = InteractionContext(interaction_id=iid, pack=pack)
    ctx.slots = {
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        "description": "grinding brakes",
    }
    ctx.investigation_brief = {
        "cluster_id": cluster_id,
        "similar_record_count": 3,
        "cluster_top_terms": ["brake", "grind"],
        "cluster_count": 5,
    }
    ctx.severity = "Medium"
    ctx.priority = 2
    return ctx


@pytest.mark.asyncio
async def test_two_threshold_crossings_one_open_investigation(
    reset_ops_db, pack, monkeypatch
):
    """M2: two case creates that both cross the threshold → one open inv."""
    from src.agents import case_agent as ca_mod

    # First case already on cluster so next two cross min_cases=3 with +1 each.
    # With min_cases=1 both would open without lock; use min_cases=1 so each
    # create is over threshold when alone, and recheck prevents double-open.
    monkeypatch.setattr(
        ca_mod,
        "settings",
        SimpleNamespace(investigation_min_cases=1),
    )

    cluster_id = 99
    iid1 = "int_m2a_" + new_ulid()[:8]
    iid2 = "int_m2b_" + new_ulid()[:8]
    _seed_interaction(iid1, pack.id)
    _seed_interaction(iid2, pack.id)

    r1 = await CaseAgent(_ctx(pack, iid1, cluster_id)).run()
    r2 = await CaseAgent(_ctx(pack, iid2, cluster_id)).run()

    assert r1["investigation_id"]
    assert r2["investigation_id"]
    assert r1["investigation_id"] == r2["investigation_id"]
    assert r1["investigation_opened"] is True
    assert r2["investigation_opened"] is False  # linked to existing

    with ops_con(read_only=True) as con:
        n = con.execute(
            """
            SELECT COUNT(*) FROM investigations
            WHERE pack_id = ? AND cluster_id = ? AND status = 'open'
            """,
            [pack.id, cluster_id],
        ).fetchone()[0]
    assert n == 1


@pytest.mark.asyncio
async def test_case_and_case_created_ledger_atomic(reset_ops_db, pack):
    """M3: successful create → both case row and case_created ledger exist."""
    iid = "int_m3_" + new_ulid()[:8]
    _seed_interaction(iid, pack.id)
    res = await CaseAgent(_ctx(pack, iid)).run()
    assert res["case_id"]

    with ops_con(read_only=True) as con:
        case = con.execute(
            "SELECT case_id FROM cases WHERE case_id = ?", [res["case_id"]]
        ).fetchone()
        ledger = con.execute(
            """
            SELECT action_type FROM agent_actions
            WHERE case_id = ? AND action_type = 'case_created'
            """,
            [res["case_id"]],
        ).fetchone()
    assert case is not None
    assert ledger is not None


@pytest.mark.asyncio
async def test_case_insert_rollback_on_ledger_failure(reset_ops_db, pack):
    """If ledger insert fails inside the transaction, case row must not remain."""
    iid = "int_m3fail_" + new_ulid()[:8]
    _seed_interaction(iid, pack.id)
    ctx = _ctx(pack, iid)

    from src.ledger import writer as lw

    real_insert = lw._insert_action_row

    def boom(con, action):
        if action.action_type == "case_created":
            raise RuntimeError("forced ledger failure")
        return real_insert(con, action)

    with patch.object(lw, "_insert_action_row", side_effect=boom):
        with pytest.raises(RuntimeError, match="forced ledger failure"):
            await CaseAgent(ctx).run()

    with ops_con(read_only=True) as con:
        n_cases = con.execute(
            "SELECT COUNT(*) FROM cases WHERE interaction_id = ?", [iid]
        ).fetchone()[0]
        n_actions = con.execute(
            """
            SELECT COUNT(*) FROM agent_actions
            WHERE interaction_id = ? AND action_type = 'case_created'
            """,
            [iid],
        ).fetchone()[0]
    assert n_cases == 0
    assert n_actions == 0
