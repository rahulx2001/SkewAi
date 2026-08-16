"""Live cluster intercept: one contact re-scores the slice and can open an investigation."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con
from src.ids import new_ulid
from src.ledger import AgentAction, record_action
from src.ml_runtime.anomalies import recompute_weekly_anomalies


def slice_is_anomalous(pack_id: str, category: str | None, entity_2: str | None) -> dict[str, Any]:
    scored = recompute_weekly_anomalies(pack_id, category=category, entity_2=entity_2)
    hits = [
        r
        for r in scored
        if r.get("is_anomaly")
        and (not category or r.get("category") == category)
        and (not entity_2 or r.get("entity_2") == entity_2)
    ]
    hits.sort(key=lambda r: float(r.get("z_score") or 0), reverse=True)
    top = hits[0] if hits else None
    return {"anomalous": bool(top), "slice": top, "scored": len(scored)}


def open_or_link_investigation(
    *,
    pack_id: str,
    cluster_id: int = 0,
    title: str | None = None,
) -> str:
    with ops_con() as con:
        row = con.execute(
            """
            SELECT investigation_id FROM investigations
            WHERE pack_id = ? AND cluster_id = ? AND status = 'open'
            LIMIT 1
            """,
            [pack_id, cluster_id],
        ).fetchone()
        if row:
            return str(row[0])
        seq = con.execute("SELECT nextval('investigation_seq')").fetchone()
        inv_id = f"inv_{int(seq[0]):04d}" if seq else "inv_" + new_ulid()[:8]
        con.execute(
            """
            INSERT INTO investigations
            (investigation_id, pack_id, cluster_id, title, status,
             opened_at, last_case_at, case_count)
            VALUES (?, ?, ?, ?, 'open', ?, ?, 1)
            """,
            [
                inv_id,
                pack_id,
                cluster_id,
                title or f"Live intercept cluster {cluster_id}",
                utc_now(),
                utc_now(),
            ],
        )
    return inv_id


def intercept_contact(ctx: Any) -> dict[str, Any]:
    """Re-score anomalies for this contact's slice; open/link investigation if spiked."""
    pack_id = ctx.pack.id if getattr(ctx, "pack", None) else None
    if not pack_id:
        return {"anomalous": False, "investigation_id": None}
    cat = (ctx.slots or {}).get("category")
    ent = (ctx.slots or {}).get("entity_2")
    result = slice_is_anomalous(pack_id, cat, ent)
    try:
        from src.qubot.retrievers import live_risk

        result["live_risk"] = [
            r for r in live_risk(7) if not pack_id or r.get("pack_id") == pack_id
        ]
    except Exception:
        result["live_risk"] = []
    inv_id = None
    if result["anomalous"]:
        cluster_id = 0
        if getattr(ctx, "investigation_brief", None) and ctx.investigation_brief.get("cluster_id") is not None:
            cluster_id = int(ctx.investigation_brief["cluster_id"])
        inv_id = open_or_link_investigation(
            pack_id=pack_id,
            cluster_id=cluster_id,
            title=f"Live intercept {cat or ''} {ent or ''}".strip(),
        )
        ctx.investigation_id = inv_id
        record_action(
            AgentAction(
                interaction_id=ctx.interaction_id,
                agent="investigator",
                action_type="live_intercept",
                input_summary=f"slice={cat}/{ent}",
                output_summary=f"investigation_id={inv_id}; anomalous=true",
                evidence_ids=[inv_id],
                ok=True,
            )
        )
    result["investigation_id"] = inv_id
    return result


__all__ = ["slice_is_anomalous", "open_or_link_investigation", "intercept_contact"]
