"""Traffic Simulator — replay corpus records as scripted contacts.

Samples real records from the active pack's domain warehouse and converts each
into a scripted contact: entities + category from the record's columns, the
caller's "utterances" templated from the record's narrative text. Replays them
through the real orchestrator over the simulated channel adapter — same agents,
same ledger, same audits.

LLM-free: fast-path + stubbed narrations, same stubbing as the offline eval
harness. Simulating 25 contacts costs $0 and finishes in seconds (speed:"instant")
or paced for a live-looking console (speed:"realtime").

Triggered from the dashboard button or `make simulate N=25`.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from dataclasses import dataclass, field
from typing import Any

from src.agents.orchestrator import OrchestratorHooks, create_interaction
from src.channels.simulated import SimulatedChannel
from src.config import settings
from src.data.warehouse import domain_con


# ── Persona scripting ────────────────────────────────────────────────────────


@dataclass
class ScriptedContact:
    """A scripted contact replayed through the orchestrator."""

    record_id: str
    turns: list[str]
    pack_id: str = ""


def _turn_from_record(record: dict[str, Any]) -> list[str]:
    """Convert a corpus record into a list of caller utterances."""
    parts: list[str] = []
    year = record.get("entity_1") or ""
    make = record.get("entity_2") or ""
    model = record.get("entity_3") or ""
    category = record.get("category") or ""
    text = (record.get("text") or "").strip()

    # Opening turn: introduce vehicle/system + symptom
    vehicle_phrase = " ".join(p for p in [year, make, model] if p)
    if vehicle_phrase:
        if text:
            parts.append(f"My {vehicle_phrase} — {text.lower()}.")
        else:
            parts.append(f"I'm calling about my {vehicle_phrase}.")
    elif text:
        parts.append(text)

    # Optional second turn: confirm the system / category
    if category:
        # Reuse a small variation pool to keep sim realistic
        variations = [
            f"Yes, it's the {category.lower()} system.",
            f"Right, the issue is with the {category.lower()}.",
            f"Correct — {category.lower()}.",
        ]
        parts.append(variations[random.randrange(len(variations))])

    # Safety ack: pretend nobody is hurt (always safe — simulator is for volume)
    parts.append("Nobody is hurt and I'm in a safe location.")

    return parts


# ── Sample records ────────────────────────────────────────────────────────────


def _sample_records(pack_id: str, count: int) -> list[dict[str, Any]]:
    """Sample N records from the pack's domain warehouse (random, with replacement if needed)."""
    try:
        with domain_con(pack_id) as con:
            cur = con.execute(
                """
                SELECT record_id, entity_1, entity_2, entity_3, category, text
                FROM records
                WHERE text IS NOT NULL AND text != ''
                ORDER BY random()
                LIMIT ?
                """,
                [count],
            )
            cols = [d[0] for d in con.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except FileNotFoundError:
        return []


# ── Simulator hooks ──────────────────────────────────────────────────────────


@dataclass
class SimHooks(OrchestratorHooks):
    """No-op hooks for the simulator. The simulated channel records everything
    we need for assertions; the hooks just keep the orchestrator happy."""

    async def emit_customer_turn(self, text: str, meta: dict[str, Any]) -> None: pass
    async def emit_activity(self, payload: dict[str, Any]) -> None: pass
    async def emit_slots_update(self, slots: dict[str, str]) -> None: pass
    async def emit_handoff_offer(self) -> None: pass
    async def emit_interaction_ended(self, payload: dict[str, Any]) -> None: pass


# ── Runner ────────────────────────────────────────────────────────────────────


@dataclass
class SimResult:
    """Result of a simulation run."""

    completed: int = 0
    abandoned: int = 0
    escalated: int = 0
    cases_created: int = 0
    investigations_opened: int = 0
    errors: list[str] = field(default_factory=list)


async def _run_one(contact: ScriptedContact, hooks: OrchestratorHooks) -> dict[str, Any]:
    """Run one scripted contact through the orchestrator. Returns the final ctx state."""
    orch, _ = await create_interaction(
        channel="simulated", pack_id=contact.pack_id, hooks=hooks
    )
    for turn in contact.turns:
        if orch.ctx.state in ("DONE", "ABANDONED"):
            break
        await orch.handle_customer_turn(turn)
    if orch.ctx.state != "DONE":
        await orch.hangup()
    return {
        "interaction_id": orch.ctx.interaction_id,
        "state": orch.ctx.state,
        "case_id": orch.ctx.case_id,
        "investigation_opened": orch.ctx.investigation_id is not None,
        "escalated": bool(orch.ctx.safety_flags),
    }


async def simulate(
    count: int = 25,
    pack_id: str | None = None,
    speed: str = "instant",
    seed: int | None = None,
) -> SimResult:
    """Simulate N contacts by sampling + replaying corpus records.

    Args:
        count: number of contacts to simulate.
        pack_id: pack to simulate against (default: active pack).
        speed: "instant" (no pacing) or "realtime" (small delay between contacts).
        seed: optional RNG seed for reproducibility.

    Returns: SimResult aggregate stats.
    """
    if seed is not None:
        random.seed(seed)

    from src.domains.active_pack import resolve_active_pack_id

    # Same active-pack store as contact start / Settings UI (not env alone).
    pack_id = pack_id or resolve_active_pack_id()
    records = _sample_records(pack_id, count)
    if not records:
        return SimResult(errors=[f"no records found for pack '{pack_id}'"])

    # If we got fewer records than requested, cycle through them.
    while len(records) < count:
        records.extend(records[: count - len(records)])
    records = records[:count]

    contacts = [
        ScriptedContact(
            record_id=r["record_id"],
            turns=_turn_from_record(r),
            pack_id=pack_id,
        )
        for r in records
    ]

    hooks = SimHooks()
    result = SimResult()

    for i, contact in enumerate(contacts, 1):
        try:
            res = await _run_one(contact, hooks)
            if res["state"] == "DONE":
                result.completed += 1
                if res["case_id"]:
                    result.cases_created += 1
                if res["investigation_opened"]:
                    result.investigations_opened += 1
                if res["escalated"]:
                    result.escalated += 1
            else:
                result.abandoned += 1
        except Exception as e:
            result.errors.append(f"contact {i} ({contact.record_id}): {type(e).__name__}: {e}")

        if speed == "realtime":
            await asyncio.sleep(0.3)

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────


def _main() -> int:
    parser = argparse.ArgumentParser(description="Skew AI traffic simulator")
    parser.add_argument("--count", "-n", type=int, default=25, help="Number of contacts to simulate")
    parser.add_argument("--speed", choices=["instant", "realtime"], default="instant")
    parser.add_argument("--pack", default=None, help="Pack id (default: active)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    args = parser.parse_args()

    from src.domains.active_pack import resolve_active_pack_id

    result = asyncio.run(simulate(
        count=args.count, pack_id=args.pack, speed=args.speed, seed=args.seed
    ))
    print(
        f"Simulated {args.count} contacts on pack "
        f"'{args.pack or resolve_active_pack_id()}':"
    )
    print(f"  completed:           {result.completed}")
    print(f"  abandoned:           {result.abandoned}")
    print(f"  escalated:           {result.escalated}")
    print(f"  cases_created:       {result.cases_created}")
    print(f"  investigations_opened: {result.investigations_opened}")
    if result.errors:
        print(f"  errors ({len(result.errors)}):")
        for e in result.errors[:5]:
            print(f"    - {e}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
