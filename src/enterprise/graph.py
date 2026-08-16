"""Ops knowledge graph — entities, cases, investigations, advisories as nodes/edges.

Built from warehouse joins (not a graph DB). Enough for UI exploration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data.warehouse import ops_con


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def build_ops_graph(
    *,
    pack_id: str | None = None,
    limit_cases: int = 40,
) -> dict[str, Any]:
    """Return {nodes, edges} for exploration."""
    limit_cases = min(max(int(limit_cases), 1), 200)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(nid: str, ntype: str, label: str, **meta: Any) -> None:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, **meta}

    def add_edge(src: str, dst: str, rel: str) -> None:
        edges.append({"source": src, "target": dst, "rel": rel})

    sql = """
        SELECT case_id, interaction_id, pack_id, category, severity, status,
               advisory_match_id, cluster_match_id, investigation_id,
               entity_1, entity_2, entity_3
        FROM cases
    """
    # cases table may not have entity_* — check schema
    # From schema: cases has category, description but entities are on interactions
    # Join interactions for entities
    sql = """
        SELECT c.case_id, c.interaction_id, c.pack_id, c.category, c.severity, c.status,
               c.advisory_match_id, c.cluster_match_id, c.investigation_id,
               i.entity_1, i.entity_2, i.entity_3
        FROM cases c
        LEFT JOIN interactions i ON i.interaction_id = c.interaction_id
    """
    params: list[Any] = []
    if pack_id:
        sql += " WHERE c.pack_id = ?"
        params.append(pack_id)
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    params.append(limit_cases)

    with ops_con(read_only=True) as con:
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        case_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        inv_rows = con.execute(
            """
            SELECT investigation_id, pack_id, cluster_id, title, status, case_count
            FROM investigations
            ORDER BY opened_at DESC LIMIT 50
            """
        ).fetchall()
        icols = [d[0] for d in con.description]
        investigations = [dict(zip(icols, r)) for r in inv_rows]

    for inv in investigations:
        if pack_id and inv.get("pack_id") != pack_id:
            continue
        iid = inv["investigation_id"]
        add_node(f"inv:{iid}", "investigation", inv.get("title") or iid, status=inv.get("status"))
        cid = inv.get("cluster_id")
        if cid is not None:
            add_node(f"cluster:{cid}", "cluster", f"Cluster {cid}")
            add_edge(f"inv:{iid}", f"cluster:{cid}", "investigates")

    for c in case_rows:
        cid = c["case_id"]
        add_node(
            f"case:{cid}",
            "case",
            cid,
            severity=c.get("severity"),
            status=c.get("status"),
            category=c.get("category"),
        )
        if c.get("interaction_id"):
            add_node(f"ix:{c['interaction_id']}", "interaction", c["interaction_id"])
            add_edge(f"case:{cid}", f"ix:{c['interaction_id']}", "from_contact")
        if c.get("category"):
            cat = str(c["category"])
            add_node(f"cat:{cat}", "category", cat)
            add_edge(f"case:{cid}", f"cat:{cat}", "about")
        for slot, key in (("entity_1", "e1"), ("entity_2", "e2"), ("entity_3", "e3")):
            val = c.get(slot)
            if val:
                nid = f"ent:{key}:{val}"
                add_node(nid, "entity", str(val), slot=slot)
                add_edge(f"case:{cid}", nid, "involves")
        if c.get("advisory_match_id"):
            aid = c["advisory_match_id"]
            add_node(f"adv:{aid}", "advisory", aid)
            add_edge(f"case:{cid}", f"adv:{aid}", "matched_advisory")
        if c.get("cluster_match_id") is not None:
            cl = c["cluster_match_id"]
            add_node(f"cluster:{cl}", "cluster", f"Cluster {cl}")
            add_edge(f"case:{cid}", f"cluster:{cl}", "in_cluster")
        if c.get("investigation_id"):
            inv = c["investigation_id"]
            add_node(f"inv:{inv}", "investigation", inv)
            add_edge(f"case:{cid}", f"inv:{inv}", "linked_investigation")

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "pack_id": pack_id,
    }
