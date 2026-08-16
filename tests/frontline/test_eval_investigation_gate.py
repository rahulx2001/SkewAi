"""Investigation gate isolation + ledger checks must not vacuous-pass."""

from __future__ import annotations

import pytest

from eval.frontline.personas import Persona
from eval.frontline.run_eval import (
    _check_ledger_completeness,
    run_investigation_auto_open_gate,
)


@pytest.mark.asyncio
async def test_investigation_gate_reports_honest_attempt_counts(reset_ops_db, seed_automotive_pack):
    """Gate detail uses actual attempts/successes (not a fixed planned string alone)."""
    empty = Persona(
        name="investigation_trigger",
        description="minimal for gate counters",
        turns=["hello only"],
    )
    gate = await run_investigation_auto_open_gate(
        pack_id="automotive_nhtsa",
        trigger_persona=empty,
        min_cases=2,
    )
    assert "attempts=" in gate.detail
    assert "successes=" in gate.detail
    assert "planned=2" in gate.detail
    assert "ran 3 cases" not in gate.detail
    assert gate.passed is False or "investigation_opened=" in gate.detail


@pytest.mark.asyncio
async def test_investigation_gate_resets_ops_before_running(reset_ops_db, seed_automotive_pack):
    """Gate runs its own attempts after an ops reset."""
    persona = Persona(
        name="investigation_trigger",
        description="minimal",
        turns=["x"],
    )
    gate = await run_investigation_auto_open_gate(
        pack_id="automotive_nhtsa",
        trigger_persona=persona,
        min_cases=1,
    )
    assert "attempts=1" in gate.detail
    assert gate.name == "investigation_auto_open"


def test_ledger_completeness_fails_for_missing_interaction(reset_ops_db):
    """Missing interaction_id must not vacuous-pass (empty turns => False)."""
    assert _check_ledger_completeness("missing-id-never-stored") is False
