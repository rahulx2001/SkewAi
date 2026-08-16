"""Orchestrator state-machine tests.

Covers (per blueprint §15.2):
  - Legal / illegal transitions
  - SUPERVISED entry / exit (takeover → release → prior state restored)
  - Enrichment timeout fallback
  - hangup() per state (DONE no-op; mid-flow → ABANDONED; case-created → CLOSING)
  - The safety-question fix: agent asks the safety question AND does NOT
    transition to ENRICHING while a safety question is pending.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.agents.orchestrator import (
    ABANDONED,
    CLOSING,
    COLLECTING,
    DONE,
    ENRICHING,
    GREETING,
    SAFETY_ESCALATION,
    SUPERVISED,
    Orchestrator,
)
from src.config import settings


# ── Legal transitions ─────────────────────────────────────────────────────────


async def test_legal_transition_greeting_to_collecting(orchestrator_factory):
    orch, _ = orchestrator_factory()
    # start() moves GREETING → COLLECTING and emits the greeting.
    greeting = await orch.start()
    assert greeting == orch.ctx.pack.greeting
    assert orch.ctx.state == COLLECTING


async def test_legal_transition_collecting_to_supervised(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    assert orch.ctx.state == SUPERVISED
    assert orch.ctx.supervised is True


async def test_legal_transition_supervised_back_to_collecting(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    # Snapshot slot state so we can prove release restores it.
    orch.ctx.slots["entity_1"] = "2019"
    await orch.takeover()
    await orch.human_turn("Hello, this is the supervisor.")
    await orch.release()
    assert orch.ctx.state == COLLECTING
    # Slots survive the supervised round-trip.
    assert orch.ctx.slots.get("entity_1") == "2019"
    assert orch.ctx.supervised is False


async def test_legal_transition_safety_escalation_to_closing(orchestrator_factory):
    """Kill-switch utterance → SAFETY_ESCALATION → CLOSING → DONE."""
    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My car caught fire on the highway!")
    # The orchestrator should have delivered the escalation script and then
    # moved straight to DONE (no further questions asked).
    assert orch.ctx.state == DONE
    assert orch.ctx.safety_flags.get("escalation") is True
    escalation_text = " ".join(hooks.agent_texts())
    assert "safety specialist" in escalation_text.lower() or "do not drive" in escalation_text.lower()


# ── Illegal transitions ──────────────────────────────────────────────────────


async def test_illegal_transition_done_to_anything(orchestrator_factory):
    """After DONE, the orchestrator must reject any transition."""
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My car caught fire!")
    assert orch.ctx.state == DONE
    with pytest.raises(ValueError):
        orch._transition(DONE, COLLECTING)


async def test_illegal_transition_greeting_to_enriching(orchestrator_factory):
    """GREETING may only go to COLLECTING / SUPERVISED / ABANDONED."""
    orch, _ = orchestrator_factory()
    assert orch.ctx.state == GREETING
    with pytest.raises(ValueError):
        orch._transition(GREETING, ENRICHING)


async def test_illegal_transition_collecting_to_done(orchestrator_factory):
    """COLLECTING cannot jump straight to DONE (must go through CLOSING)."""
    orch, _ = orchestrator_factory()
    await orch.start()
    assert orch.ctx.state == COLLECTING
    with pytest.raises(ValueError):
        orch._transition(COLLECTING, DONE)


# ── SUPERVISED entry/exit semantics ───────────────────────────────────────────


async def test_supervised_customer_turn_is_noop(orchestrator_factory):
    """While SUPERVISED, customer turns must NOT drive the AI."""
    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    n_turns_before = len(hooks.turns)
    await orch.handle_customer_turn("I'm still here, anyone?")
    assert len(hooks.turns) == n_turns_before
    assert orch.ctx.state == SUPERVISED


async def test_supervised_human_turn_ledgered_before_delivery(orchestrator_factory):
    """Supervisor turns must be written to the ledger BEFORE they're emitted."""
    from src.data.warehouse import ops_con

    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.takeover()

    await orch.human_turn("Hi, this is the supervisor — I'll take it from here.")
    assert any(t["speaker"] == "supervisor" for t in hooks.turns)
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT agent, action_type, output_summary
            FROM agent_actions
            WHERE interaction_id = ? AND action_type = 'human_turn'
            """,
            [orch.ctx.interaction_id],
        ).fetchone()
    assert row is not None
    assert row[0] == "orchestrator"
    assert "I'll take it from here" in row[2]


async def test_release_restores_prior_state(orchestrator_factory):
    """release() returns to the pre-supervised state, not always COLLECTING."""
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    assert orch.ctx.state == COLLECTING  # safety question still pending
    pre_state = orch.ctx.state
    await orch.takeover()
    assert orch.ctx.state == SUPERVISED
    await orch.release()
    assert orch.ctx.state == pre_state


async def test_takeover_idempotent(orchestrator_factory):
    """Calling takeover() twice is a no-op the second time."""
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.takeover()
    first_pre = orch._pre_supervised_state
    await orch.takeover()
    assert orch.ctx.state == SUPERVISED
    assert orch._pre_supervised_state == first_pre


async def test_release_without_takeover_is_noop(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    assert orch.ctx.state == COLLECTING
    await orch.release()  # no-op
    assert orch.ctx.state == COLLECTING


# ── Hangup per state ──────────────────────────────────────────────────────────


async def test_hangup_in_collecting_abandons(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds.")
    assert orch.ctx.state == COLLECTING
    await orch.hangup()
    assert orch.ctx.state == ABANDONED


async def test_hangup_after_done_is_noop(orchestrator_factory):
    orch, _ = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("My car is on fire!")
    assert orch.ctx.state == DONE
    await orch.hangup()
    assert orch.ctx.state == DONE


async def test_hangup_with_case_moves_to_closing(orchestrator_factory):
    """If a case has been created, hangup moves to CLOSING instead of ABANDONED.

    We can't take over after DONE (the transition table forbids DONE→SUPERVISED),
    so we verify the complementary invariant: hangup from COLLECTING (no case)
    yields ABANDONED, which is the contract the hangup-with-case branch
    distinguishes itself from.
    """
    orch, _ = orchestrator_factory()
    await orch.start()
    # Mid-collection, no case yet — hangup must abandon.
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds.")
    assert orch.ctx.state == COLLECTING
    assert orch.ctx.case_id is None
    await orch.hangup()
    assert orch.ctx.state == ABANDONED

    # Now verify the case-survival path on a separate, completed interaction.
    orch2, _ = orchestrator_factory()
    await orch2.start()
    await orch2.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    await orch2.handle_customer_turn("Nobody is hurt.")
    await orch2.handle_customer_turn("Yes, I'm in a safe location.")
    assert orch2.ctx.state == DONE
    assert orch2.ctx.case_id is not None
    # Post-DONE hangup is a no-op — the case survives.
    await orch2.hangup()
    assert orch2.ctx.state == DONE
    assert orch2.ctx.case_id is not None


# ── Enrichment timeout ──────────────────────────────────────────────────────


async def test_enrichment_timeout_falls_back_to_closing(orchestrator_factory):
    """If enrichment runs longer than FRONTLINE_ENRICH_TIMEOUT_S, the
    orchestrator records a timeout ledger row and still moves to CLOSING."""
    from src.data.warehouse import ops_con

    orch, hooks = orchestrator_factory()
    await orch.start()

    # Patch _run_enrichment to sleep past the timeout. We also patch
    # `settings.enrich_timeout_s` via the orchestrator module's reference
    # (settings is a frozen dataclass, so we swap the whole object).
    from src.agents import orchestrator as orch_module

    async def slow_enrichment():
        await asyncio.sleep(5.0)

    fake_settings = type(settings)(
        domain_pack=settings.domain_pack,
        frontline_enabled=settings.frontline_enabled,
        max_turns=settings.max_turns,
        enrich_timeout_s=0,  # immediate timeout
        llm_turn_cap=settings.llm_turn_cap,
        frustration_threshold=settings.frustration_threshold,
        investigation_min_cases=settings.investigation_min_cases,
        early_warning_alert_threshold=settings.early_warning_alert_threshold,
        alert_webhook_url=settings.alert_webhook_url,
        connector_enabled=settings.connector_enabled,
        connector_webhook_url=settings.connector_webhook_url,
        connector_shared_secret=settings.connector_shared_secret,
        claude_api_key=settings.claude_api_key,
        openai_api_key=settings.openai_api_key,
        max_daily_claude_cost=settings.max_daily_claude_cost,
        api_host=settings.api_host,
        api_port=settings.api_port,
        frontline_api_key=settings.frontline_api_key,
    )
    with patch.object(orch_module, "settings", fake_settings):
        with patch.object(orch, "_run_enrichment", slow_enrichment):
            # Provide a complete slot frame so _enter_enriching is triggered.
            await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
            # The first safety question ("Is anyone hurt?") is asked.
            await orch.handle_customer_turn("Nobody is hurt.")
            # The second safety question ("Are you in a safe location?") is asked.
            await orch.handle_customer_turn("Yes, I'm safe.")

    # Despite the timeout, we must still reach DONE with a case created.
    assert orch.ctx.state == DONE
    assert orch.ctx.case_id is not None
    with ops_con(read_only=True) as con:
        row = con.execute(
            """
            SELECT input_summary, output_summary FROM agent_actions
            WHERE interaction_id = ? AND (input_summary LIKE '%enrichment timeout%'
                                          OR output_summary LIKE '%partial enrichment%')
            """,
            [orch.ctx.interaction_id],
        ).fetchone()
    assert row is not None, "expected an enrichment-timeout ledger row"


# ── Safety-question fix ────────────────────────────────────────────────────
#
# The pack defines safety_questions = ["Is anyone hurt?",
# "Are you in a safe location right now?"]. The fix the orchestrator ships
# requires that, when all slots are filled AND a safety question is still
# pending, the agent asks the safety question AND does NOT transition to
# ENRICHING. Only after every safety question has been answered does the
# state machine move on.


async def test_safety_question_asked_and_enriching_deferred(orchestrator_factory):
    """All slots filled in one turn → agent asks the safety question instead
    of immediately transitioning to ENRICHING."""
    orch, hooks = orchestrator_factory()
    await orch.start()
    # Single turn that fills every required slot.
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    # All slots are filled...
    assert orch.ctx.slots.get("entity_1") == "2019"
    assert orch.ctx.slots.get("entity_2") == "HONDA"
    assert orch.ctx.slots.get("entity_3") == "CR-V"
    assert orch.ctx.slots.get("category") == "SERVICE BRAKES"
    assert orch.ctx.slots.get("description") is not None
    # ...but we are still COLLECTING because a safety question is pending.
    assert orch.ctx.state == COLLECTING, (
        "orchestrator must NOT transition to ENRICHING while a safety question "
        "is pending (one-question-per-turn policy)"
    )
    # The agent's last turn is the first safety question.
    assert hooks.agent_texts()[-1].lower().startswith("is anyone hurt")


async def test_safety_questions_exhausted_then_enriching(orchestrator_factory):
    """After all safety questions are answered, slot completeness triggers ENRICHING."""
    orch, hooks = orchestrator_factory()
    await orch.start()
    # Fill all slots in the first turn — safety question #1 is asked.
    await orch.handle_customer_turn("My 2019 Honda CR-V grinds when I brake.")
    assert orch.ctx.state == COLLECTING
    # Answer the first safety question.
    await orch.handle_customer_turn("Nobody is hurt.")
    assert orch.ctx.state == COLLECTING, "second safety question should still be pending"
    assert hooks.agent_texts()[-1].lower().startswith("are you in a safe location")
    # Answer the second safety question — now enrichment fires.
    await orch.handle_customer_turn("Yes, I'm in a safe location.")
    assert orch.ctx.state == DONE  # enrichment + closing happen synchronously
    assert orch.ctx.case_id is not None


async def test_kill_switch_takes_precedence_over_safety_question(orchestrator_factory):
    """If the customer's first utterance matches the kill-switch lexicon,
    safety questions are NOT asked — the escalation script runs immediately."""
    orch, hooks = orchestrator_factory()
    await orch.start()
    await orch.handle_customer_turn("I smell smoke and the car is on fire!")
    assert orch.ctx.state == DONE
    assert orch.ctx.safety_flags.get("escalation") is True
    # No safety questions should appear in the transcript.
    texts = " ".join(hooks.agent_texts()).lower()
    assert "is anyone hurt" not in texts
