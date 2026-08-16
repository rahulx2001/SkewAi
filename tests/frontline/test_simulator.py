"""Traffic simulator tests (per blueprint §15.2).

Covers:
  - record → persona conversion (ScriptedContact.turns is a non-empty list)
  - channel='simulated' marking on the interaction row
  - $0 LLM guarantee (no LLM calls recorded for simulated interactions)
"""

from __future__ import annotations

import pytest

from src.frontline.simulator import ScriptedContact, SimResult, simulate, _turn_from_record


# ── Record → persona conversion ───────────────────────────────────────────────


def test_turn_from_record_builds_utterances(pack, seed_automotive_pack):
    """A corpus record is converted into a non-empty list of caller utterances."""
    record = {
        "record_id": "NHTSA-100001",
        "entity_1": "2019",
        "entity_2": "HONDA",
        "entity_3": "CR-V",
        "category": "SERVICE BRAKES",
        "text": "Grinding noise when braking at low speed.",
    }
    turns = _turn_from_record(record)
    assert isinstance(turns, list)
    assert len(turns) >= 2
    # The first turn mentions the vehicle (year make model).
    assert "2019" in turns[0]
    assert "honda" in turns[0].lower()
    assert "cr-v" in turns[0].lower()


def test_turn_from_record_includes_safety_ack(pack, seed_automotive_pack):
    """The simulator always appends a 'nobody is hurt' safety ack so the
    orchestrator doesn't escalate on simulated traffic."""
    record = {
        "record_id": "NHTSA-X",
        "entity_1": "2020",
        "entity_2": "FORD",
        "entity_3": "F-150",
        "category": "ELECTRICAL SYSTEM",
        "text": "Power window stopped working.",
    }
    turns = _turn_from_record(record)
    last = turns[-1].lower()
    assert "safe" in last or "nobody" in last


# ── channel='simulated' marking ──────────────────────────────────────────────


async def test_simulated_channel_marked_on_interaction(pack, seed_automotive_pack, reset_ops_db):
    """Every interaction created by the simulator has channel='simulated'."""
    from src.data.warehouse import ops_con

    result = await simulate(count=3, pack_id="automotive_nhtsa", seed=42)
    assert result.completed == 3
    assert result.errors == []

    with ops_con(read_only=True) as con:
        rows = con.execute(
            "SELECT channel FROM interactions WHERE channel = 'simulated'"
        ).fetchall()
    assert len(rows) == 3, "expected 3 simulated interactions in the ops warehouse"


# ── $0 LLM guarantee ──────────────────────────────────────────────────────────


async def test_simulator_makes_zero_llm_calls(pack, seed_automotive_pack, reset_ops_db):
    """Simulated interactions must record llm_calls=0."""
    from src.data.warehouse import ops_con

    result = await simulate(count=3, pack_id="automotive_nhtsa", seed=42)
    assert result.completed == 3
    assert result.errors == []

    with ops_con(read_only=True) as con:
        rows = con.execute(
            "SELECT llm_calls FROM interactions WHERE channel = 'simulated'"
        ).fetchall()
    for (llm_calls,) in rows:
        assert llm_calls == 0, "simulator must not call any LLM"


# ── Determinism with seed ─────────────────────────────────────────────────────


async def test_simulator_seed_deterministic(pack, seed_automotive_pack, reset_ops_db):
    """The same seed yields the same number of completed contacts (deterministic)."""
    r1 = await simulate(count=3, pack_id="automotive_nhtsa", seed=42)
    assert r1.errors == []
    assert r1.completed == 3


async def test_simulator_handles_empty_warehouse(reset_ops_db):
    """If the domain warehouse has no records, the simulator returns errors
    instead of crashing."""
    from src.config import settings
    from src.data.warehouse import init_domain_db

    # Wipe + re-init the domain warehouse so it has schema but zero rows.
    path = settings.domain_db_path("automotive_nhtsa")
    if path.exists():
        path.unlink()
    init_domain_db("automotive_nhtsa")

    result = await simulate(count=3, pack_id="automotive_nhtsa", seed=42)
    assert result.completed == 0
    assert len(result.errors) >= 1


# ── SimResult shape ──────────────────────────────────────────────────────────


async def test_simulator_returns_simresult(pack, seed_automotive_pack, reset_ops_db):
    result = await simulate(count=2, pack_id="automotive_nhtsa", seed=1)
    assert isinstance(result, SimResult)
    assert result.completed >= 1
    assert isinstance(result.errors, list)


async def test_simulator_cases_created(pack, seed_automotive_pack, reset_ops_db):
    """Each completed simulated contact should create a case."""
    result = await simulate(count=3, pack_id="automotive_nhtsa", seed=42)
    assert result.completed == 3
    assert result.cases_created == 3
