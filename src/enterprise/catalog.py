"""Enterprise catalog helpers — recent interactions for ops pickers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data.warehouse import ops_con


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def list_recent_interactions(
    *,
    limit: int = 25,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Newest interactions for timeline / RCA / decision-flow pickers."""
    limit = min(max(int(limit), 1), 100)
    sql = """
        SELECT i.interaction_id, i.pack_id, i.status, i.outcome, i.channel,
               i.peak_frustration, i.started_at, i.ended_at,
               i.entity_1, i.entity_2, i.entity_3, i.category,
               c.case_id, c.severity AS case_severity
        FROM interactions i
        LEFT JOIN cases c ON c.interaction_id = i.interaction_id
    """
    params: list[Any] = []
    if status:
        sql += " WHERE i.status = ?"
        params.append(status)
    sql += " ORDER BY i.started_at DESC LIMIT ?"
    params.append(limit)
    with ops_con(read_only=True) as con:
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k, v in list(d.items()):
                d[k] = _iso(v)
            rows.append(d)
    return rows


__all__ = ["list_recent_interactions"]
