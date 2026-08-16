"""Persona definitions for the Frontline v2 eval harness.

Each persona is a list of customer turns + a set of expected outcomes. The eval
harness replays each persona through the orchestrator in text mode (LLM stubbed)
and asserts the expected outcomes were produced.

Personas are pack-agnostic: they describe BEHAVIOR (vague, angry, safety-critical,
etc.) and the harness adapts them to the active pack's slot frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PersonaResult:
    """Expected outcomes for a persona run."""

    # What the persona should produce
    should_escalate_safety: bool = False
    should_notify_advisory: bool = False
    should_open_investigation: bool = False
    should_flag_frustration: bool = False
    should_complete: bool = True  # False for abandoner
    max_turns: int = 12
    min_slot_fill_pct: float = 0.0  # 0 = no requirement


@dataclass
class Persona:
    """A scripted customer persona for the eval harness."""

    name: str
    description: str
    turns: list[str]
    expected: PersonaResult = field(default_factory=PersonaResult)


# ── The 8 platform personas ───────────────────────────────────────────────────
# These are written for the automotive pack. The harness can adapt them for
# other packs by substituting entity values.


AUTOMOTIVE_PERSONAS: list[Persona] = [
    Persona(
        name="cooperative",
        description="Gives all slots in the first turn; answers safety questions clearly.",
        turns=[
            "My 2019 Honda CR-V grinds when I brake.",
            "Nobody is hurt and I'm pulled over safely.",
            "Yes, I'm in a safe location right now.",
        ],
        expected=PersonaResult(min_slot_fill_pct=0.9),
    ),
    Persona(
        name="vague",
        description="Re-asks needed; says 'I don't know' once, then provides details.",
        turns=[
            "My car has a problem.",
            "I don't know, it's a Honda I think.",
            "It's a 2019 CR-V and the brakes grind when I stop.",
            "Nobody is hurt and I'm safe.",
            "Yes, I'm in a safe location.",
        ],
        expected=PersonaResult(min_slot_fill_pct=0.9),
    ),
    Persona(
        name="angry",
        description="Acts frustrated from the start; must trigger frustration_flagged + handoff offer.",
        turns=[
            "I am ABSOLUTELY FURIOUS about my 2019 Honda CR-V brakes grinding!!",
            "This is RIDICULOUS and I'm calling my lawyer!!",
            "Nobody is hurt and I'm safe.",
            "Yes, I'm in a safe location.",
        ],
        expected=PersonaResult(
            should_flag_frustration=True,
            should_notify_advisory=True,
            min_slot_fill_pct=0.7,
        ),
    ),
    Persona(
        name="safety_critical",
        description="Reports a safety-critical issue; must escalate within 1 turn.",
        turns=[
            "My 2019 Honda CR-V caught FIRE while I was driving!",
        ],
        expected=PersonaResult(
            should_escalate_safety=True,
            should_complete=True,
            max_turns=4,
        ),
    ),
    Persona(
        name="advisory_match",
        description="Planted Honda CR-V brake complaint; must notify the matching advisory.",
        turns=[
            "My 2019 Honda CR-V has a grinding noise when I brake.",
            "Nobody is hurt and I'm safe.",
            "Yes, I'm in a safe location.",
        ],
        expected=PersonaResult(
            should_notify_advisory=True,
            min_slot_fill_pct=0.9,
        ),
    ),
    Persona(
        name="investigation_trigger",
        description="Nth case on cluster #14; run multiple times to trigger investigation.",
        turns=[
            "My 2019 Honda CR-V brakes are grinding badly.",
            "Nobody is hurt and I'm safe.",
            "Yes, I'm in a safe location.",
        ],
        expected=PersonaResult(
            should_open_investigation=True,  # when run N times in sequence
            should_notify_advisory=True,
            min_slot_fill_pct=0.9,
        ),
    ),
    Persona(
        name="off_topic",
        description="Asks for legal advice; must be politely refused via pack refusal_topics.",
        turns=[
            "Can you give me legal advice about suing Honda?",
        ],
        expected=PersonaResult(
            should_complete=True,  # the agent will redirect, not abandon
            max_turns=6,
        ),
    ),
    Persona(
        name="abandoner",
        description="Hangs up after 2 turns; must not orphan a case.",
        turns=[
            "My 2019 Honda CR-V has a brake problem.",
            "Actually, I have to go. Bye.",
        ],
        expected=PersonaResult(
            should_complete=False,  # abandoned
            min_slot_fill_pct=0.0,
        ),
    ),
]


# ── Finance pack adaptation ───────────────────────────────────────────────────
# If finance_cfpb pack is built, swap the entity values. Same personas, different
# vocabulary. (The Pack Builder builds this pack; if it's not present, the eval
# just skips the finance run.)

FINANCE_PERSONAS: list[Persona] = [
    Persona(
        name="cooperative",
        description="Gives all slots in the first turn; answers finance safety questions clearly.",
        turns=[
            "My checking account at Chase was charged twice for a transfer.",
            "No, money was not taken without my permission.",
            "Yes, I contacted their fraud department.",
        ],
        expected=PersonaResult(min_slot_fill_pct=0.9),
    ),
    Persona(
        name="vague",
        description="Re-asks needed; says 'I don't know' once, then provides details.",
        turns=[
            "My bank did something wrong.",
            "I don't know, it's Chase I think.",
            "It's a checking account charged twice for a transfer.",
            "No, money was not taken without my permission.",
            "Yes, I contacted their fraud department.",
        ],
        expected=PersonaResult(min_slot_fill_pct=0.9),
    ),
    Persona(
        name="angry",
        description="Acts frustrated; must trigger frustration flag + handoff.",
        turns=[
            "I am ABSOLUTELY FURIOUS about Chase charging me twice!!",
            "This is RIDICULOUS and I'm filing a CFPB complaint!!",
            "No, money was not taken without my permission.",
            "Yes, I contacted their fraud department.",
        ],
        expected=PersonaResult(should_flag_frustration=True, min_slot_fill_pct=0.7),
    ),
    Persona(
        name="safety_critical",
        description="Reports identity theft; must escalate within 1 turn.",
        turns=[
            "I think I'm a victim of identity theft at Chase!",
        ],
        expected=PersonaResult(should_escalate_safety=True, max_turns=4),
    ),
    Persona(
        name="advisory_match",
        description="Planted Chase checking double-charge; must notify matching CFPB advisory.",
        turns=[
            "My checking account at Chase was charged twice for a transfer.",
            "No, money was not taken without my permission.",
            "Yes, I contacted their fraud department.",
        ],
        expected=PersonaResult(
            should_notify_advisory=True,
            min_slot_fill_pct=0.9,
        ),
    ),
    Persona(
        name="investigation_trigger",
        description="Nth case on cluster #41 (Chase double-charge); run multiple times to trigger investigation.",
        turns=[
            "My Chase checking account was charged twice for a transfer.",
            "No, money was not taken without my permission.",
            "Yes, I contacted their fraud department.",
        ],
        expected=PersonaResult(
            should_open_investigation=True,  # when run N times in sequence
            should_notify_advisory=True,
            min_slot_fill_pct=0.9,
        ),
    ),
    Persona(
        name="off_topic",
        description="Asks for legal advice; must be politely refused via pack refusal_topics.",
        turns=[
            "Can you give me legal advice about suing my bank?",
        ],
        expected=PersonaResult(
            should_complete=True,  # the agent will redirect, not abandon
            max_turns=6,
        ),
    ),
    Persona(
        name="abandoner",
        description="Hangs up after 2 turns; must not orphan a case.",
        turns=[
            "My Chase checking account has an issue.",
            "Actually, I have to go. Bye.",
        ],
        expected=PersonaResult(
            should_complete=False,  # abandoned
            min_slot_fill_pct=0.0,
        ),
    ),
]


def personas_for_pack(pack_id: str) -> list[Persona]:
    """Return the persona list appropriate for a pack."""
    if pack_id.startswith("finance"):
        return FINANCE_PERSONAS
    return AUTOMOTIVE_PERSONAS


__all__ = [
    "Persona",
    "PersonaResult",
    "AUTOMOTIVE_PERSONAS",
    "FINANCE_PERSONAS",
    "personas_for_pack",
]
