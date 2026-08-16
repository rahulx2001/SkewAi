"""Wallboard metrics from real ops tables (feature #54)."""

from __future__ import annotations

from typing import Any

from src.data.timeutil import utc_now
from src.data.warehouse import ops_con


def build_wallboard(*, pack_id: str | None = None, limit_clusters: int = 5) -> dict[str, Any]:
    """Live contacts, P1/open counts, top risk clusters."""
    with ops_con(read_only=True) as con:
        active = con.execute(
            """
            SELECT COUNT(*) FROM interactions WHERE status = 'active'
            """
        ).fetchone()[0]
        completed = con.execute(
            """
            SELECT COUNT(*) FROM interactions WHERE status IN ('completed', 'escalated')
            """
        ).fetchone()[0]
        open_cases = con.execute(
            "SELECT COUNT(*) FROM cases WHERE status IN ('open', 'pending_followup')"
        ).fetchone()[0]
        p1 = con.execute(
            "SELECT COUNT(*) FROM cases WHERE priority = 1 AND status IN ('open', 'pending_followup')"
        ).fetchone()[0]
        critical = con.execute(
            "SELECT COUNT(*) FROM cases WHERE severity = 'Critical' AND status IN ('open', 'pending_followup')"
        ).fetchone()[0]

        # Top clusters by live case volume.
        # Severity rank via CASE — lexical MAX('Critical','Low') is wrong ('Low').
        sql = """
            SELECT cluster_match_id, pack_id, COUNT(*) AS n,
                   MAX(CASE severity
                         WHEN 'Critical' THEN 3
                         WHEN 'Medium' THEN 2
                         WHEN 'Low' THEN 1
                         ELSE 0
                       END) AS max_sev_rank
            FROM cases
            WHERE cluster_match_id IS NOT NULL
              AND status IN ('open', 'pending_followup')
        """
        params: list[Any] = []
        if pack_id:
            sql += " AND pack_id = ?"
            params.append(pack_id)
        sql += """
            GROUP BY cluster_match_id, pack_id
            ORDER BY n DESC
            LIMIT ?
        """
        params.append(int(limit_clusters))
        cur = con.execute(sql, params)
        _rank_to_sev = {3: "Critical", 2: "Medium", 1: "Low", 0: None}
        top_clusters = [
            {
                "cluster_id": r[0],
                "pack_id": r[1],
                "open_cases": r[2],
                "max_severity": _rank_to_sev.get(int(r[3] or 0)),
            }
            for r in cur.fetchall()
        ]

        live = con.execute(
            """
            SELECT interaction_id, pack_id, status, channel, started_at, category
            FROM interactions
            WHERE status = 'active'
            ORDER BY started_at DESC
            LIMIT 20
            """
        ).fetchall()
        live_contacts = [
            {
                "interaction_id": r[0],
                "pack_id": r[1],
                "status": r[2],
                "channel": r[3],
                "started_at": str(r[4]) if r[4] is not None else None,
                "category": r[5],
            }
            for r in live
        ]

    return {
        "ts": utc_now().isoformat() + "Z",
        "active_contacts": int(active),
        "completed_contacts": int(completed),
        "open_cases": int(open_cases),
        "p1_open": int(p1),
        "critical_open": int(critical),
        "top_risk_clusters": top_clusters,
        "live_contacts": live_contacts,
    }


__all__ = ["build_wallboard"]
