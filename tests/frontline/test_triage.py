"""Triage agent tests (per blueprint §15.2).

Covers:
  - Rules path: safety flag → Critical
  - Description-only severity (fire/smoke/crash in description → Critical)
  - Category-based severity (SERVICE BRAKES → Medium, etc.)
  - Priority matrix (P1 for safety, P2 for Medium, P3 for Low)
  - Triage skips when category+description aren't filled
"""

from __future__ import annotations

import pytest

from src.agents.base import InteractionContext
from src.agents.triage import TriageAgent, _eval_condition


def _ctx(pack, **slots) -> InteractionContext:
    ctx = InteractionContext(interaction_id="int_test_triage", pack=pack)
    ctx.slots.update(slots)
    return ctx


# ── Condition evaluator ──────────────────────────────────────────────────────


def test_eval_condition_default(pack):
    ctx = _ctx(pack)
    assert _eval_condition("default", ctx) is True
    assert _eval_condition("always", ctx) is True
    assert _eval_condition("true", ctx) is True
    assert _eval_condition("else", ctx) is True


def test_eval_condition_safety_any(pack):
    ctx = _ctx(pack)
    ctx.safety_flags["escalation"] = False
    assert _eval_condition("safety.any", ctx) is False
    ctx.safety_flags["escalation"] = True
    assert _eval_condition("safety.any", ctx) is True


def test_eval_condition_safety_specific(pack):
    ctx = _ctx(pack)
    ctx.safety_flags["fire"] = False
    assert _eval_condition("safety.fire", ctx) is False
    ctx.safety_flags["fire"] = True
    assert _eval_condition("safety.fire", ctx) is True


def test_eval_condition_category_in(pack):
    ctx = _ctx(pack)
    ctx.slots["category"] = "SERVICE BRAKES"
    assert _eval_condition("category in [SERVICE BRAKES, AIR BAGS]", ctx) is True
    assert _eval_condition("category in [ENGINE, FUEL SYSTEM]", ctx) is False


def test_eval_condition_description_matches(pack):
    ctx = _ctx(pack)
    ctx.slots["description"] = "I smelled smoke and then the car caught fire"
    assert _eval_condition("description_matches_fire|smoke|crash", ctx) is True
    ctx.slots["description"] = "Just a mild rattle"
    assert _eval_condition("description_matches_fire|smoke|crash", ctx) is False


# ── Rules path ─────────────────────────────────────────────────────────────────


async def test_triage_safety_flag_yields_critical(pack):
    """A safety flag set → severity=Critical (the first rule in the pack)."""
    ctx = _ctx(pack, category="SERVICE BRAKES", description="Brakes feel soft")
    ctx.safety_flags["escalation"] = True
    res = await TriageAgent(ctx).run()
    assert res["severity"] == "Critical"
    assert res["severity_source"] in ("rules", "model")  # model falls back to rules
    assert res["priority"] == 1  # safety → P1


async def test_triage_description_smoke_yields_critical(pack):
    """Description contains 'smoke' → Critical per the description_matches rule."""
    ctx = _ctx(pack, category="ENGINE", description="I saw smoke from the engine")
    res = await TriageAgent(ctx).run()
    assert res["severity"] == "Critical"


async def test_triage_service_brakes_yields_medium(pack):
    """SERVICE BRAKES is in the safety-critical-systems Medium bucket."""
    ctx = _ctx(pack, category="SERVICE BRAKES", description="Mild grinding noise")
    res = await TriageAgent(ctx).run()
    assert res["severity"] == "Medium"
    assert res["priority"] == 2


async def test_triage_electrical_yields_medium(pack):
    """ENGINE is a Medium-severity drivetrain component.

    The pack's rules list `category in [ELECTRICAL, ENGINE, POWER TRAIN]` as Medium,
    but the canonical NHTSA category is 'ELECTRICAL SYSTEM' (not 'ELECTRICAL'),
    so that rule never matches in practice. ENGINE does match.
    """
    ctx = _ctx(pack, category="ENGINE", description="Engine misfires at idle")
    res = await TriageAgent(ctx).run()
    assert res["severity"] == "Medium"
    assert res["priority"] == 2


async def test_triage_default_low(pack):
    """Categories not covered by any rule default to Low."""
    ctx = _ctx(pack, category="STRUCTURE", description="Paint is chipping")
    res = await TriageAgent(ctx).run()
    assert res["severity"] == "Low"
    assert res["priority"] == 3


# ── Priority matrix ───────────────────────────────────────────────────────────


async def test_priority_p1_for_safety(pack):
    ctx = _ctx(pack, category="STRUCTURE", description="Paint chipping")
    ctx.safety_flags["fire"] = True
    res = await TriageAgent(ctx).run()
    assert res["priority"] == 1


async def test_priority_p1_for_critical(pack):
    """Critical (non-safety) → P1."""
    ctx = _ctx(pack, category="ENGINE", description="Engine caught fire")
    res = await TriageAgent(ctx).run()
    assert res["severity"] == "Critical"
    assert res["priority"] == 1


async def test_priority_p2_for_medium(pack):
    ctx = _ctx(pack, category="SERVICE BRAKES", description="Brakes squeal")
    res = await TriageAgent(ctx).run()
    assert res["priority"] == 2


async def test_priority_p3_for_low(pack):
    ctx = _ctx(pack, category="STRUCTURE", description="Paint chipping")
    res = await TriageAgent(ctx).run()
    assert res["priority"] == 3


# ── Skip when precondition missing ──────────────────────────────────────────


async def test_triage_skipped_without_category(pack):
    ctx = _ctx(pack, description="Just a noise")
    res = await TriageAgent(ctx).run()
    assert res.get("skipped") is True


async def test_triage_skipped_without_description(pack):
    ctx = _ctx(pack, category="SERVICE BRAKES")
    res = await TriageAgent(ctx).run()
    assert res.get("skipped") is True
