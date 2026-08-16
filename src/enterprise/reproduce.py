"""REPRODUCE: re-derive case severity and investigation-open decision.

Not bit-identical bytes. Same inputs → same severity + same open/not-open.
"""

from __future__ import annotations

from typing import Any

from src.agents.base import InteractionContext
from src.agents.triage import score_severity
from src.data.warehouse import ops_con
from src.domains.loader import load_pack
from src.frontline.live_intercept import slice_is_anomalous
from src.ledger import AgentAction, record_action


def stored_contact_inputs(interaction_id: str) -> dict[str, Any]:
    with ops_con(read_only=True) as con:
        ix = con.execute(
            """
            SELECT interaction_id, pack_id, entity_1, entity_2, entity_3,
                   category, description, status, outcome
            FROM interactions WHERE interaction_id = ?
            """,
            [interaction_id],
        ).fetchone()
        if not ix:
            raise LookupError(interaction_id)
        icols = [d[0] for d in con.description]
        inter = dict(zip(icols, ix))
        case = con.execute(
            "SELECT severity, priority, investigation_id FROM cases WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()
        ccols = [d[0] for d in con.description] if case else []
        case_d = dict(zip(ccols, case)) if case else {}
    return {"interaction": inter, "case": case_d}


def reproduce_contact(interaction_id: str) -> dict[str, Any]:
    """Re-run rule severity + spike-based investigation decision."""
    stored = stored_contact_inputs(interaction_id)
    inter = stored["interaction"]
    pack = load_pack(inter["pack_id"], reload=True)
    ctx = InteractionContext(interaction_id=interaction_id, pack=pack)
    ctx.slots["entity_1"] = inter.get("entity_1") or ""
    ctx.slots["entity_2"] = inter.get("entity_2") or ""
    ctx.slots["entity_3"] = inter.get("entity_3") or ""
    ctx.slots["category"] = inter.get("category") or ""
    ctx.slots["description"] = inter.get("description") or ""
    severity, source, reason = score_severity(ctx)
    spike = slice_is_anomalous(inter["pack_id"], ctx.slots.get("category"), ctx.slots.get("entity_2"))
    should_open = bool(spike.get("anomalous"))
    record_action(
        AgentAction(
            interaction_id=interaction_id,
            agent="orchestrator",
            action_type="reproduced",
            input_summary="reproduce_contact",
            output_summary=f"severity={severity}; open={should_open}",
            ok=True,
        )
    )
    original_sev = stored["case"].get("severity")
    return {
        "interaction_id": interaction_id,
        "severity": severity,
        "severity_source": source,
        "severity_reason": reason,
        "investigation_should_open": should_open,
        "original_severity": original_sev,
        "severity_matches_original": (
            original_sev is None or original_sev == severity
        ),
    }


__all__ = ["stored_contact_inputs", "reproduce_contact"]
