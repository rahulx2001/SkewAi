"""Non-conversational complaint ingest (feature #12).

Accepts a complete payload and runs create_interaction + slot fill + enrich
without a WebSocket.
"""

from __future__ import annotations

from typing import Any

from src.agents.orchestrator import create_interaction
from src.data.timeutil import utc_now
from src.data.warehouse import ops_con


async def ingest_complaint(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the real orchestrator path for a batch complaint.

    Payload fields (optional unless noted):
      pack_id, channel, entity_1, entity_2, entity_3, category, description,
      text (alias for description), customer_name
    """
    pack_id = payload.get("pack_id")
    channel = payload.get("channel") or "webhook"
    description = (payload.get("description") or payload.get("text") or "").strip()
    orch, greeting = await create_interaction(channel=channel, pack_id=pack_id)

    # Pre-fill slots from payload
    for key in ("entity_1", "entity_2", "entity_3", "category", "description"):
        val = payload.get(key)
        if key == "description" and not val:
            val = description
        if val:
            orch.ctx.slots[str(key)] = str(val).strip()

    # Drive turns if description present and slots incomplete
    if description:
        await orch.handle_customer_turn(description)
    # Safety answers for packs that ask
    if not orch.ctx.has_required_slots():
        await orch.handle_customer_turn("Nobody is hurt and I am in a safe location.")
    if orch.ctx.state not in ("DONE", "ABANDONED"):
        # Force wrap if still collecting
        if orch.ctx.has_required_slots() or orch.ctx.slots.get("description"):
            try:
                await orch._enter_enriching()  # type: ignore[attr-defined]
            except Exception:
                await orch.hangup()
        else:
            await orch.hangup()

    return {
        "interaction_id": orch.ctx.interaction_id,
        "state": orch.ctx.state,
        "case_id": orch.ctx.case_id,
        "slots": {k: v for k, v in orch.ctx.slots.items() if not str(k).startswith("__")},
        "greeting": greeting,
        "severity": getattr(orch.ctx, "severity", None),
        "pack_id": orch.ctx.pack.id if orch.ctx.pack else pack_id,
        "ingested_at": utc_now().isoformat() + "Z",
    }


__all__ = ["ingest_complaint"]
