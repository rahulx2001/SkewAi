"""Decision flow visualizer — agent DAG from the action ledger for one contact.

Nodes = agents / system stages; edges = sequential handoffs inferred from
action order. Complements incident timeline with a flow graph shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data.warehouse import ops_con


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


# Canonical pipeline order for layout hints
_STAGE_ORDER = [
    "orchestrator",
    "intake",
    "sentiment",
    "triage",
    "sentinel",
    "investigator",
    "case",
    "supervisor",
]


def build_decision_flow(interaction_id: str) -> dict[str, Any]:
    with ops_con(read_only=True) as con:
        exists = con.execute(
            "SELECT 1 FROM interactions WHERE interaction_id = ?",
            [interaction_id],
        ).fetchone()
        if not exists:
            raise LookupError(f"interaction not found: {interaction_id}")
        cur = con.execute(
            """
            SELECT action_id, agent, action_type, ok, error, duration_ms, ts, evidence_ids
            FROM agent_actions
            WHERE interaction_id = ?
            ORDER BY ts
            """,
            [interaction_id],
        )
        cols = [d[0] for d in cur.description]
        actions = [dict(zip(cols, r)) for r in cur.fetchall()]

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    action_nodes: list[str] = []

    for a in actions:
        aid = a["action_id"]
        agent = a.get("agent") or "unknown"
        atype = a.get("action_type") or "action"
        nid = f"act:{aid}"
        nodes[nid] = {
            "id": nid,
            "type": "action",
            "agent": agent,
            "action_type": atype,
            "label": f"{agent}:{atype}",
            "ok": a.get("ok"),
            "error": a.get("error"),
            "duration_ms": a.get("duration_ms"),
            "ts": _iso(a.get("ts")),
        }
        # agent pool node
        ag_id = f"agent:{agent}"
        if ag_id not in nodes:
            order = _STAGE_ORDER.index(agent) if agent in _STAGE_ORDER else 99
            nodes[ag_id] = {
                "id": ag_id,
                "type": "agent",
                "label": agent,
                "stage_order": order,
            }
        edges.append({"source": ag_id, "target": nid, "rel": "performed"})
        if action_nodes:
            edges.append(
                {
                    "source": action_nodes[-1],
                    "target": nid,
                    "rel": "then",
                }
            )
        action_nodes.append(nid)

    # Stage sequence edges between agents that appeared
    seen_agents = []
    for a in actions:
        ag = a.get("agent")
        if ag and ag not in seen_agents:
            if seen_agents:
                edges.append(
                    {
                        "source": f"agent:{seen_agents[-1]}",
                        "target": f"agent:{ag}",
                        "rel": "pipeline",
                    }
                )
            seen_agents.append(ag)

    return {
        "interaction_id": interaction_id,
        "nodes": list(nodes.values()),
        "edges": edges,
        "action_count": len(actions),
        "agents_in_order": seen_agents,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
