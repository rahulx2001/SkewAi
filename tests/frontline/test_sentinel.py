"""Sentinel agent tests (per blueprint §15.2).

Covers:
  - Advisory match (Honda CR-V SERVICE BRAKES → 19V-12345)
  - No-match (Ford F-150 → no advisory)
  - Verbatim notice built from SQL columns (advisory_id, scope_summary, remedy, url)
"""

from __future__ import annotations

import pytest

from src.agents.base import InteractionContext
from src.agents.sentinel import SentinelAgent


def _ctx(pack, **slots) -> InteractionContext:
    ctx = InteractionContext(interaction_id="int_test_sentinel", pack=pack)
    ctx.slots.update(slots)
    return ctx


# ── Advisory match ────────────────────────────────────────────────────────────


async def test_advisory_match_honda_cr_v_brakes(pack):
    """Honda CR-V + SERVICE BRAKES must match advisory 19V-12345."""
    ctx = _ctx(
        pack,
        entity_1="2019",
        entity_2="HONDA",
        entity_3="CR-V",
        category="SERVICE BRAKES",
    )
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    assert res.get("advisory_match") is not None
    match = res["advisory_match"]
    assert match["advisory_id"] == "19V-12345"
    # The notice is built verbatim from the readback_fields.
    notice = res["notice"]
    assert "19V-12345" in notice
    assert "HONDA CR-V SERVICE BRAKES" in notice  # scope_summary concatenation
    assert "Dealer will replace front brake pads" in notice  # remedy
    assert "https://www.nhtsa.gov/recalls/19V-12345" in notice  # url


async def test_advisory_match_toyota_camry_airbags(pack):
    """Toyota Camry + AIR BAGS must match advisory 20V-67890."""
    ctx = _ctx(
        pack,
        entity_1="2017",
        entity_2="TOYOTA",
        entity_3="CAMRY",
        category="AIR BAGS",
    )
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    assert res.get("advisory_match") is not None
    assert res["advisory_match"]["advisory_id"] == "20V-67890"


# ── No-match ─────────────────────────────────────────────────────────────────


async def test_no_match_ford_f_150(pack):
    """Ford F-150 + ELECTRICAL SYSTEM has no advisory in the fixture."""
    ctx = _ctx(
        pack,
        entity_1="2020",
        entity_2="FORD",
        entity_3="F-150",
        category="ELECTRICAL SYSTEM",
    )
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    assert res.get("advisory_match") is None
    # Sentinel returns None advisory_match when no rows matched.
    assert "notice" not in res or res.get("notice") is None


async def test_no_match_with_unknown_make(pack):
    ctx = _ctx(
        pack,
        entity_2="UNKNOWN_MAKE",
        entity_3="UNKNOWN_MODEL",
        category="UNKNOWN_CATEGORY",
    )
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    assert res.get("advisory_match") is None


# ── Escalation trigger ────────────────────────────────────────────────────────


async def test_escalation_trigger_marks_interaction(pack):
    """The 'escalation' trigger (from Intake's kill-switch) marks the interaction."""
    ctx = _ctx(pack)
    res = await SentinelAgent(ctx).run(trigger="escalation")
    assert res["escalated"] is True
    assert res["advisory_match"] is None


# ── Skip behavior when no entities ──────────────────────────────────────────


async def test_sentinel_skips_when_no_entities(pack):
    """If no entity slots are filled, sentinel skips (no SQL run)."""
    ctx = _ctx(pack)  # no slots
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    assert res.get("skipped") is True


# ── Verbatim notice from SQL ─────────────────────────────────────────────────


async def test_notice_uses_pack_readback_fields(pack):
    """The notice must contain every field in advisory_match.readback_fields."""
    ctx = _ctx(
        pack,
        entity_2="HONDA",
        entity_3="CR-V",
        category="SERVICE BRAKES",
    )
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    notice = res["notice"]
    # Every readback field appears in the notice (title-cased).
    for field in pack.manifest.advisory_match.readback_fields:
        # Field names like 'advisory_id' become 'Advisory Id' in the notice.
        humanized = field.replace("_", " ").title()
        assert humanized in notice, f"notice missing readback field '{humanized}'"


# ── Evidence ids recorded ────────────────────────────────────────────────────


async def test_advisory_evidence_ids_recorded(pack):
    """The advisory_id is returned in evidence_ids for the ledger."""
    ctx = _ctx(
        pack,
        entity_2="HONDA",
        entity_3="CR-V",
        category="SERVICE BRAKES",
    )
    res = await SentinelAgent(ctx).run(trigger="entities_complete")
    assert "19V-12345" in res.get("evidence_ids", [])
