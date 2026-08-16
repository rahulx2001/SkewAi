"""Decision explainability from existing ledger / case / brief (no second brain)."""

from __future__ import annotations

import json
from typing import Any

from src.data.warehouse import ops_con
from src.ledger.writer import list_actions


def explain_interaction(interaction_id: str) -> dict[str, Any]:
    """Assemble why decisions happened for one contact."""
    iid = interaction_id
    out: dict[str, Any] = {
        "interaction_id": iid,
        "slots": {},
        "severity": None,
        "severity_source": None,
        "advisory": None,
        "similar_records": [],
        "cluster": None,
        "lead_time_weeks": None,
        "actions": [],
        "evidence_ids": [],
    }

    with ops_con(read_only=True) as con:
        ix = con.execute(
            """
            SELECT pack_id, entity_1, entity_2, entity_3, category, description,
                   status, outcome, peak_frustration
            FROM interactions WHERE interaction_id = ?
            """,
            [iid],
        ).fetchone()
        if not ix:
            return {**out, "found": False}
        out["found"] = True
        out["pack_id"] = ix[0]
        out["slots"] = {
            "entity_1": ix[1],
            "entity_2": ix[2],
            "entity_3": ix[3],
            "category": ix[4],
            "description": ix[5],
        }
        out["status"] = ix[6]
        out["outcome"] = ix[7]
        out["peak_frustration"] = ix[8]

        case = con.execute(
            """
            SELECT case_id, severity, severity_source, priority, advisory_match_id,
                   cluster_match_id, similar_record_count, investigation_id,
                   followup_draft, safety_flags
            FROM cases WHERE interaction_id = ?
            ORDER BY created_at ASC
            """,
            [iid],
        ).fetchall()
        cases = []
        for c in case:
            cases.append(
                {
                    "case_id": c[0],
                    "severity": c[1],
                    "severity_source": c[2],
                    "priority": c[3],
                    "advisory_match_id": c[4],
                    "cluster_match_id": c[5],
                    "similar_record_count": c[6],
                    "investigation_id": c[7],
                    "followup_draft": (c[8] or "")[:300],
                    "safety_flags": c[9],
                }
            )
        out["cases"] = cases
        if cases:
            out["severity"] = cases[0]["severity"]
            out["severity_source"] = cases[0]["severity_source"]
            if cases[0]["advisory_match_id"]:
                out["advisory"] = {"advisory_id": cases[0]["advisory_match_id"]}
            if cases[0]["cluster_match_id"] is not None:
                out["cluster"] = {"cluster_id": cases[0]["cluster_match_id"]}

        # Linked secondary issues table if present
        try:
            cur = con.execute(
                """
                SELECT issue_id, category, description, case_id, seq
                FROM contact_issues WHERE interaction_id = ? ORDER BY seq
                """,
                [iid],
            )
            cols = [d[0] for d in cur.description]
            out["issues"] = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            out["issues"] = []

    actions = list_actions(iid)
    # Summarize decision-relevant actions
    interesting = {
        "slot_extracted",
        "severity_scored",
        "priority_assigned",
        "advisory_check",
        "advisory_notified",
        "similar_search",
        "cluster_matched",
        "brief_written",
        "case_created",
        "safety_flag_raised",
        "handoff_offer_emitted",
    }
    slim = []
    evidence: list[str] = []
    for a in actions:
        if a.get("action_type") not in interesting:
            continue
        slim.append(
            {
                "action_type": a.get("action_type"),
                "agent": a.get("agent"),
                "input_summary": a.get("input_summary"),
                "output_summary": a.get("output_summary"),
                "evidence_ids": a.get("evidence_ids") or [],
            }
        )
        for e in a.get("evidence_ids") or []:
            if e and str(e) not in evidence:
                evidence.append(str(e))
        # Parse cluster / lead from summaries when present
        os_ = str(a.get("output_summary") or "")
        if a.get("action_type") == "brief_written" and "lead_time_weeks=" in os_:
            try:
                part = os_.split("lead_time_weeks=")[1].split(",")[0]
                out["lead_time_weeks"] = int(part) if part not in ("None", "") else None
            except Exception:
                pass
        if a.get("action_type") == "similar_search":
            out["similar_records"] = a.get("evidence_ids") or []
    out["actions"] = slim
    out["evidence_ids"] = evidence

    # Narrative bullets for UI
    bullets = []
    if out["slots"].get("entity_2"):
        bullets.append(
            f"Entities captured: "
            f"{out['slots'].get('entity_1')} / {out['slots'].get('entity_2')} / "
            f"{out['slots'].get('entity_3')} · category={out['slots'].get('category')}"
        )
    if out.get("severity"):
        bullets.append(
            f"Severity={out['severity']} (source={out.get('severity_source')})"
        )
    if out.get("advisory"):
        bullets.append(f"Advisory match: {out['advisory'].get('advisory_id')}")
    if out.get("cluster"):
        bullets.append(f"Cluster match: #{out['cluster'].get('cluster_id')}")
    if out.get("lead_time_weeks") is not None:
        bullets.append(
            f"Historical lead time vs advisory: {out['lead_time_weeks']} weeks"
        )
    if out.get("similar_records"):
        bullets.append(
            f"Similar records ({len(out['similar_records'])}): "
            + ", ".join(str(x) for x in out["similar_records"][:5])
        )
    out["summary_bullets"] = bullets
    return out


__all__ = ["explain_interaction"]
