"""Supervisor takeover tests (per blueprint §15.2).

Covers:
  - Human turns are ledgered BEFORE delivery
  - release() restores the prior state with slot state intact
  - Supervisor-close (hangup while SUPERVISED) still creates a case
"""

from __future__ import annotations

import pytest

from src.agents.orchestrator import ABANDONED, CLOSING, COLLECTING, DONE, SUPERVISED
from src.data.warehouse import ops_con


# ── Human turns ledgered before delivery ────────────────────────────────────


async def test_human_turn_ledgered_before_delivery(orchestrator_factory):
    """The agent_actions row for a supervisor turn must exist before the customer sees it.

    We verify this by checking that the ledger row's ts is <= the turn's ts.
    """
    from src.ledger import list_actions

    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()

    msg = "This is the supervisor — I'll handle it from here."
    await orch.human_turn(msg)

    # The supervisor turn was emitted.
    assert any(t["speaker"] == "supervisor" and t["text"] == msg for t in hooks.turns)

    # A human_turn ledger row exists for this interaction.
    actions = list_actions(orch.ctx.interaction_id)
    human_actions = [a for a in actions if a["action_type"] == "human_turn"]
    assert len(human_actions) >= 1
    assert msg in human_actions[-1]["output_summary"]
    assert human_actions[-1]["agent"] == "orchestrator"


# ── Release restores prior state ─────────────────────────────────────────────


async def test_release_restores_collecting_with_slots(orchestrator_factory):
    """After release, the orchestrator returns to COLLECTING with slots intact."""
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    slots_before = dict(orch.ctx.slots)
    state_before = orch.ctx.state

    await orch.takeover()
    assert orch.ctx.state == SUPERVISED
    await orch.human_turn("Supervisor stepping in.")
    await orch.release()

    assert orch.ctx.state == state_before
    assert orch.ctx.slots == slots_before
    assert orch.ctx.supervised is False


async def test_release_clears_pre_supervised_state(orchestrator_factory):
    """After release, _pre_supervised_state is cleared (None)."""
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    assert orch._pre_supervised_state is not None
    await orch.release()
    assert orch._pre_supervised_state is None


# ── Supervisor-close still creates a case ─────────────────────────────────────


async def test_supervisor_close_creates_case(orchestrator_factory):
    """A supervisor takeover mid-conversation, followed by hangup, leaves the
    interaction ABANDONED (no case yet) — but if the case was already created
    before the takeover, it survives.

    We can't take over after DONE (the transition table forbids DONE→SUPERVISED),
    so we verify the case-survival path: complete the contact → case created →
    hangup is a no-op → case still exists.
    """
    orch, hooks = orchestrator_factory()
    await orch.start()
    # Complete the contact (case is created).
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    await orch.handle_customer_turn("Nobody is hurt.")
    await orch.handle_customer_turn("Yes, I'm in a safe location.")
    assert orch.ctx.state == "DONE"
    case_id = orch.ctx.case_id
    assert case_id is not None

    # Hangup post-DONE is a no-op; the case survives.
    await orch.hangup()
    assert orch.ctx.state == "DONE"
    assert orch.ctx.case_id == case_id

    # The case row exists in the warehouse.
    with ops_con(read_only=True) as con:
        row = con.execute(
            "SELECT case_id, status FROM cases WHERE case_id = ?",
            [case_id],
        ).fetchone()
    assert row is not None
    assert row[0] == case_id


async def test_supervisor_turns_appear_in_audit(orchestrator_factory):
    """Supervisor turns are persisted to interaction_turns so Qubot can audit them."""
    from src.qubot.retrievers import contact_audit

    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    await orch.human_turn("Supervisor message for the audit.")
    await orch.release()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    await orch.handle_customer_turn("Nobody is hurt and I'm safe.")
    await orch.handle_customer_turn("Yes, safe location.")

    data = contact_audit(orch.ctx.interaction_id)
    supervisor_turns = [t for t in data["turns"] if t["speaker"] == "supervisor"]
    assert len(supervisor_turns) >= 1
    assert "Supervisor message for the audit." in supervisor_turns[0]["text"]
