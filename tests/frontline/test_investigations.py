"""Investigation auto-linking tests (per blueprint §15.2).

Covers:
  - First N-1 cases on a cluster → no investigation opened
  - Nth case (FRONTLINE_INVESTIGATION_MIN_CASES=3) → new investigation opened
  - N+1th case → links to the existing open investigation (case_count++)
"""

from __future__ import annotations

import pytest

from src.agents.base import InteractionContext
from src.agents.case_agent import CaseAgent
from src.config import settings


def _ctx(pack, cluster_id: int = 14, **slots) -> InteractionContext:
    """Build a ctx with a pre-populated investigation_brief pointing at a cluster."""
    ctx = InteractionContext(
        interaction_id="int_test_investigations",
        pack=pack,
    )
    ctx.slots.update(
        {
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "SERVICE BRAKES",
            "description": "Brakes grind at low speed",
            **slots,
        }
    )
    ctx.investigation_brief = {
        "cluster_id": cluster_id,
        "cluster_count": 5,
        "cluster_top_terms": ["grinding", "brakes", "cr-v"],
        "similar_record_count": 5,
        "similar_records": [],
        "spikes": [],
        "lead_time_weeks": 11,
    }
    return ctx


async def _run_case_agent(pack, cluster_id: int = 14) -> tuple[str, bool]:
    """Run the CaseAgent once and return (case_id, investigation_opened)."""
    ctx = _ctx(pack, cluster_id=cluster_id)
    res = await CaseAgent(ctx).run()
    return res["case_id"], res["investigation_opened"]


# ── Auto-open threshold (FRONTLINE_INVESTIGATION_MIN_CASES=3) ────────────────


async def test_first_two_cases_do_not_open_investigation(pack, reset_ops_db):
    """Cases 1 and 2 on a cluster → no investigation yet."""
    assert settings.investigation_min_cases == 3

    # Case 1
    case_id_1, opened_1 = await _run_case_agent(pack)
    assert case_id_1 is not None
    assert opened_1 is False, "first case must not open an investigation"

    # Case 2
    case_id_2, opened_2 = await _run_case_agent(pack)
    assert opened_2 is False, "second case must not open an investigation either"


async def test_third_case_opens_investigation(pack, reset_ops_db):
    """The 3rd case on a cluster opens a new investigation."""
    await _run_case_agent(pack)  # case 1
    await _run_case_agent(pack)  # case 2
    case_id_3, opened_3 = await _run_case_agent(pack)  # case 3 — threshold met
    assert opened_3 is True, "third case must open the investigation"


async def test_fourth_case_links_to_existing_investigation(pack, reset_ops_db):
    """The 4th case on a cluster links to the already-open investigation."""
    await _run_case_agent(pack)  # case 1
    await _run_case_agent(pack)  # case 2
    _, opened_3 = await _run_case_agent(pack)  # case 3 — opens inv_0001
    assert opened_3 is True

    ctx_4 = _ctx(pack)
    res_4 = await CaseAgent(ctx_4).run()
    assert res_4["investigation_opened"] is False, "4th case must link, not open"
    assert res_4["investigation_id"] is not None


async def test_investigation_counter_increments_on_link(pack, reset_ops_db):
    """When a case links to an existing investigation, case_count is incremented."""
    from src.data.warehouse import ops_con

    # Open the investigation (3 cases).
    await _run_case_agent(pack)
    await _run_case_agent(pack)
    await _run_case_agent(pack)  # opens inv_0001 with case_count=1

    # 4th case links.
    ctx_4 = _ctx(pack)
    res_4 = await CaseAgent(ctx_4).run()
    inv_id = res_4["investigation_id"]
    assert inv_id is not None

    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT case_count FROM investigations WHERE investigation_id = ?",
            [inv_id],
        ).fetchone()
    assert row[0] >= 2, "linked case must have incremented case_count"


# ── Different clusters are independent ────────────────────────────────────────


async def test_different_clusters_are_independent(pack, reset_ops_db):
    """Cases on cluster 14 and cluster 22 don't interfere."""
    # Two cases on cluster 14.
    await _run_case_agent(pack, cluster_id=14)
    await _run_case_agent(pack, cluster_id=14)

    # One case on cluster 22 — should NOT open an investigation.
    _, opened_22 = await _run_case_agent(pack, cluster_id=22)
    assert opened_22 is False

    # Third case on cluster 14 — opens.
    _, opened_14 = await _run_case_agent(pack, cluster_id=14)
    assert opened_14 is True


# ── No cluster match → no investigation ─────────────────────────────────────


async def test_no_cluster_no_investigation(pack, reset_ops_db):
    """If investigation_brief has no cluster_id, no investigation is created."""
    ctx = InteractionContext(
        interaction_id="int_test_no_cluster",
        pack=pack,
    )
    ctx.slots.update(
        {
            "entity_1": "2019",
            "entity_2": "HONDA",
            "entity_3": "CR-V",
            "category": "SERVICE BRAKES",
            "description": "Brakes grind",
        }
    )
    ctx.investigation_brief = None  # no cluster match
    res = await CaseAgent(ctx).run()
    assert res["investigation_id"] is None
    assert res["investigation_opened"] is False
    assert res["case_id"] is not None  # case still created
