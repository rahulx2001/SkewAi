"""Failure root-cause explorer — deterministic post-mortem for bad outcomes.

Analyzes abandoned / escalated / incomplete contacts from ledger + turns.
Not an LLM: rule-scored factors with confidence and suggested ops fix.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.data.warehouse import ops_con


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def analyze_root_cause(interaction_id: str) -> dict[str, Any]:
    """Return root-cause analysis for one interaction."""
    with ops_con(read_only=True) as con:
        h = con.execute(
            "SELECT * FROM interactions WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()
        if not h:
            raise LookupError(f"interaction not found: {interaction_id}")
        hcols = [d[0] for d in con.description]
        ix = dict(zip(hcols, h))

        actions = con.execute(
            """
            SELECT agent, action_type, ok, error, output_summary, duration_ms, ts
            FROM agent_actions WHERE interaction_id = ? ORDER BY ts
            """,
            [interaction_id],
        ).fetchall()
        acols = [d[0] for d in con.description]

        turns = con.execute(
            """
            SELECT seq, speaker, frustration_score, text
            FROM interaction_turns WHERE interaction_id = ? ORDER BY seq
            """,
            [interaction_id],
        ).fetchall()
        tcols = [d[0] for d in con.description]

        case = con.execute(
            "SELECT case_id, severity, priority, status FROM cases WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()

    action_rows = [dict(zip(acols, r)) for r in actions]
    turn_rows = [dict(zip(tcols, r)) for r in turns]

    factors: list[dict[str, Any]] = []
    blame_agent: str | None = None
    failed_actions = [a for a in action_rows if a.get("ok") is False]
    if failed_actions:
        last = failed_actions[-1]
        blame_agent = last.get("agent")
        factors.append(
            {
                "code": "agent_error",
                "weight": 0.35,
                "detail": f"{last.get('agent')}:{last.get('action_type')} error={last.get('error')}",
            }
        )

    status = (ix.get("status") or "").lower()
    outcome = (ix.get("outcome") or "").lower()
    peak_fr = float(ix.get("peak_frustration") or 0.0)

    if status == "abandoned" or outcome == "incomplete":
        factors.append(
            {
                "code": "abandoned_or_incomplete",
                "weight": 0.3,
                "detail": f"status={status} outcome={outcome}",
            }
        )
    if status == "escalated" or outcome == "escalated_safety":
        factors.append(
            {
                "code": "safety_or_escalation",
                "weight": 0.4,
                "detail": "Contact hit safety/escalation path",
            }
        )
        blame_agent = blame_agent or "sentinel"
    if peak_fr >= 0.65:
        factors.append(
            {
                "code": "high_frustration",
                "weight": 0.25,
                "detail": f"peak_frustration={peak_fr:.2f}",
            }
        )
        if not blame_agent:
            blame_agent = "sentiment"

    # Slot fill: missing entity columns
    missing_slots = [
        s
        for s in ("entity_1", "entity_2", "entity_3", "category")
        if not ix.get(s)
    ]
    if missing_slots and status in ("abandoned", "completed"):
        factors.append(
            {
                "code": "incomplete_slots",
                "weight": 0.2,
                "detail": f"missing={missing_slots}",
            }
        )
        if not blame_agent:
            blame_agent = "intake"

    cust_turns = [t for t in turn_rows if t.get("speaker") == "customer"]
    if len(cust_turns) <= 1 and status != "active":
        factors.append(
            {
                "code": "early_drop",
                "weight": 0.15,
                "detail": f"only {len(cust_turns)} customer turn(s)",
            }
        )

    if not factors:
        factors.append(
            {
                "code": "no_failure_signal",
                "weight": 0.05,
                "detail": "Contact completed without strong failure markers",
            }
        )

    total_w = sum(f["weight"] for f in factors) or 1.0
    confidence = min(0.95, round(total_w / 1.2, 2))
    primary = max(factors, key=lambda f: f["weight"])

    suggestions = {
        "agent_error": "Inspect failed agent_action rows; fix error path and re-run contact audit.",
        "abandoned_or_incomplete": "Review intake questions; reduce turn count or clarify first ask.",
        "safety_or_escalation": "Validate kill-switch terms and escalation script; ensure P1 case created.",
        "high_frustration": "Offer human handoff earlier; tune FRUSTRATION_THRESHOLD for this pack.",
        "incomplete_slots": "Check gazetteers and slot questions for entity extraction gaps.",
        "early_drop": "Shorten greeting; ask highest-value slot first.",
        "no_failure_signal": "No corrective action required; use for baseline comparison.",
    }
    suggested_fix = suggestions.get(primary["code"], "Review full incident timeline.")

    # Similar historical: association (category/entity), not recency LIMIT 5
    similar: list[dict[str, Any]] = []
    with ops_con(read_only=True) as con:
        rows = con.execute(
            """
            SELECT interaction_id, status, outcome, peak_frustration,
                   category, entity_2, entity_3, started_at
            FROM interactions
            WHERE interaction_id != ?
            """,
            [interaction_id],
        ).fetchall()
        scols = [d[0] for d in con.description]
        pool = []
        for r in rows:
            d = dict(zip(scols, r))
            pool.append(d)
        from src.ml_runtime.association import rank_by_association

        query = {
            "interaction_id": interaction_id,
            "category": ix.get("category"),
            "entity_2": ix.get("entity_2"),
            "entity_3": ix.get("entity_3"),
            "status": ix.get("status"),
            "outcome": ix.get("outcome"),
        }
        ranked = rank_by_association(
            query, pool, pool, top_k=5, id_key="interaction_id"
        )
        for d in ranked:
            d["started_at"] = _iso(d.get("started_at"))
            similar.append(d)

    for k, v in list(ix.items()):
        ix[k] = _iso(v)

    is_failure = (
        status in ("abandoned", "escalated")
        or outcome in ("incomplete", "escalated_safety")
        or bool(failed_actions)
        or peak_fr >= 0.85
    )

    return {
        "interaction_id": interaction_id,
        "is_failure": is_failure,
        "primary_cause": primary["code"],
        "why": primary["detail"],
        "blame_agent": blame_agent or "orchestrator",
        "confidence": confidence,
        "suggested_fix": suggested_fix,
        "factors": factors,
        "failed_action_count": len(failed_actions),
        "peak_frustration": peak_fr,
        "status": status,
        "outcome": outcome,
        "case": (
            {"case_id": case[0], "severity": case[1], "priority": case[2], "status": case[3]}
            if case
            else None
        ),
        "similar_historical": similar,
        "interaction": ix,
    }


def list_failure_postmortems(limit: int = 25) -> list[dict[str, Any]]:
    """List recent failure-like interactions with lightweight analyses."""
    limit = min(max(int(limit), 1), 100)
    with ops_con(read_only=True) as con:
        rows = con.execute(
            """
            SELECT interaction_id FROM interactions
            WHERE status IN ('abandoned', 'escalated')
               OR outcome IN ('incomplete', 'escalated_safety')
               OR COALESCE(peak_frustration, 0) >= 0.85
            ORDER BY COALESCE(ended_at, started_at) DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
    out = []
    for (iid,) in rows:
        try:
            full = analyze_root_cause(iid)
            out.append(
                {
                    "interaction_id": iid,
                    "primary_cause": full["primary_cause"],
                    "blame_agent": full["blame_agent"],
                    "confidence": full["confidence"],
                    "suggested_fix": full["suggested_fix"],
                    "status": full["status"],
                    "outcome": full["outcome"],
                }
            )
        except Exception:
            continue
    return out
